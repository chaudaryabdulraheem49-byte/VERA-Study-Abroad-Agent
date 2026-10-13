"""Keep the CRICOS data current with what data.gov.au publishes.

The register is reissued periodically. `ingest_cricos.py` loads whatever zip
is already on disk; this decides whether that zip is still the current one,
fetches a new release when there is one, and leaves the index consistent
afterwards.

    python scripts/sync_cricos.py --dry-run
    python scripts/sync_cricos.py
    python scripts/sync_cricos.py --force        # re-sync regardless

The only host contacted is data.gov.au, and a run that finds nothing new
downloads nothing: the decision is made from CKAN metadata, which is a few
kilobytes, not from the 1.5 MB archive.

Three things are compared against the last run, because any one of them alone
can miss a change. `last_modified` is what the publisher states, size catches
a re-upload that kept the timestamp, and the SHA-256 of the bytes is the only
one that cannot be wrong - it is checked after download, so a resource that
was re-published with identical content is recognised and the ingest skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

import httpx

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.phase2.db import dispose_engine, init_schema  # noqa: E402
from app.services.phase2.ingestion_service import (  # noqa: E402
    close_qdrant_client,
    ensure_collection,
    get_qdrant_client,
)
from backfill_embeddings import (  # noqa: E402
    BATCH,
    TEXTS_PER_DAY,
    TEXTS_PER_MINUTE,
    Checkpoint,
    DailyQuotaReached,
    backfill,
    pending_courses,
)
from ingest_cricos import (  # noqa: E402
    extract,
    load_courses,
    load_institutions,
    upsert_courses,
    upsert_raw,
    upsert_universities,
)

logger = logging.getLogger("sync_cricos")

CKAN: Final = "https://data.gov.au/data/api/3/action/package_show"
PACKAGE: Final = "cricos"
# Verified against the live catalogue: the package carries exactly one ZIP,
# "CRICOS Providers, Courses, and Locations". Resolved by format on every run
# rather than pinned by id, because republishing can mint a new resource id
# and a pinned one would then quietly keep serving the superseded release.
ZIP_FORMAT: Final = "ZIP"

STATE_PATH: Final = REPO_ROOT / "data" / "cricos_sync_state.json"
ARCHIVE_PATH: Final = REPO_ROOT / "cricos-providers-courses-and-locations.zip"
EXTRACT_DIR: Final = REPO_ROOT / "data" / "cricos"

TIMEOUT: Final = httpx.Timeout(60.0, read=180.0)


# --------------------------------------------------------------------------- #
# Catalogue
# --------------------------------------------------------------------------- #


class SyncError(RuntimeError):
    """The catalogue could not be read, or did not contain what we expect."""


def fetch_resource() -> dict[str, Any]:
    """Return the CKAN record for the current CRICOS archive."""
    try:
        response = httpx.get(
            CKAN, params={"id": PACKAGE}, timeout=TIMEOUT, follow_redirects=True
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SyncError(f"Could not read the data.gov.au catalogue: {exc}") from exc

    if not payload.get("success"):
        raise SyncError(f"CKAN refused the request for package {PACKAGE!r}")

    resources = payload["result"].get("resources", [])
    archives = [
        item
        for item in resources
        if (item.get("format") or "").upper() == ZIP_FORMAT
        and (item.get("url") or "").lower().endswith(".zip")
    ]
    if not archives:
        raise SyncError(
            f"No ZIP resource in package {PACKAGE!r}. The publisher may have "
            f"changed the format; found: {sorted({r.get('format') for r in resources})}"
        )
    # Newest first, so a package carrying several archives syncs the current
    # one rather than whichever happens to be listed first.
    archives.sort(
        key=lambda item: item.get("last_modified") or item.get("created") or "",
        reverse=True,
    )
    return archives[0]


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


def read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable sync state %s: %s", path, exc)
        return {}


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(path)


def is_current(resource: dict[str, Any], state: dict[str, Any]) -> bool:
    if not state:
        return False
    return all(
        str(state.get(key)) == str(resource.get(source))
        for key, source in (
            ("resource_id", "id"),
            ("last_modified", "last_modified"),
            ("size", "size"),
        )
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path) -> Path:
    """Fetch the archive to a temporary file, then move it into place.

    Downloading over the live archive would, on a failure part way through,
    leave a truncated file that the next run treats as the current release.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".part")
    with httpx.stream(
        "GET", url, timeout=TIMEOUT, follow_redirects=True
    ) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_bytes(1 << 16):
                handle.write(chunk)
    temporary.replace(destination)
    return destination


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #


async def ingest(fx: float) -> dict[str, int]:
    csv_dir = extract(ARCHIVE_PATH, EXTRACT_DIR)
    institutions = load_institutions(csv_dir)
    all_courses, degrees = load_courses(csv_dir, fx)

    await init_schema()
    providers = await upsert_universities(institutions)
    raw = await upsert_raw(all_courses)
    courses = await upsert_courses(degrees)
    return {"providers": providers, "raw": raw, "courses": courses}


