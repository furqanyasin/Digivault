"""Tests for apps.scripts.dedup — merging cache-buster duplicate Script rows."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.dedup import merge_duplicate_scripts
from apps.scripts.models import Script, ScriptChange
from apps.websites.models import Website

pytestmark = pytest.mark.django_db


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="dedup_o@test.com", password="Pass123!")
    team = TeamService.create(name="Dedup Agency", owner=owner)
    return Website.objects.create(team=team, name="Dedup Site", domain="dedup.io")


def _make_script(website, src_url, created_offset_s=0, **kwargs):
    # Bypass ingest: simulate legacy rows that predate normalized_url by
    # writing an identity value the merge is expected to overwrite.
    script = Script.objects.create(
        website=website,
        src_url=src_url,
        normalized_url=src_url,
        **kwargs,
    )
    if created_offset_s:
        # auto_now_add can give two rows the same microsecond; "earliest
        # wins" needs unambiguous ordering.
        offset_time = timezone.now() + timedelta(seconds=created_offset_s)
        Script.objects.filter(pk=script.pk).update(
            created_at=offset_time, last_seen_at=offset_time
        )
    return script


class TestMergeDuplicateScripts:
    def test_merges_ver_variants_into_one_row(self, website):
        a = _make_script(website, "https://cdn.x.com/w.js?ver=1.0",
                         seen_on_pages=["https://site.com/a"])
        _make_script(website, "https://cdn.x.com/w.js?ver=2.0",
                     created_offset_s=60,
                     seen_on_pages=["https://site.com/b"],
                     review_status=Script.ReviewStatus.APPROVED)

        deleted = merge_duplicate_scripts(Script, ScriptChange)

        assert deleted == 1
        survivor = Script.objects.get(website=website, normalized_url="https://cdn.x.com/w.js")
        assert survivor.pk == a.pk  # earliest row wins
        assert set(survivor.seen_on_pages) == {"https://site.com/a", "https://site.com/b"}
        assert survivor.review_status == Script.ReviewStatus.APPROVED
        # src_url refreshed to the most recently seen raw form
        assert survivor.src_url == "https://cdn.x.com/w.js?ver=2.0"

    def test_repoints_script_changes(self, website):
        keeper = _make_script(website, "https://cdn.x.com/w.js?ver=1.0")
        dup = _make_script(website, "https://cdn.x.com/w.js?ver=2.0", created_offset_s=60)
        change = ScriptChange.objects.create(
            website=website, script=dup, change_type="added",
            severity="medium", description="x",
        )

        merge_duplicate_scripts(Script, ScriptChange)

        change.refresh_from_db()
        assert change.script_id == keeper.pk

    def test_distinct_scripts_untouched(self, website):
        _make_script(website, "https://cdn.x.com/a.js")
        _make_script(website, "https://cdn.x.com/b.js")

        assert merge_duplicate_scripts(Script, ScriptChange) == 0
        assert Script.objects.filter(website=website).count() == 2

    def test_backfills_normalized_url(self, website):
        Script.objects.create(website=website, src_url="https://cdn.x.com/a.js?ver=9")
        merge_duplicate_scripts(Script, ScriptChange)
        s = Script.objects.get(website=website)
        assert s.normalized_url == "https://cdn.x.com/a.js"
