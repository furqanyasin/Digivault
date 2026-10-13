import pytest

from apps.websites.wp_sso_snippet import SNIPPET_VERSION, build_wp_sso_snippet

SECRET = "s" * 32


def build():
    return build_wp_sso_snippet(
        SECRET,
        site_id="site_abc",
        ingest_url="https://digivault.example/api/wp-activity/",
    )


def test_declares_its_version():
    assert "define( 'DVC_VERSION', 2 )" in build()
    assert SNIPPET_VERSION == 2


def test_bails_when_a_newer_snippet_is_already_loaded():
    php = build()
    # Highest version wins: a client who ADDS v2 beside v1 rather than replacing
    # it must not end up running v1's function bodies under v2's routes.
    assert "defined( 'DVC_VERSION' )" in php
    assert "DVC_VERSION >= 2" in php


def test_every_symbol_is_version_suffixed():
    php = build()
    assert "dvc_verify_token" not in php
    assert "dvc2_verify_token" in php


def test_no_placeholders_survive():
    php = build()
    assert "__DVC_" not in php


def test_secret_site_id_and_url_are_baked_in():
    php = build()
    assert SECRET in php
    assert "site_abc" in php
    assert "https://digivault.example/api/wp-activity/" in php


def test_buffer_table_is_capped():
    assert "10000" in build()


def test_details_are_sliced():
    assert "1024" in build()


def test_empty_secret_returns_nothing():
    assert build_wp_sso_snippet("", site_id="x", ingest_url="y") == ""


def test_rendered_snippet_is_valid_php(tmp_path):
    """Lint the real output with php -l.

    The other tests here assert on substrings, which cannot catch an unbalanced
    brace or a bad heredoc — and the snippet is assembled by string splicing
    into a Python template, which is exactly where that kind of damage happens.
    Skipped where no PHP binary exists (CI images without it still get the rest).
    """
    import shutil
    import subprocess

    php = shutil.which("php")
    if php is None:
        pytest.skip("no php binary available")

    target = tmp_path / "snippet.php"
    target.write_text(build(), encoding="utf-8")
    result = subprocess.run(
        [php, "-l", str(target)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_heartbeat_runs_from_cron_never_inside_a_visitors_request():
    php = build()
    # The loopback is a blocking 10s request: on `shutdown` it would sit inside
    # whichever visitor's page load happened to trigger the flush.
    assert "add_action( 'dvc2_cron_flush', 'dvc2_cron_tick' );" in php
    assert "add_action( 'shutdown', 'dvc2_flush', 999 );" in php
    assert "home_url( '/' )" in php
    # A heartbeat alone is worth a POST; an idle flush is not.
    assert "&& null === $heartbeat ) { return; }" in php
