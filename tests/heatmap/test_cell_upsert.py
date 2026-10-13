"""Cell accumulation survived being rewritten as one statement.

`_accumulate_cells` used to be a Python loop doing `get_or_create` plus an
`UPDATE` per cell — two or three round trips each, up to 5000 cells a payload,
inside one transaction, on the busiest write path in the product. It is now a
chunked `INSERT ... ON CONFLICT DO UPDATE`.

Two properties are load-bearing and neither is obvious from reading the SQL:

- `count` **adds**. Django's own `bulk_create(update_conflicts=True)` assigns
  the incoming value instead, which would replace a cell's running total with
  whatever the last flush carried — a heatmap that looks right and is wrong.
- A payload may name the same cell twice, and Postgres refuses an upsert whose
  own rows collide. That case never arose while each cell was its own statement.
"""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.heatmap.models import HeatmapActivity
from apps.heatmap.tasks import process_heatmap_payload
from apps.websites.models import Website

pytestmark = pytest.mark.django_db


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="upsert@test.com", password="Pass123!")
    team = TeamService.create(name="Upsert Agency", owner=owner)
    return Website.objects.create(
        team=team, name="Upsert Site", domain="upsert.io", heatmap_enabled=True
    )


def _payload(site_id, cells, **overrides):
    payload = {
        "site_id": site_id,
        "page_url": "https://upsert.io/",
        "device": "desktop",
        "visitor_type": "new",
        "source": "direct",
        "final": True,
        "total_clicks": 0,
        "max_scroll_percent": 50,
        "scroll_histogram": {},
        "cells": cells,
    }
    payload.update(overrides)
    return payload


def _cell(website, kind="click", x=10, y=10):
    return HeatmapActivity.objects.get(
        website=website, page_url="https://upsert.io/", kind=kind, x=x, y=y
    )


def test_duplicate_cells_in_one_payload_are_summed_not_rejected(website):
    """Postgres cannot update the same row twice in one upsert — so fold first."""
    process_heatmap_payload(
        website.site_id,
        _payload(website.site_id, [
            {"kind": "click", "x": 10, "y": 10, "count": 3},
            {"kind": "click", "x": 10, "y": 10, "count": 4},
        ]),
    )
    assert _cell(website).count == 7
    assert HeatmapActivity.objects.filter(website=website).count() == 1


def test_count_accumulates_rather_than_overwrites(website):
    for n in (5, 2, 9):
        process_heatmap_payload(
            website.site_id,
            _payload(website.site_id, [{"kind": "click", "x": 10, "y": 10, "count": n}]),
        )
    assert _cell(website).count == 16


def test_a_later_element_wins_but_a_blank_one_does_not_erase(website):
    process_heatmap_payload(
        website.site_id,
        _payload(website.site_id, [
            {"kind": "click", "x": 10, "y": 10, "count": 1, "element": "button#buy"},
        ]),
    )
    process_heatmap_payload(
        website.site_id,
        _payload(website.site_id, [
            {"kind": "click", "x": 10, "y": 10, "count": 1, "element": ""},
        ]),
    )
    cell = _cell(website)
    assert cell.element == "button#buy"
    assert cell.count == 2

    process_heatmap_payload(
        website.site_id,
        _payload(website.site_id, [
            {"kind": "click", "x": 10, "y": 10, "count": 1, "element": "a.cta"},
        ]),
    )
    assert _cell(website).element == "a.cta"


def test_segments_stay_separate_rows(website):
    """Identity is (page, kind, device, visitor type, source, x, y) — all of it."""
    process_heatmap_payload(
        website.site_id,
        _payload(website.site_id, [{"kind": "click", "x": 10, "y": 10, "count": 1}]),
    )
    process_heatmap_payload(
        website.site_id,
        _payload(
            website.site_id,
            [{"kind": "click", "x": 10, "y": 10, "count": 1}],
            device="mobile",
        ),
    )
    assert HeatmapActivity.objects.filter(website=website).count() == 2


def test_last_seen_at_advances_on_a_repeat_observation(website):
    process_heatmap_payload(
        website.site_id,
        _payload(website.site_id, [{"kind": "click", "x": 10, "y": 10, "count": 1}]),
    )
    first = _cell(website).last_seen_at

    process_heatmap_payload(
        website.site_id,
        _payload(website.site_id, [{"kind": "click", "x": 10, "y": 10, "count": 1}]),
    )
    cell = _cell(website)
    assert cell.last_seen_at >= first
    # first_seen_at is the insert's value and must not be pushed forward.
    assert cell.first_seen_at <= cell.last_seen_at


def test_a_payload_of_only_invalid_cells_writes_nothing(website):
    process_heatmap_payload(
        website.site_id,
        _payload(website.site_id, [
            {"kind": "", "x": 1, "y": 1, "count": 1},
            {"kind": "click", "x": 1, "y": 1, "count": 0},
        ]),
    )
    assert HeatmapActivity.objects.filter(website=website).count() == 0


def test_a_payload_larger_than_one_chunk_is_written_whole(website):
    """_CELL_CHUNK splits the INSERT; nothing may be lost at the seam."""
    from apps.heatmap.tasks import _CELL_CHUNK

    total = _CELL_CHUNK + 25
    cells = [
        {"kind": "move", "x": i % 101, "y": i // 101, "count": 1}
        for i in range(total)
    ]
    process_heatmap_payload(website.site_id, _payload(website.site_id, cells))
    assert HeatmapActivity.objects.filter(website=website, kind="move").count() == total
