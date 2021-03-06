import logging
from datetime import timedelta, datetime
from typing import Optional, List

import cuwais.database
import jwt
from cuwais.config import config_file
from cuwais.database import User
from fastapi import FastAPI, HTTPException, Security, Cookie
from fastapi.security import SecurityScopes
from fastapi_utils.timing import add_timing_middleware
from jwt import DecodeError, InvalidTokenError
from pydantic import ValidationError
from pydantic.main import BaseModel
from starlette import status
from starlette.responses import JSONResponse, Response

from app import login, queries, repo
from app.config import DEBUG, PROFILE, ACCESS_TOKEN_EXPIRE_MINUTES, SECRET_KEY, ACCESS_TOKEN_ALGORITHM

app = FastAPI(root_path="/api")
if DEBUG and PROFILE:
    add_timing_middleware(app, record=logging.info, prefix="app", exclude="untimed")

logging.basicConfig(level=logging.DEBUG if DEBUG else logging.WARNING)


class TokenData(BaseModel):
    username: Optional[str] = None
    scopes: List[str] = []


async def get_current_user_or_none(security_scopes: SecurityScopes,
                                   response: Response,
                                   session_jwt: Optional[str] = Cookie(None),
                                   log_out: Optional[str] = Cookie(None)):
    return await _get_current_user_impl(security_scopes, response, session_jwt, log_out, raise_on_none=False)


async def get_current_user(security_scopes: SecurityScopes,
                           response: Response,
                           session_jwt: Optional[str] = Cookie(None),
                           log_out: Optional[str] = Cookie(None)):
    return await _get_current_user_impl(security_scopes, response, session_jwt, log_out, raise_on_none=True)


async def _get_current_user_impl(security_scopes: SecurityScopes,
                                 response: Response,
                                 session_jwt: Optional[str] = Cookie(None),
                                 log_out: Optional[str] = Cookie(None),
                                 raise_on_none: bool = True):
    if security_scopes.scopes:
        authenticate_value = f'Bearer scope="{security_scopes.scope_str}"'
    else:
        authenticate_value = f"Bearer"
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": authenticate_value},
    )

    def on_none():
        if session_jwt is not None:
            response.delete_cookie("session_jwt")

        if raise_on_none:
            raise credentials_exception
        else:
            return None

    if log_out is not None:
        response.delete_cookie("log_out")
        return on_none()

    if session_jwt is None:
        return on_none()

    try:
        payload = jwt.decode(session_jwt, SECRET_KEY, algorithms=[ACCESS_TOKEN_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return on_none()
        token_scopes = payload.get("scopes", [])
        token_data = TokenData(scopes=token_scopes, username=username)
    except (DecodeError, ValidationError, InvalidTokenError):
        return on_none()
    user = queries.get_user(token_data.username)
    if user is None:
        return on_none()
    for scope in security_scopes.scopes:
        if scope not in token_data.scopes:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not enough permissions",
                headers={"WWW-Authenticate": authenticate_value},
            )
    return user


def abort404():
    raise HTTPException(status_code=404, detail="Item not found")


def abort400():
    raise HTTPException(status_code=400, detail="Invalid request")


def human_format(num):
    num = float('{:.3g}'.format(num))
    magnitude = 0
    while abs(num) >= 1000:
        magnitude += 1
        num /= 1000.0
    return '{}{}'.format('{:f}'.format(num).rstrip('0').rstrip('.'), ['', 'K', 'M', 'B', 'T'][magnitude])


def reason_crash(reason):
    crash_reasons = config_file.get("localisation.crash_reasons")
    default_crash_reason = config_file.get("localisation.default_crash_reason")
    return crash_reasons.get(reason, default_crash_reason)


def validate_submission_viewable(db_session, user, submission_id):
    return queries.is_current_submission(db_session, submission_id) \
           or queries.submission_is_owned_by_user(db_session, submission_id, user)


def validate_submission_playable(db_session, user, submission_id):
    return validate_submission_viewable(db_session, user, submission_id) \
           and queries.is_submission_healthy(db_session, submission_id)


def create_access_token(token_data: dict, expires_delta: timedelta):
    to_encode = token_data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ACCESS_TOKEN_ALGORITHM)
    return encoded_jwt


def get_scopes(user: User):
    scopes = ["me", "submission.add", "submission.remove", "submission.modify", "submissions.view", "leaderboard.view"]

    if user.is_admin:
        scopes.append("bot.add")
        scopes.append("bot.remove")

    return scopes


class GoogleTokenData(BaseModel):
    google_token: str


