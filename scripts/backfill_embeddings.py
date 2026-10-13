"""Give every Postgres course a Qdrant vector.

A bulk import writes rows straight to Postgres, which makes them *eligible*
but not *findable*: the hybrid search filters in SQL and then ranks in Qdrant,
so a course with no point is dropped at the ranking step and never reaches a
student. After the CRICOS import that left 9,845 courses in the database and
12 in the vector store.

    python scripts/backfill_embeddings.py --dry-run
    python scripts/backfill_embeddings.py

Resumable by construction: it asks Qdrant which ids it already holds and
embeds only the difference. A run stopped by a quota limit, a network drop or
Ctrl-C loses nothing, because every batch is committed before the next is
requested - so re-running simply continues.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final

from qdrant_client import models
from sqlalchemy import select

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.services.phase2.db import (  # noqa: E402
    Course,
    dispose_engine,
    session_scope,
)
from app.services.phase2.embeddings import EmbeddingError, embed_texts  # noqa: E402
from app.services.phase2.ingestion_service import (  # noqa: E402
    close_qdrant_client,
    ensure_collection,
    get_qdrant_client,
)

logger = logging.getLogger("backfill")

# Rows per round trip. Within the 50-100 band, and matched closely enough to
# the embedding client's own chunk size that one batch here is one HTTP call.
BATCH: Final = 50

# The free tier's two ceilings, and the one fact that governs both: it bills
# per *text*, not per call. Sending 64 texts in a single request spends 64 of
# the allowance, which is why batching does nothing to stretch it and why an
# earlier run pacing 55 *batches* a minute was really asking for ~3,500 texts a
# minute against a 100 ceiling.
#
# So both limits are counted in texts, and the pacer sleeps in proportion to
# batch size rather than per call.
TEXTS_PER_MINUTE: Final = 80  # ceiling is 100; leave headroom for clock skew

# The tier allows 1,000 a day, but the backfill must not take all of it.
# Every chat search embeds the student's query, so an allowance spent entirely
# on backfilling does not merely pause the backfill - it takes search offline
# for everyone until UTC midnight. That happened; this is the fix.
TEXTS_PER_DAY: Final = 900
LIVE_QUERY_RESERVE: Final = 100


class Pacer:
    """Hold throughput to a fixed rate, sleeping only when actually ahead."""

    def __init__(self, per_minute: int) -> None:
        self._interval = 60.0 / max(per_minute, 1)
        self._next = 0.0

    async def wait(self, items: int = 1) -> None:
        now = time.monotonic()
        if now < self._next:
            await asyncio.sleep(self._next - now)
        self._next = max(now, self._next) + self._interval * items


class DailyQuotaReached(RuntimeError):
    """The per-day allowance is gone; only tomorrow fixes it."""


def utc_today() -> str:
    """The date the daily allowance is reckoned against (Google resets in UTC)."""
    return datetime.now(timezone.utc).date().isoformat()


def seconds_until_utc_midnight() -> float:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (tomorrow - now).total_seconds()


def embedding_text(course: Course) -> str:
    """Mirror `CourseExtractionSchema.embedding_text` for an ORM row.

    The two must stay identical. If a backfilled vector were built from
    different text than an ingested one, the same course would score
    differently depending on how it entered the index - and nothing would
    report the discrepancy.
    """
    return (
        f"{course.course_title} ({course.degree_level}) at "
        f"{course.university_name}, {course.country}.\n{course.syllabus_description}"
    )


async def existing_ids(client) -> set[str]:
    """Every course id Qdrant already holds.

    Scrolled rather than queried: this is a full enumeration of the collection,
    and asking for it up front turns "which rows need work" into set
    arithmetic instead of one lookup per row.
    """
    collection = get_settings().qdrant_collection
    found: set[str] = set()
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=collection,
            limit=1_000,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        found.update(str(point.id) for point in points)
        if offset is None:
            break
    return found


class Checkpoint:
    """Progress written to disk after every batch.

    Qdrant remains the source of truth - it is what the search actually reads,
    so a course is done when a point exists, not when a file says so. This
    file is the faster answer to the same question: reading it costs nothing,
    while enumerating the collection costs a full scroll.

    It records the model, collection and width it was written under, and is
    ignored if any of them changed. Vectors from two different models occupy
    different spaces, so resuming across a model change would leave the index
    quietly incoherent - half the courses scored on one geometry and half on
    another, with nothing to show for it but bad matches.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        settings = get_settings()
        self._stamp = {
            "model": settings.embedding_model,
            "dimensions": settings.embedding_dimensions,
            "collection": settings.qdrant_collection,
        }
        self.completed: set[str] = set()
        # texts spent per UTC date, so a second run on the same day knows how
        # much of the daily allowance the first one already used. Without this
        # every run starts believing it has a fresh 1,000 and rediscovers the
        # ceiling by being refused.
        self.spent: dict[str, int] = {}
        # Which courses were embedded on which UTC date. `completed` answers
        # "is this done" and is all the resume logic needs; this answers "what
        # did today's run actually add", which is the question asked after
        # every run and which a single merged set cannot answer.
        self.by_date: dict[str, list[str]] = {}

    def spent_today(self) -> int:
        return self.spent.get(utc_today(), 0)

    def embedded_on(self, date: str | None = None) -> list[str]:
        """Course ids embedded on a given UTC date (default: today)."""
        return list(self.by_date.get(date or utc_today(), []))

    def load(self) -> set[str]:
        if not self.path.is_file():
            return set()
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Ignoring unreadable checkpoint %s: %s", self.path, exc)
            return set()

        self.spent = {k: int(v) for k, v in (saved.get("spent") or {}).items()}

        if {k: saved.get(k) for k in self._stamp} != self._stamp:
            logger.warning(
                "Checkpoint was written for a different model or collection; "
                "ignoring its course list and asking Qdrant instead."
            )
            return set()

        self.completed = set(saved.get("completed", []))
        # The spend ledger survives a model change even when the id set does
        # not: the allowance was still consumed, whatever it was spent on.
        self.spent = {k: int(v) for k, v in (saved.get("spent") or {}).items()}
        # Absent from checkpoints written before this existed. An empty log is
        # correct there - those days genuinely cannot be reconstructed, and
        # inventing a split would be worse than admitting the gap.
        self.by_date = {
            k: list(v) for k, v in (saved.get("embedded_by_date") or {}).items()
        }
        return self.completed

    def record(self, ids: list[str], *, total: int, spent: int = 0) -> None:
        # Only genuinely new ids are logged for the day. A re-run that covers
        # ground already done must not inflate today's tally.
        fresh = [i for i in ids if i not in self.completed]
        if fresh:
            self.by_date.setdefault(utc_today(), []).extend(fresh)
        self.completed.update(ids)
        if spent:
            self.spent[utc_today()] = self.spent.get(utc_today(), 0) + spent
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **self._stamp,
            "total_courses": total,
            "completed_count": len(self.completed),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "spent": self.spent,
            "embedded_by_date": self.by_date,
            "completed": sorted(self.completed),
        }
        # Written to a sibling then moved: a run killed mid-write would
        # otherwise leave truncated JSON, and the next run would discard the
        # whole record over it.
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(self.path)


