from apps.scripts.normalize import normalize_script_url
from apps.scripts.diff_engine import DiffEngine


def test_youtube_widget_bundle_release_paths_share_one_identity():
    assert normalize_script_url(
        "https://www.youtube.com/s/player/9470c977/www-widgetapi.vflset/www-widgetapi.js"
    ) == "https://www.youtube.com/www-widgetapi.js"
    assert normalize_script_url(
        "https://s.ytimg.com/yts/jsbin/www-widgetapi.js"
    ) == "https://www.youtube.com/www-widgetapi.js"


def test_youtube_iframe_api_remains_distinct_from_widget_bundle():
    assert normalize_script_url(
        "https://www.youtube.com/iframe_api"
    ) != normalize_script_url(
        "https://www.youtube.com/s/player/9470c977/www-widgetapi.vflset/www-widgetapi.js"
    )


def test_youtube_bundle_release_change_is_not_add_remove_churn():
    before = [{"src": "https://www.youtube.com/s/player/old/www-widgetapi.vflset/www-widgetapi.js"}]
    after = [{"src": "https://www.youtube.com/s/player/new/www-widgetapi.vflset/www-widgetapi.js"}]
    assert DiffEngine.diff(before, after) == []