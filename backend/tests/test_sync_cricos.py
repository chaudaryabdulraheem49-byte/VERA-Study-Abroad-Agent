"""Deciding whether the published CRICOS release is newer than ours.

The whole point of the sync is to *not* download 1.5 MB and re-ingest 26,000
rows when nothing has changed. Getting that decision wrong is silent in both
directions: too eager and every run redoes the work, too lax and the index
quietly serves a superseded register.

Offline - the CKAN response is supplied rather than fetched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sync_cricos import is_current, read_state, sha256, write_state


def resource(**overrides: object) -> dict[str, object]:
    record = {
        "id": "eb3e505b-8fce-47c1-a19b-2d24fc234b35",
        "last_modified": "2026-08-31T23:30:40.019425",
        "size": 1488630,
        "url": "https://data.gov.au/.../cricos.zip",
    }
    record.update(overrides)
    return record


def state_for(record: dict[str, object], **overrides: object) -> dict[str, object]:
    saved = {
        "resource_id": record["id"],
        "last_modified": record["last_modified"],
        "size": record["size"],
        "sha256": "abc123",
    }
    saved.update(overrides)
    return saved


# --------------------------------------------------------------------------- #
# Change detection
# --------------------------------------------------------------------------- #


def test_an_unchanged_release_is_recognised() -> None:
    record = resource()
    assert is_current(record, state_for(record)) is True


def test_no_state_means_not_current() -> None:
    """A first run has nothing to compare against and must not assume it is
    up to date."""
    assert is_current(resource(), {}) is False


def test_a_newer_timestamp_is_a_change() -> None:
    record = resource()
    stale = state_for(record, last_modified="2026-07-01T00:00:00")
    assert is_current(record, stale) is False


def test_a_reupload_that_kept_the_timestamp_is_still_a_change() -> None:
    """Publishers do replace a file without moving its date, which is why size
    is compared as well as the timestamp."""
    record = resource()
    stale = state_for(record, size=999)
    assert is_current(record, stale) is False


def test_a_new_resource_id_is_a_change() -> None:
    """Republishing can mint a new id for the same logical file; treating that
    as unchanged would pin us to the superseded release forever."""
    record = resource()
    stale = state_for(record, resource_id="00000000-0000-0000-0000-000000000000")
    assert is_current(record, stale) is False


def test_comparison_survives_a_number_stored_as_text() -> None:
    """JSON round-trips make `size` a string often enough that comparing types
    rather than values would report a change on every run."""
    record = resource()
    assert is_current(record, state_for(record, size="1488630")) is True


# --------------------------------------------------------------------------- #
# State file
# --------------------------------------------------------------------------- #


def test_state_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    write_state(path, {"resource_id": "x", "size": 1})
    assert read_state(path) == {"resource_id": "x", "size": 1}


def test_a_missing_state_file_is_not_an_error(tmp_path: Path) -> None:
    assert read_state(tmp_path / "absent.json") == {}


def test_a_truncated_state_file_is_ignored_rather_than_fatal(tmp_path: Path) -> None:
    """A run killed mid-write must not make every later run fail; the worst
    outcome of ignoring it is one redundant sync."""
    path = tmp_path / "state.json"
    path.write_text('{"resource_id": "x"', encoding="utf-8")
    assert read_state(path) == {}


def test_state_is_written_atomically(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    write_state(path, {"resource_id": "x"})
    assert json.loads(path.read_text(encoding="utf-8"))["resource_id"] == "x"
    assert not path.with_suffix(".tmp").exists()


# --------------------------------------------------------------------------- #
# Content hash
# --------------------------------------------------------------------------- #


def test_hashing_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    """The hash is the only comparison that cannot be wrong, and it is what
    lets a re-published but byte-identical release skip the ingest."""
    first = tmp_path / "a.zip"
    second = tmp_path / "b.zip"
    first.write_bytes(b"payload")
    second.write_bytes(b"payload")
    assert sha256(first) == sha256(second)

    second.write_bytes(b"payload!")
    assert sha256(first) != sha256(second)


def test_hashing_reads_a_file_larger_than_one_block(tmp_path: Path) -> None:
    """Read in 1 MiB blocks so a 1.5 MB archive is not loaded whole; the loop
    is where an off-by-one would hide."""
    import hashlib

    payload = bytes(range(256)) * 8192  # 2 MiB
    path = tmp_path / "big.zip"
    path.write_bytes(payload)
    assert sha256(path) == hashlib.sha256(payload).hexdigest()