async def pending_courses(
    client,
    checkpoint: Checkpoint | None = None,
    *,
    match: str | None = None,
    level: str | None = None,
    country: str | None = None,
) -> list[Course]:
    """Courses with no vector yet, optionally narrowed to a subset.

    The narrowing exists because the free tier allows 1,000 embeddings a day
    and counts each text, so a large index is filled over several days. Which
    thousand goes first is then a real decision: the courses students are
    actually asking for should not wait behind an alphabetical accident.
    """
    done = await existing_ids(client)
    if checkpoint is not None:
        done |= checkpoint.load()
    async with session_scope() as session:
        query = select(Course)
        if match:
            query = query.where(Course.course_title.ilike(f"%{match}%"))
        if level:
            query = query.where(Course.degree_level == level)
        if country:
            query = query.where(Course.country == country)
        rows = (await session.execute(query)).scalars().all()
        # Detached from the session deliberately: the loop below runs long
        # network calls, and holding a transaction open across them would pin a
        # connection for the whole run.
        return [
            Course(
                course_id=row.course_id,
                course_title=row.course_title,
                university_name=row.university_name,
                country=row.country,
                degree_level=row.degree_level,
                syllabus_description=row.syllabus_description,
                tuition_fee_amount=row.tuition_fee_amount,
                currency=row.currency,
                tuition_fee_usd=row.tuition_fee_usd,
            )
            for row in rows
            if str(row.course_id) not in done
        ]


