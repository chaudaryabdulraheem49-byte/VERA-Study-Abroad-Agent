"""Rate limiting and checkpointing for the embedding backfill.

The free tier allows 1,000 embeddings a day and bills per *text*, not per
call, so a large index is filled over several days. That makes two things
load-bearing: the run must stay inside the allowance by arithmetic rather than
by being refused, and it must know on restart exactly what it already did.

All offline - nothing here embeds anything.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import tempfile

from backfill_embeddings import Checkpoint, Pacer, utc_today


def embedding_cache_tmp() -> str:
    """A throwaway directory per call, so no test sees another's log."""
    return tempfile.mkdtemp()


# --------------------------------------------------------------------------- #
# Pacing
# --------------------------------------------------------------------------- #


def test_pacing_is_charged_per_text_not_per_call() -> None:
    """The live bug. The ceiling is 100 texts/minute, but the pacer counted
    calls - so 55 calls/min carrying 64 texts each was really asking for
    ~3,500/min and every request came back refused."""
    pacer = Pacer(60)  # one text per second
    start = asyncio.get_event_loop_policy().new_event_loop()
    try:
        start.run_until_complete(pacer.wait(10))
        # The first call never sleeps; what matters is that it has reserved
        # ten seconds of budget, not one.
        assert pacer._next > 0
        reserved = pacer._next
        start.run_until_complete(pacer.wait(1))
        assert pacer._next == pytest.approx(reserved + 1.0, abs=0.01)
    finally:
        start.close()


def test_a_bigger_batch_reserves_proportionally_more() -> None:
    small, large = Pacer(60), Pacer(60)
    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        loop.run_until_complete(small.wait(1))
        loop.run_until_complete(large.wait(50))
        assert large._next > small._next
    finally:
        loop.close()


# --------------------------------------------------------------------------- #
# Checkpoint
# --------------------------------------------------------------------------- #


def checkpoint(tmp_path: Path) -> Checkpoint:
    return Checkpoint(tmp_path / "checkpoint.json")


def test_a_missing_checkpoint_is_not_an_error(tmp_path: Path) -> None:
    assert checkpoint(tmp_path).load() == set()


def test_progress_survives_a_restart(tmp_path: Path) -> None:
    first = checkpoint(tmp_path)
    first.record(["a", "b"], total=10, spent=2)

    second = checkpoint(tmp_path)
    assert second.load() == {"a", "b"}
    assert second.spent_today() == 2


def test_spend_accumulates_across_runs_on_the_same_day(tmp_path: Path) -> None:
    """Without this every run believes it has a fresh 1,000 and rediscovers
    the ceiling by being refused."""
    first = checkpoint(tmp_path)
    first.record(["a"], total=10, spent=400)
    first.record(["b"], total=10, spent=300)

    second = checkpoint(tmp_path)
    second.load()
    assert second.spent_today() == 700


def test_the_ledger_is_kept_per_day(tmp_path: Path) -> None:
    point = checkpoint(tmp_path)
    point.record(["a"], total=10, spent=500)
    point.spent["1999-01-01"] = 900  # yesterday's spend must not count
    assert point.spent_today() == 500


def test_a_checkpoint_from_another_model_is_not_reused(tmp_path: Path) -> None:
    """Vectors from two models occupy different spaces. Resuming across a
    model change would leave half the index scored on one geometry and half on
    another, with nothing to show for it but bad matches."""
    point = checkpoint(tmp_path)
    point.record(["a", "b"], total=10, spent=2)

    saved = json.loads(point.path.read_text(encoding="utf-8"))
    saved["model"] = "some-other-embedding-model"
    point.path.write_text(json.dumps(saved), encoding="utf-8")

    assert checkpoint(tmp_path).load() == set()


def test_the_spend_ledger_survives_a_model_change(tmp_path: Path) -> None:
    """The allowance was consumed whatever it was spent on, so forgetting it
    would immediately overspend the day."""
    point = checkpoint(tmp_path)
    point.record(["a"], total=10, spent=600)

    saved = json.loads(point.path.read_text(encoding="utf-8"))
    saved["model"] = "some-other-embedding-model"
    point.path.write_text(json.dumps(saved), encoding="utf-8")

    fresh = checkpoint(tmp_path)
    fresh.load()
    assert fresh.spent_today() == 600


def test_a_truncated_checkpoint_is_ignored_rather_than_fatal(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    path.write_text('{"model": "gemini', encoding="utf-8")
    assert Checkpoint(path).load() == set()


def test_writing_is_atomic(tmp_path: Path) -> None:
    """Written to a sibling then moved, so a run killed mid-write cannot leave
    truncated JSON for the next one to discard."""
    point = checkpoint(tmp_path)
    point.record(["a"], total=10, spent=1)
    assert json.loads(point.path.read_text(encoding="utf-8"))["completed"] == ["a"]
    assert not point.path.with_suffix(".tmp").exists()


def test_the_record_names_what_it_was_written_under(tmp_path: Path) -> None:
    point = checkpoint(tmp_path)
    point.record(["a"], total=10, spent=1)
    saved = json.loads(point.path.read_text(encoding="utf-8"))
    assert {"model", "dimensions", "collection"} <= set(saved)
    assert saved["total_courses"] == 10
    assert utc_today() in saved["spent"]


# --------------------------------------------------------------------------- #
# Per-day log
#
# `completed` answers "is this done", which is all the resume logic needs.
# It cannot answer "what did today's run add" - the question asked after every
# run - because it is one merged set.
# --------------------------------------------------------------------------- #


def test_todays_work_is_logged_against_todays_date() -> None:
    point = checkpoint(tmp := Path(embedding_cache_tmp()))
    point.record(["a", "b"], total=10, spent=2)
    assert sorted(point.embedded_on()) == ["a", "b"]
    assert point.embedded_on(utc_today()) == point.embedded_on()


def test_the_per_day_log_survives_a_restart() -> None:
    directory = Path(embedding_cache_tmp())
    first = checkpoint(directory)
    first.record(["a"], total=10, spent=1)

    second = checkpoint(directory)
    second.load()
    assert second.embedded_on() == ["a"]


def test_a_rerun_does_not_inflate_the_tally() -> None:
    """A re-run covers ground already done; counting it again would make the
    log say more arrived than actually did."""
    point = checkpoint(Path(embedding_cache_tmp()))
    point.record(["a", "b"], total=10, spent=2)
    point.record(["a", "b", "c"], total=10, spent=1)
    assert sorted(point.embedded_on()) == ["a", "b", "c"]


def test_another_day_is_kept_separate() -> None:
    point = checkpoint(Path(embedding_cache_tmp()))
    point.record(["a"], total=10, spent=1)
    point.by_date["1999-01-01"] = ["old"]
    assert point.embedded_on("1999-01-01") == ["old"]
    assert "old" not in point.embedded_on()


def test_a_checkpoint_written_before_this_existed_logs_nothing() -> None:
    """Those days genuinely cannot be reconstructed, and inventing a split
    would be worse than admitting the gap."""
    directory = Path(embedding_cache_tmp())
    point = checkpoint(directory)
    point.record(["a"], total=10, spent=1)

    saved = json.loads(point.path.read_text(encoding="utf-8"))
    del saved["embedded_by_date"]
    point.path.write_text(json.dumps(saved), encoding="utf-8")

    fresh = checkpoint(directory)
    fresh.load()
    assert fresh.embedded_on() == []
    assert fresh.spent_today() == 1  # the ledger still knows it happened
