from apps.site_health.file_diff import diff_manifests, is_sensitive_path

# --- diff_manifests (pure, no DB) -------------------------------------------


def test_no_baseline_reports_nothing():
    """The first complete walk establishes the baseline. Reporting every file on
    the site as added would bury the one that matters, forever."""
    assert diff_manifests({}, {"a.php": "h1", "b.php": "h2"}) == []


def test_unchanged_files_produce_no_events():
    assert diff_manifests({"a.php": "h1"}, {"a.php": "h1"}) == []


def test_modified_file_is_reported():
    events = diff_manifests({"a.php": "h1"}, {"a.php": "h2"})
    assert len(events) == 1
    assert events[0]["change"] == "modified"
    assert events[0]["path"] == "a.php"


def test_added_file_is_reported():
    events = diff_manifests({"a.php": "h1"}, {"a.php": "h1", "b.php": "h2"})
    assert [e["change"] for e in events] == ["added"]
    assert events[0]["path"] == "b.php"


def test_removed_file_is_reported():
    events = diff_manifests({"a.php": "h1", "b.php": "h2"}, {"a.php": "h1"})
    assert [e["change"] for e in events] == ["removed"]
    assert events[0]["path"] == "b.php"


def test_events_are_ordered_deterministically():
    events = diff_manifests({}, {})
    assert events == []
    events = diff_manifests(
        {"z.php": "1", "a.php": "1"}, {"z.php": "2", "a.php": "2"}
    )
    assert [e["path"] for e in events] == ["a.php", "z.php"]


def test_a_whole_plugin_being_deleted_collapses_to_one_event():
    """Deleting a plugin removes hundreds of files. One event per file would
    make the timeline useless on exactly the day something big happened."""
    before = {f"plugins/wp-rocket/f{i}.php": "h" for i in range(50)}
    events = diff_manifests(before, {})
    assert len(events) == 1
    assert events[0]["change"] == "removed"
    assert events[0]["path"] == "plugins/wp-rocket"
    assert events[0]["file_count"] == 50


def test_a_few_changes_in_one_directory_stay_individual():
    before = {f"plugins/wp-rocket/f{i}.php": "h" for i in range(3)}
    events = diff_manifests(before, {})
    assert len(events) == 3


# --- is_sensitive_path -------------------------------------------------------


def test_a_new_php_file_in_uploads_is_sensitive():
    """Nothing legitimate writes executable PHP into the media library. This is
    the single most common shape of a WordPress backdoor."""
    assert is_sensitive_path("uploads/2026/09/shell.php") is True


def test_an_image_in_uploads_is_not_sensitive():
    assert is_sensitive_path("uploads/2026/09/photo.jpg") is False


def test_an_ordinary_plugin_file_is_not_sensitive():
    assert is_sensitive_path("plugins/wp-rocket/inc/Engine.php") is False


def test_an_htaccess_change_is_sensitive():
    assert is_sensitive_path("uploads/.htaccess") is True