async def backfill(
    courses: list[Course],
    *,
    batch_size: int,
    per_minute: int,
    checkpoint: Checkpoint,
    daily_budget: int,
) -> tuple[int, int]:
    """Embed and store in batches. Returns (written, failed)."""
    client = get_qdrant_client()
    await ensure_collection(client)
    collection = get_settings().qdrant_collection
    pacer = Pacer(per_minute)

    written = 0
    failed = 0
    started = time.monotonic()
    total = len(courses)

    for start in range(0, total, batch_size):
        # Stay inside the day's allowance by arithmetic rather than by being
        # refused. A request that comes back 429 has still cost a round trip,
        # a backoff and - on some tiers - a slice of the very quota it was
        # denied for, so counting is strictly cheaper than discovering.
        remaining_today = daily_budget - checkpoint.spent_today()
        if remaining_today <= 0:
            raise DailyQuotaReached(
                f"{daily_budget:,} text(s) already embedded today"
            )

        batch = courses[start : start + min(batch_size, remaining_today)]
        await pacer.wait(len(batch))
        try:
            vectors = await embed_texts([embedding_text(c) for c in batch])
        except EmbeddingError as exc:
            # The ledger only counts what we chose to spend; a refusal means
            # the real remaining budget is smaller than we believed, so it is
            # written off here and the run ends rather than probing for the
            # true figure one refused request at a time.
            if "PerDay" in str(exc) or "limit: 1000" in str(exc):
                checkpoint.record([], total=total, spent=remaining_today)
                raise DailyQuotaReached(str(exc)) from exc
            # Anything else is local to this batch: the rest of the index is
            # still worth building, and a re-run picks these up again.
            failed += len(batch)
            logger.error(
                "Batch at row %d failed (%d course(s) skipped): %s",
                start,
                len(batch),
                str(exc)[:200],
            )
            continue

        await client.upsert(
            collection_name=collection,
            points=[
                models.PointStruct(
                    id=str(course.course_id),
                    vector=vector,
                    payload={
                        "course_id": str(course.course_id),
                        "university_name": course.university_name,
                        "country": course.country,
                    },
                )
                for course, vector in zip(batch, vectors, strict=True)
            ],
            wait=True,
        )
        written += len(batch)
        # Only after the upsert has been acknowledged: a checkpoint written
        # before the write lands would skip courses that were never stored.
        checkpoint.record(
            [str(c.course_id) for c in batch], total=total, spent=len(batch)
        )

        elapsed = time.monotonic() - started
        rate = written / elapsed if elapsed else 0
        remaining = (total - written - failed) / rate if rate else 0
        done = written + failed
        bar = "#" * int(24 * done / total) if total else ""
        print(
            f"  batch {start // batch_size + 1:>3}/{-(-total // batch_size):<3} "
            f"[{bar:<24}] {done:>6,}/{total:,} "
            f"{100 * done / total:5.1f}%  {rate:5.1f}/s  "
            f"~{remaining / 60:4.1f} min left",
            flush=True,
        )

    return written, failed


