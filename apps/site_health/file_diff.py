"""Comparing two wp-content file manifests.

Pure functions, no DB and no model imports, so they can be tested directly the
way `DiffEngine` and `wp_assets.diff_assets` are.

Two decisions here are about signal rather than correctness:

* **An empty baseline reports nothing.** The first complete walk establishes the
  baseline; reporting every file on the site as added would bury the one that
  matters. Same reasoning as `diff_assets` returning [] for an empty previous.
* **A wholesale directory change collapses to one event.** Deleting a plugin
  removes hundreds of files. One row per file makes the timeline useless on
  exactly the day something big happened.
"""
from __future__ import annotations

import posixpath

# Above this many changes in one directory, report the directory instead.
_COLLAPSE_THRESHOLD = 10

# Extensions the web server will execute. A new one of these somewhere content
# is uploaded is the classic WordPress backdoor.
_EXECUTABLE_SUFFIXES = (".php", ".phtml", ".php5", ".php7", ".phar")

# Directories that exist to hold user content, never code.
_CONTENT_DIRS = ("uploads/", "upgrade/", "cache/")


def is_sensitive_path(path: str) -> bool:
    """True if this path changing is suspicious on its own merits.

    Deliberately narrow. Every plugin update changes PHP under plugins/ — that
    is not a finding. Executable code appearing under uploads/ is.
    """
    normalised = (path or "").replace("\\", "/").lstrip("/").lower()
    if not normalised:
        return False
    in_content_dir = any(normalised.startswith(d) for d in _CONTENT_DIRS)
    if not in_content_dir:
        return False
    if normalised.endswith(_EXECUTABLE_SUFFIXES):
        return True
    # .htaccess under uploads can turn the media library into a code directory
    # or redirect traffic wholesale.
    return posixpath.basename(normalised) == ".htaccess"


def _event(change: str, path: str, file_count: int = 1) -> dict:
    return {
        "change": change,
        "path": path,
        "file_count": file_count,
        "sensitive": file_count == 1 and is_sensitive_path(path),
    }


def _collapse(change: str, paths: list[str]) -> list[dict]:
    """Group a change type by top-two-path-segments where the count is large."""
    by_dir: dict[str, list[str]] = {}
    for path in paths:
        parts = (path or "").replace("\\", "/").split("/")
        key = "/".join(parts[:2]) if len(parts) > 2 else posixpath.dirname(path)
        by_dir.setdefault(key, []).append(path)

    events: list[dict] = []
    for directory, members in by_dir.items():
        if len(members) > _COLLAPSE_THRESHOLD:
            events.append(_event(change, directory, len(members)))
        else:
            events.extend(_event(change, p) for p in members)
    return events


def diff_manifests(before: dict[str, str], after: dict[str, str]) -> list[dict]:
    """Describe what changed between two complete path -> md5 maps.

    Returns [] when `before` is empty — see the module docstring. Both inputs
    must come from *complete* walks; diffing a partial manifest would report
    every not-yet-walked file as removed.
    """
    if not before:
        return []

    before_keys, after_keys = set(before), set(after)

    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    modified = sorted(
        path for path in before_keys & after_keys if before[path] != after[path]
    )

    events = (
        _collapse("added", added)
        + _collapse("removed", removed)
        + _collapse("modified", modified)
    )
    # Sorted so a run over the same inputs always produces the same timeline —
    # dict iteration order in _collapse is otherwise insertion-dependent.
    return sorted(events, key=lambda e: (e["change"], e["path"]))