async def embed_missing(args: argparse.Namespace) -> tuple[int, int, bool]:
    """Vector anything the sync left without one. Returns (done, left, capped).

    A sync that adds courses leaves them eligible but unrankable, which is the
    same silent gap a bulk import creates - so closing it is part of syncing,
    not a separate chore. The free-tier budget still applies, so a large
    update becomes searchable over several days rather than all at once.
    """
    client = get_qdrant_client()
    await ensure_collection(client)

    checkpoint = Checkpoint(Path(args.checkpoint))
    courses = await pending_courses(client, checkpoint)
    if not courses:
        return 0, 0, False

    remaining = args.daily_limit - checkpoint.spent_today()
    if remaining <= 0:
        return 0, len(courses), True

    try:
        written, _ = await backfill(
            courses,
            batch_size=BATCH,
            per_minute=args.rpm,
            checkpoint=checkpoint,
            daily_budget=args.daily_limit,
        )
        return written, len(courses) - written, False
    except DailyQuotaReached:
        return 0, len(courses), True


async def run(args: argparse.Namespace) -> int:
    state = read_state(Path(args.state))
    resource = fetch_resource()

    published = resource.get("last_modified") or resource.get("created")
    print(f"Published release   {published}")
    print(f"  resource          {resource.get('id')}")
    print(f"  size              {int(resource.get('size') or 0):,} bytes")
    if state:
        print(f"Last synced         {state.get('last_modified')} "
              f"on {state.get('synced_at')}")
    else:
        print("Last synced         never")

    current = is_current(resource, state)
    if current and not args.force:
        print("\nAlready up to date. Nothing downloaded.")
        return 0

    if args.dry_run:
        print()
        if args.force:
            print("A --force sync would re-download and re-ingest this release.")
        elif not state:
            # First run. Saying "a new release is available" would be wrong
            # when the archive on disk is already the published one - which is
            # the normal case for a first sync, since the file was fetched by
            # hand. Size is the only comparison available without downloading.
            local = (
                ARCHIVE_PATH.stat().st_size if ARCHIVE_PATH.is_file() else None
            )
            if local is not None and str(local) == str(resource.get("size")):
                print(
                    "No sync state yet, and the archive already on disk is the "
                    "same size as the published one - almost certainly the same "
                    "release. A real run would download it, confirm by hash, "
                    "skip the ingest if identical, and record the state."
                )
            else:
                print(
                    "No sync state yet; a real run would download this release "
                    "and ingest it."
                )
        else:
            print("A new release is available; a real run would download and ingest it.")
        print(f"  from  {resource.get('url')}")
        print(f"  to    {ARCHIVE_PATH}")
        print("\nDry run - nothing downloaded, nothing written.")
        return 0

    print(f"\nDownloading {resource.get('url')}")
    download(str(resource["url"]), ARCHIVE_PATH)
    digest = sha256(ARCHIVE_PATH)
    print(f"  {ARCHIVE_PATH.stat().st_size:,} bytes  sha256 {digest[:16]}...")

    # The publisher can reissue a resource whose bytes are unchanged. Ingesting
    # it again is harmless - every write is an upsert - but it is minutes of
    # work for a file we already hold, so it is skipped and only the state
    # advanced.
    if digest == state.get("sha256") and not args.force:
        print("\nContents identical to the last sync; skipping ingest.")
        counts = {}
    else:
        print("\nIngesting...")
        counts = await ingest(args.fx)
        for label, value in counts.items():
            print(f"  {label:10} {value:>7,}")

    if args.no_embed:
        # Left to the caller. Useful when a scheduler runs the backfill as its
        # own step, so the day's allowance is spent somewhere it can be seen.
        done, left, capped = 0, 0, False
        print("\nSkipping embeddings (--no-embed).")
    else:
        done, left, capped = await embed_missing(args)
    if done:
        print(f"\nEmbedded {done:,} new course(s).")
    if left:
        note = " (daily free-tier allowance reached)" if capped else ""
        days = -(-left // max(args.daily_limit, 1))
        print(
            f"{left:,} course(s) still need a vector{note} - "
            f"about {days} more daily run(s) of scripts/backfill_embeddings.py."
        )
    elif not done:
        print("\nEvery course already has a vector.")

    write_state(
        Path(args.state),
        {
            "package": PACKAGE,
            "resource_id": resource.get("id"),
            "resource_name": resource.get("name"),
            "url": resource.get("url"),
            "last_modified": published,
            "size": resource.get("size"),
            "sha256": digest,
            "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ingested": counts,
        },
    )
    print(f"\nSync state written to {args.state}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default=str(STATE_PATH))
    parser.add_argument("--fx", type=float, default=0.67, help="AUD -> USD")
    parser.add_argument(
        "--dry-run", action="store_true", help="check only; download nothing"
    )
    parser.add_argument(
        "--force", action="store_true", help="re-sync even if already current"
    )
    parser.add_argument(
        "--checkpoint",
        default=str(REPO_ROOT / "data" / "embedding_checkpoint.json"),
    )
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="ingest only; leave vectors to backfill_embeddings.py",
    )
    parser.add_argument("--rpm", type=int, default=TEXTS_PER_MINUTE)
    parser.add_argument("--daily-limit", type=int, default=TEXTS_PER_DAY)
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
    except SyncError as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