@app.post('/exchange_google_token', response_class=JSONResponse)
async def exchange_google_token(data: GoogleTokenData, response: Response):
    with cuwais.database.create_session() as db_session:
        user = login.get_user_from_google_token(db_session, data.google_token)
        db_session.commit()

        user_id = user.id
        scopes = get_scopes(user)
        user_dict = user.to_private_dict()

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        token_data={"sub": user_id, "scopes": scopes},
        expires_delta=access_token_expires,
    )
    response.set_cookie("session_jwt", access_token, httponly=True, samesite="strict", secure=not DEBUG)
    return {"user": user_dict}


def _make_api_failure(message):
    return {"status": "fail", "message": message}


@app.post('/get_navbar', response_class=JSONResponse)
async def get_navbar(user: Optional[User] = Security(get_current_user_or_none, scopes=["me"])):
    places = ['about']
    if user is not None:
        places += ['leaderboard', 'submissions', 'you', 'logout']
    else:
        places += ['login']

    return dict(
        soc_name=config_file.get("soc_name").upper(),
        accessible=places
    )


@app.post('/get_google_login_data', response_class=JSONResponse)
async def get_login_modal_data():
    return {'clientId': config_file.get("google_client_id"), 'hostedDomain': config_file.get("allowed_email_domain")}


@app.post('/get_me', response_class=JSONResponse)
async def get_me(user: Optional[User] = Security(get_current_user, scopes=["me"])):
    return user.to_private_dict()


class AddSubmissionData(BaseModel):
    url: str


@app.post('/add_submission', response_class=JSONResponse)
async def add_submission(data: AddSubmissionData, user: User = Security(get_current_user, scopes=["submission.add"])):
    try:
        with cuwais.database.create_session() as db_session:
            submission_id = queries.create_submission(db_session, user, data.url)
            db_session.commit()
    except repo.InvalidGitURL:
        return _make_api_failure(config_file.get("localisation.git_errors.invalid-url"))
    except repo.AlreadyExistsException:
        return _make_api_failure(config_file.get("localisation.git_errors.already-submitted"))
    except repo.RepoTooBigException:
        return _make_api_failure(config_file.get("localisation.git_errors.too-large"))
    except repo.CantCloneException:
        return _make_api_failure(config_file.get("localisation.git_errors.clone-fail"))
    except repo.AlreadyCloningException:
        return {"status": "resent"}

    return {"status": "success", "submission_id": submission_id}


class BotData(BaseModel):
    name: str
    url: str


@app.post('/add_bot', response_class=JSONResponse)
async def add_bot(data: BotData, _: User = Security(get_current_user, scopes=["bot.add"])):
    with cuwais.database.create_session() as db_session:
        bot = queries.create_bot(db_session, data.name)
        db_session.flush()
        try:
            submission_id = queries.create_submission(db_session, bot, data.url)
        except repo.InvalidGitURL:
            return _make_api_failure(config_file.get("localisation.git_errors.invalid-url"))
        except repo.AlreadyExistsException:
            return _make_api_failure(config_file.get("localisation.git_errors.already-submitted"))
        except repo.RepoTooBigException:
            return _make_api_failure(config_file.get("localisation.git_errors.too-large"))
        except repo.CantCloneException:
            return _make_api_failure(config_file.get("localisation.git_errors.clone-fail"))
        db_session.commit()

    return {"status": "success", "submission_id": submission_id}


class NameVisibleData(BaseModel):
    visible: bool


@app.post('/set_name_visible', response_class=JSONResponse)
async def set_name_visible(data: NameVisibleData, user: User = Security(get_current_user, scopes=["me"])):
    with cuwais.database.create_session() as db_session:
        queries.set_user_name_visible(db_session, user, data.visible)
        db_session.commit()

    return {"status": "success"}


class RemoveBotData(BaseModel):
    bot_id: str


@app.post('/remove_bot', response_class=JSONResponse)
async def remove_bot(data: RemoveBotData, _: User = Security(get_current_user, scopes=["bot.remove"])):
    with cuwais.database.create_session() as db_session:
        queries.delete_bot(db_session, data.bot_id)
        db_session.commit()

    return {"status": "success"}


@app.post('/remove_user', response_class=JSONResponse)
async def remove_user(user: User = Security(get_current_user, scopes=["me"])):
    with cuwais.database.create_session() as db_session:
        queries.delete_user(db_session, user)
        db_session.commit()

    return {"status": "success"}


class SubmissionActiveData(BaseModel):
    submission_id: int
    enabled: bool


