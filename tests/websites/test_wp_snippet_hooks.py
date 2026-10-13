import pytest

from apps.websites.wp_sso_snippet import build_wp_sso_snippet

SECRET = "s" * 32


@pytest.fixture
def php():
    return build_wp_sso_snippet(
        SECRET, site_id="s1", ingest_url="https://x.test/api/wp-activity/"
    )


@pytest.mark.parametrize("hook", [
    "wp_login", "wp_login_failed", "user_register", "profile_update",
    "set_user_role", "delete_user", "password_reset",
    "activated_plugin", "deactivated_plugin", "upgrader_process_complete",
    "switch_theme", "deleted_plugin", "deleted_theme",
    # `wp_trash_post` is deliberately not in this list. Trashing is already
    # captured by `transition_post_status`, which records `post_trashed` when
    # the new status is `trash`; registering the dedicated hook as well would
    # log every trash twice. It would also cost a re-paste of the snippet on
    # every client site, which is the entire cost centre of this feature.
    "transition_post_status", "before_delete_post",
    "woocommerce_order_status_changed", "woocommerce_update_product",
    "woocommerce_order_refunded",
])
def test_hook_is_registered(php, hook):
    assert f"'{hook}'" in php


def test_flush_runs_on_shutdown_and_on_cron(php):
    assert "add_action( 'shutdown'" in php
    assert "wp_schedule_event" in php
    assert "dvc2_cron_flush" in php


def test_flush_signs_the_body_not_the_url(php):
    # The signature must cover the payload; a URL-only signature would let a
    # captured request be replayed with a different body.
    assert "hash_hmac( 'sha256', $ts . '.' . $body, DVC2_SECRET )" in php


def test_flush_sends_the_three_auth_headers(php):
    assert "X-StacksMonitor-Site" in php
    assert "X-StacksMonitor-Timestamp" in php
    assert "X-StacksMonitor-Signature" in php


def test_flush_records_the_ack_timestamp(php):
    assert "dvc2_last_ack" in php


def test_flush_honours_a_resend_request(php):
    assert "resend_from" in php


def test_acked_rows_are_deleted_not_just_marked(php):
    assert "DELETE FROM" in php
