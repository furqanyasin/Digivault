import pytest

from apps.heatmaps.models import HeatmapEvent


@pytest.mark.django_db
def test_heatmap_event_can_be_created_for_active_team(auth_client, user, team):
    response = auth_client.post(
        "/api/v1/heatmaps/events/",
        {
            "page_path": "/dashboard",
            "page_title": "Dashboard",
            "event_type": "click",
            "x": 34.5,
            "y": 58.2,
            "viewport_width": 1440,
            "viewport_height": 900,
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["data"]["page_path"] == "/dashboard"
    assert response.data["data"]["event_type"] == "click"
    assert HeatmapEvent.objects.filter(team=team, user=user).count() == 1


@pytest.mark.django_db
def test_heatmap_events_are_available_to_team_manager(auth_client, user, team):
    HeatmapEvent.objects.create(
        team=team,
        user=user,
        page_path="/dashboard",
        event_type="scroll",
        y=72.1,
        viewport_width=1440,
        viewport_height=900,
    )

    response = auth_client.get("/api/v1/heatmaps/events/")

    assert response.status_code == 200
    assert response.data["data"][0]["page_path"] == "/dashboard"
    assert response.data["data"][0]["event_type"] == "scroll"
