from typing import Optional

import cuwais
from cuwais.database import User

from server import data


def make_nav_item(text, icon=None, active=False, link='#', data_toggle=None):
    return dict(text=text, icon=icon, active=active, link=link, data_toggle=data_toggle)


def make_nav_item_from_name(name, current_dir):
    is_active = (name == current_dir)
    link = f'/{name}' if not is_active else '#'
    return make_nav_item(text=name.capitalize(), link=link, active=is_active)


def make_l_nav(user: Optional[User], current_dir):
    places = []
    if user is not None:
        places += ['leaderboard', 'submissions']
    places += ['about']

    items = [make_nav_item_from_name(name, current_dir) for name in places]
    return items


def make_r_nav(user: Optional[User], current_dir):
    items = []
    if user is None:
        items.append(
            make_nav_item(text='Log In', icon='fa fa-sign-in', link='#loginModal', data_toggle='modal'))
    else:
        items.append(
            make_nav_item(text=user.display_name, link='/me', active=(current_dir == 'me')))
        items.append(
            make_nav_item(text='Log Out', icon='fa fa-sign-out', link='/logout'))
    return items


def extract_session_objs(current_dir, database_session=None):
    # If no session is passed in to jump off of, make a new one
    if database_session is None:
        with cuwais.database.create_session() as new_session:
            return extract_session_objs(current_dir, new_session)

    user = data.get_user(database_session)
    return dict(
        user=user,
        l_nav=make_l_nav(user, current_dir),
        r_nav=make_r_nav(user, current_dir)
    )