"""report_issue() — create a ClickUp task for a Digivault issue, once.

The point of the link table is deduplication. A monitor that stays down keeps
firing; without a link, every repeat opens another task and the board fills
with duplicates of the same outage. The first report creates a task, later
reports comment on it, and once the link is closed a genuinely new occurrence
gets a fresh task.
"""
import pytest

from apps.accounts.services import TeamService
from apps.integrations.clickup import ClickUpClient
from apps.integrations.models import ClickUpTaskLink
from apps.integrations.tasks import report_issue


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class RecordingSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json})
        if url.endswith("/task"):
            return FakeResponse(200, {"id": f"task-{len(self.calls)}", "url": "https://app.clickup.com/t/x"})
        return FakeResponse(200, {"id": "comment-1"})

    def urls(self):
        return [c["url"] for c in self.calls]


@pytest.fixture
def team(db, django_user_model):
    owner = django_user_model.objects.create_user(email="cu_owner@x.io", password="Pass123!")
    t = TeamService.create(name="ClickUpCo", owner=owner)
    t.clickup_api_token = "pk_test"
    t.clickup_list_id = "list-42"
    t.save()
    return t


def _client(session):
    return ClickUpClient("pk_test", session=session)


def test_first_report_creates_a_task_and_records_the_link(team):
    session = RecordingSession()

    link = report_issue(
        team, "monitor:abc:down", title="Site down: example.com",
        body="Down since 10:00", client=_client(session),
    )

    assert link is not None
    assert link.task_id == "task-1"
    assert ClickUpTaskLink.objects.filter(team=team, subject="monitor:abc:down").count() == 1
    assert session.urls() == ["https://api.clickup.com/api/v2/list/list-42/task"]


def test_repeat_report_comments_on_the_existing_task_instead_of_creating_another(team):
    session = RecordingSession()

    first = report_issue(team, "monitor:abc:down", title="Site down", body="first", client=_client(session))
    second = report_issue(team, "monitor:abc:down", title="Site down", body="still down", client=_client(session))

    assert second.pk == first.pk
    assert ClickUpTaskLink.objects.filter(team=team).count() == 1
    assert session.urls() == [
        "https://api.clickup.com/api/v2/list/list-42/task",
        "https://api.clickup.com/api/v2/task/task-1/comment",
    ]
    assert session.calls[-1]["json"]["comment_text"] == "still down"


def test_a_closed_link_lets_the_next_occurrence_open_a_fresh_task(team):
    session = RecordingSession()
    link = report_issue(team, "monitor:abc:down", title="Site down", body="first", client=_client(session))
    link.close()

    again = report_issue(team, "monitor:abc:down", title="Site down", body="new outage", client=_client(session))

    assert again.pk != link.pk
    assert ClickUpTaskLink.objects.filter(team=team, subject="monitor:abc:down").count() == 2
    assert session.urls()[-1] == "https://api.clickup.com/api/v2/list/list-42/task"


def test_different_subjects_get_their_own_tasks(team):
    session = RecordingSession()

    report_issue(team, "monitor:abc:down", title="A", body="x", client=_client(session))
    report_issue(team, "domain:xyz:ssl", title="B", body="y", client=_client(session))

    assert ClickUpTaskLink.objects.filter(team=team).count() == 2
    assert session.urls().count("https://api.clickup.com/api/v2/list/list-42/task") == 2


def test_assignees_are_passed_through_to_the_created_task(team):
    session = RecordingSession()

    report_issue(team, "monitor:abc:down", title="A", body="x", assignees=[42], client=_client(session))

    assert session.calls[0]["json"]["assignees"] == [42]


def test_without_a_configured_list_nothing_is_sent(team):
    team.clickup_list_id = ""
    team.save()
    session = RecordingSession()

    link = report_issue(team, "monitor:abc:down", title="A", body="x", client=_client(session))

    assert link is None
    assert session.calls == []
    assert ClickUpTaskLink.objects.count() == 0
