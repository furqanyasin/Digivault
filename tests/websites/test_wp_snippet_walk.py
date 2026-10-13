import pytest

from apps.websites.wp_sso_snippet import build_wp_sso_snippet


@pytest.fixture
def php():
    return build_wp_sso_snippet(
        "s" * 32, site_id="s1", ingest_url="https://x.test/api/wp-activity/"
    )


def test_walk_is_scheduled_daily(php):
    assert "dvc2_cron_walk" in php
    assert "'daily'" in php


def test_walk_covers_the_three_wp_content_roots(php):
    assert "WP_CONTENT_DIR . '/plugins'" in php
    assert "WP_CONTENT_DIR . '/themes'" in php
    assert "WP_CONTENT_DIR . '/mu-plugins'" in php


def test_walk_is_chunked_with_a_cursor(php):
    # A 50k-file site cannot be walked in one cron tick without timing out.
    assert "dvc2_walk_cursor" in php
    assert "dvc2_walk_id" in php


def test_walk_marks_completion_explicitly(php):
    # Digivault must not diff a partial manifest: every unwalked file would read
    # as removed.
    assert "'complete'" in php


def test_walk_only_hashes_code_extensions(php):
    # Asserting on the literal list, not on the substring "php" — the whole
    # template is PHP, so a substring check here would pass no matter what.
    assert "array( 'php', 'js', 'htaccess' )" in php


def test_walk_skips_files_over_the_size_cap(php):
    assert "DVC2_MAX_FILE_BYTES" in php
    assert "2097152" in php
