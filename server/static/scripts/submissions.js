class Submissions {
    constructor() {
        this.madeGraphs = new Set();
    }

    setSubmissionEnabledSwitch(checkbox, submission_id) {
        const v = checkbox.checked;
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/set_submission_active');
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function () {
            window.location.reload();
        };
        xhr.onerror = function () {
            console.log(xhr.responseText);
            const response = JSON.parse(xhr.responseText)
            this.submission_error_box.text(response.message);
            this.submission_error_box.show();
            Submissions.uncheck(checkbox, !v);
        };
        xhr.send(JSON.stringify({
            submission_id: submission_id,
            enabled: v
        }));
    }

    static uncheck(checkbox, unchecked) {
        checkbox.checked = unchecked;
    }

    onSubmit(e) {
        e.preventDefault();
        const url = this.repo_box.val();
        const _this = this;

        this.submit_spinner.show();

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/add_submission');
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function () {
            if (xhr.status !== 200) {
                _this.onSubmitFail(xhr.responseText);
                return;
            }
            const response = JSON.parse(xhr.responseText)
            if (response.status === "resent") { // Ignore resent requests
                return;
            }
            _this.submission_error_box.hide();
            window.location.reload();
        };
        xhr.onerror = function () {
            _this.onSubmitFail(xhr.responseText);
        };
        xhr.send(JSON.stringify({
            url: url
        }));
    }

    onBotSubmit(e) {
        e.preventDefault();
        const _this = this;

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/add_bot');
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function () {
            if (xhr.status !== 200) {
                _this.onSubmitFail(xhr.responseText);
                return;
            }
            _this.submission_error_box.hide();
            _this.repo_box.val("");
            window.location.reload();
        };
        xhr.onerror = function () {
            _this.onSubmitFail(xhr.responseText);
        };
        xhr.send(JSON.stringify({
            url: this.repo_box.val(),
            name: this.bot_name_box.val()
        }));
    }

    onSubmitFail(response_text) {
        console.log(response_text);
        const response = JSON.parse(response_text);
        this.submission_error_box.text(response.message);
        this.repo_box.effect("shake");
        this.submission_error_box.show();
        this.submit_spinner.hide();
    }

    deleteBot(id) {
        const xhr = new XMLHttpRequest();
        const _this = this;
        xhr.open('POST', '/api/remove_bot');
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function () {
            if (xhr.status !== 200) {
                _this.onSubmitFail(xhr.responseText);
                return;
            }
            window.location.reload();
        };
        xhr.onerror = function () {
            _this.onSubmitFail(xhr.responseText);
        };
        xhr.send(JSON.stringify({
            id: id
        }));
    }

    registerCollapse(s) {
        s = $(s);
        const _this = this;
        const id = s.data("submissionId");
        s.on('show.bs.collapse', function () {
            _this.makeGraph(id);
        });
    }

    makeGraph(id) {
        if (this.madeGraphs.has(id)) {
            return;
        }
        const s = this;

        const canvas_id = 'submissionSummaryGraph' + id;
        const objs = $("#" + canvas_id);
        if (objs.length === 0) {
            return;
        }
        objs.show();

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/get_submission_summary_graph');
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function () {
            s.madeGraphs.add(id);
            const response = JSON.parse(xhr.responseText);
            const ctx = document.getElementById(canvas_id).getContext('2d');
            const color_win = "#36e5eb";
            const color_loss = "#b536eb";
            const colors = ["#73eb37", color_win, color_loss, "#eb3636", color_win, color_loss, "#718579", color_win, color_loss, color_win, color_loss];
            let center_hidden = true;
            const data = {
                labels: ['Wins', 'Wins (Healthy)', 'Wins (Crashed)',
                    'Losses', 'Losses (Healthy)', 'Losses (Crashed)',
                    'Draws', 'Draws (Healthy)', 'Draws (Crashed)',
                    'Healthy', 'Crashed'],
                datasets: [
                    {
                        label: 'Wins & Losses',
                        data: [response.wins, 0, 0, response.losses, 0, 0, response.draws, 0, 0, 0, 0],
                        backgroundColor: colors,
                    },
                    {
                        label: 'Healthy & Not',
                        data: [0, response.wins_healthy, response.wins - response.wins_healthy,
                            0, response.losses_healthy, response.losses - response.losses_healthy,
                            0, response.draws_healthy, response.draws - response.draws_healthy,
                            0, 0],
                        backgroundColor: colors,
                        hidden: center_hidden,
                    }
                ]
            };
            const config = {
                type: 'pie',
                data: data,
                options: {
                    cutout: "33%",
                    responsive: true,
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: {
                                filter(legendItem, data) {
                                    if (legendItem.index >= 9) {
                                        return !center_hidden;
                                    }
                                    return (legendItem.index % 3) === 0;
                                },
                            },
                            onClick(e, legendItem, legend) {
                                // Stop legend selection and instead toggle crashed
                                if (this.chart.isDatasetVisible(1)) {
                                    this.chart.options.cutout = "50%";
                                    center_hidden = true;
                                    this.chart.hide(1);
                                } else {
                                    this.chart.options.cutout = "33%";
                                    center_hidden = false;
                                    this.chart.show(1);
                                }
                            },
                        },
                        title: {
                            display: true,
                            text: 'Battle Breakdown'
                        }
                    }
                },
            };
            s.chart = new Chart(ctx, config);
        };
        xhr.onerror = function () {
            $("#" + canvas_id).hide();
            console.log(xhr.responseText);
        }
        xhr.send(JSON.stringify({
            submission_id: id
        }));
    }

    registerElements() {
        this.submission_error_box = $("#submission-error-msg");
        this.repo_box = $("#repo");
        this.bot_name_box = $("#bot-name");
        this.submit_spinner = $("#submit-spinner")

        $('#submission-form').submit(e => submissions.onSubmit(e));
        $('#bot-form').submit(e => submissions.onBotSubmit(e));
        Array.from($(".submission-collapse")).forEach(s => submissions.registerCollapse(s));
    }
}

const submissions = new Submissions();