@app.post('/set_submission_active', response_class=JSONResponse)
async def set_submission_active(data: SubmissionActiveData,
                                user: User = Security(get_current_user, scopes=["submission.modify"])):
    with cuwais.database.create_session() as db_session:
        if not queries.submission_is_owned_by_user(db_session, data.submission_id, user.id):
            return _make_api_failure(config_file.get("localisation.submission_access_error"))

        queries.set_submission_enabled(db_session, data.submission_id, data.enabled)
        db_session.commit()

    return {"status": "success", "submission_id": data.submission_id}


@app.post('/get_leaderboard', response_class=JSONResponse)
async def get_leaderboard_data(user: User = Security(get_current_user, scopes=["leaderboard.view"])):
    with cuwais.database.create_session() as db_session:
        scoreboard = queries.get_scoreboard(db_session, user)

    def transform(item, i):
        trans = {"position": i,
                 "name": item["user"]["display_name"],
                 "is_real_name": item["user"]["display_real_name"],
                 "nickname": item["user"]["nickname"],
                 "wins": item["outcomes"]["wins"],
                 "losses": item["outcomes"]["losses"],
                 "draws": item["outcomes"]["draws"],
                 "score": item["score_text"],
                 "boarder_style": "leaderboard-user-submission" if item["is_you"]
                 else "leaderboard-bot-submission" if item["is_bot"]
                 else "leaderboard-other-submission"}

        return trans

    transformed = [transform(sub, i + 1) for i, sub in enumerate(scoreboard)]

    return {"entries": transformed}


@app.post('/get_submissions', response_class=JSONResponse)
async def get_submissions_data(user: User = Security(get_current_user, scopes=["submissions.view"])):
    with cuwais.database.create_session() as db_session:
        subs = queries.get_all_user_submissions(db_session, user, private=True)
        current_sub = queries.get_current_submission(db_session, user)

    def transform(sub, i):
        selected = current_sub is not None and sub['submission_id'] == current_sub.id

        class_names = []
        if sub['active']:
            class_names.append('submission-entry-active')
        if sub['tested'] and not sub['healthy']:
            class_names.append('invalid-stripes')
        if not sub['tested']:
            class_names.append('testing-stripes')
        if selected:
            class_names.append('submission-entry-selected')

        trans = {"div_class": " ".join(class_names),
                 "subdiv_class":
                     'submission-entry-testing' if not sub['tested']
                     else 'submission-entry-invalid' if not sub['healthy']
                     else "",
                 "index": i,
                 "submission_id": sub["submission_id"],
                 "submission_date": sub["submission_date"].strftime('%d %b at %I:%M %p'),
                 "active": sub['active'],
                 "healthy": sub['healthy'],
                 "crashed": sub['tested'] and not sub['healthy'],
                 "status": "Selected" if selected
                 else "Testing" if not sub['tested']
                 else "Invalid" if not sub['healthy']
                 else "",
                 "enabled_status": "Enabled" if sub['active'] else "Disabled",
                 }

        crash = sub['crash']
        if crash is not None:
            trans = {**trans,
                     "crash_reason": crash['result'].replace("-", " ").capitalize(),
                     "crash_reason_long": reason_crash(crash['result']),
                     "no_print": len(crash['prints']) == 0,
                     "prints": crash['prints']}

        return trans

    transformed_subs = [transform(sub, len(subs) - i)
                        for i, sub in enumerate(subs)]

    return {"submissions": transformed_subs, "no_submissions": len(transformed_subs) == 0}


@app.post('/get_bots', response_class=JSONResponse)
async def bots(_: User = Security(get_current_user, scopes=["bots.view"])):
    with cuwais.database.create_session() as db_session:
        bot_subs = queries.get_all_bot_submissions(db_session)
    return [{"id": bot.id, "name": bot.display_name, "date": sub.submission_date} for bot, sub in bot_subs]


@app.post('/get_leaderboard_over_time', response_class=JSONResponse)
async def get_leaderboard_over_time(user: User = Security(get_current_user, scopes=["leaderboard.view"])):
    with cuwais.database.create_session() as db_session:
        graph = queries.get_leaderboard_graph(db_session, user.id)

    return {"status": "success", "data": graph}


class SubmissionRequestData(BaseModel):
    submission_id: int


@app.post('/get_submission_summary_graph', response_class=JSONResponse)
async def get_submission_summary_graph(data: SubmissionRequestData,
                                       user: User = Security(get_current_user, scopes=["submissions.view"])):
    with cuwais.database.create_session() as db_session:
        if not queries.submission_is_owned_by_user(db_session, data.submission_id, user.id):
            return _make_api_failure(config_file.get("localisation.submission_access_error"))

    summary_data = queries.get_submission_summary_data(data.submission_id)

    return summary_data