async def run(args: argparse.Namespace) -> int:
    client = get_qdrant_client()
    await ensure_collection(client)

    checkpoint = Checkpoint(Path(args.checkpoint))
    courses = await pending_courses(
        client, checkpoint, match=args.match, level=args.level, country=args.country
    )
    held = len(await existing_ids(client))

    async with session_scope() as session:
        total = len((await session.execute(select(Course.course_id))).scalars().all())

    settings = get_settings()
    print(f"Model                 {settings.embedding_model} "
          f"({settings.embedding_dimensions}d)")
    print(f"Collection            {settings.qdrant_collection}")
    print(f"Checkpoint            {checkpoint.path}")
    print(f"Courses in Postgres   {total:>7,}")
    print(f"Vectors already held  {held:>7,}")
    narrowed = [f for f in (args.match, args.level, args.country) if f]
    if narrowed:
        print(f"Narrowed to           {', '.join(narrowed)}")
    print(f"To embed              {len(courses):>7,}")
    spent = checkpoint.spent_today()
    left_today = max(args.daily_limit - spent, 0)
    print(
        f"Free-tier budget      {left_today:>7,} of {args.daily_limit:,} "
        f"text(s) left today (UTC)"
    )

    if args.report is not None:
        # The question asked after every run. Reading it from the per-day log
        # rather than from Qdrant, because Qdrant knows what exists, not when
        # it arrived.
        day = args.report or utc_today()
        ids = set(checkpoint.embedded_on(day))
        print()
        if not ids:
            known = ", ".join(sorted(checkpoint.by_date)) or "none recorded yet"
            print(f"Nothing logged for {day}. Days with a per-day log: {known}.")
            return 0

        async with session_scope() as session:
            rows = (await session.execute(select(Course))).scalars().all()
        landed = sorted(
            (r for r in rows if str(r.course_id) in ids),
            key=lambda r: (r.degree_level, r.university_name, r.course_title),
        )
        print(f"{len(landed):,} course(s) embedded on {day} (UTC):")
        print()
        print(f"{'Course':<52} {'University':<34} Level")
        print("-" * 98)
        for row in landed:
            print(
                f"{row.course_title[:52]:<52} {row.university_name[:34]:<34} "
                f"{row.degree_level}"
            )
        return 0

    if args.status:
        # Read-only by design. It reports and exits without reaching the
        # branches below, so asking for the state can never start spending
        # the allowance.
        days = -(-len(courses) // max(args.daily_limit, 1))
        print()
        if not courses:
            print("Index coverage: complete - every course has a vector.")
        else:
            print(
                f"Index coverage: {total - len(courses):,}/{total:,} "
                f"({100 * (total - len(courses)) / total:.1f}%)."
            )
            print(
                f"{len(courses):,} course(s) awaiting a vector - about {days} "
                "daily run(s) at the free-tier rate."
            )

        if checkpoint.by_date:
            print()
            print("Embedded per day (UTC):")
            for day in sorted(checkpoint.by_date)[-10:]:
                spent = checkpoint.spent.get(day)
                cost = f"  ({spent:,} of the allowance)" if spent else ""
                print(f"  {day}  {len(checkpoint.by_date[day]):>5,} course(s){cost}")
        elif checkpoint.spent:
            # The ledger goes back further than the per-day log, and saying so
            # is better than implying nothing was done on those days.
            print()
            print(
                "Per-day detail starts from the first run after this was added; "
                "earlier days show in the spend ledger only: "
                + ", ".join(f"{d} ({n:,})" for d, n in sorted(checkpoint.spent.items()))
            )
        return 0

    if not courses:
        print("\nNothing to do - every course already has a vector.")
        return 0

    if left_today <= 0 and not args.dry_run:
        hours = seconds_until_utc_midnight() / 3600
        print(
            f"\nToday's free-tier allowance is spent. It resets in "
            f"{hours:.1f} hour(s); re-run then and it will continue from here."
        )
        return 0

    if args.dry_run:
        print("\nDry run - no API calls made. Sample of what would be embedded:")
        for course in courses[:3]:
            print(f"\n  {course.course_title} ({course.university_name})")
            print(f"    {embedding_text(course)[:160]}...")
        print(
            f"\nThis would make roughly {-(-len(courses) // 64):,} embedding "
            "request(s). Drop --dry-run to run it."
        )
        return 0

    print(f"\nEmbedding {args.batch} at a time, up to {args.rpm} request(s)/min...")
    stopped_early = False
    try:
        written, failed = await backfill(
            courses,
            batch_size=args.batch,
            per_minute=args.rpm,
            checkpoint=checkpoint,
            daily_budget=args.daily_limit,
        )
    except DailyQuotaReached as exc:
        stopped_early = True
        written, failed = 0, 0
        hours = seconds_until_utc_midnight() / 3600
        print(f"\nStopped: daily free-tier allowance reached ({str(exc)[:110]})")
        print(f"It resets in {hours:.1f} hour(s). Re-run then to continue.")

    final = len(await existing_ids(client))
    print(f"\nEmbedded {final - held:,} course(s) this run.")
    if failed:
        print(f"{failed:,} failed - re-run to retry just those.", file=sys.stderr)
    print(f"Vectors now in Qdrant: {final:,} of {total:,} course(s).")
    if final < total:
        days = -(-(total - final) // max(args.daily_limit, 1))
        print(
            f"{total - final:,} still to go - about {days} more daily run(s) "
            "at the free-tier rate. Nothing already done is repeated."
        )
    return 0 if final > held or not stopped_early else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=BATCH)
    parser.add_argument(
        "--match", default=None, help="only courses whose title contains this"
    )
    parser.add_argument("--level", default=None, help="Bachelors | Masters | PhD")
    parser.add_argument("--country", default=None)
    parser.add_argument(
        "--checkpoint",
        default=str(REPO_ROOT / "data" / "embedding_checkpoint.json"),
        help="progress file, written after every batch",
    )
    parser.add_argument(
        "--rpm",
        type=int,
        default=TEXTS_PER_MINUTE,
        help="texts per minute; the free tier ceiling is 100",
    )
    parser.add_argument(
        "--daily-limit",
        type=int,
        default=TEXTS_PER_DAY,
        help="texts per UTC day; the free tier allows 1000",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--status",
        action="store_true",
        help="report coverage and today's remaining budget, then exit",
    )
    parser.add_argument(
        "--report",
        nargs="?",
        const="",
        default=None,
        metavar="YYYY-MM-DD",
        help="list the courses embedded on a UTC date (default: today)",
    )
    return parser


async def _dispatch(args: argparse.Namespace) -> int:
    try:
        return await run(args)
    finally:
        await dispose_engine()
        await close_qdrant_client()


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args = build_parser().parse_args()
    try:
        return asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        print("\nInterrupted - progress is saved, re-run to continue.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
