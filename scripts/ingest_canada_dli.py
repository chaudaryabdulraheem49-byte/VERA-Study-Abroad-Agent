"""Ingest official Canadian Designated Learning Institutions (DLI) from IRCC.

Fetches the live public registry from canada.ca (or loads a local cache),
normalizes the records, and upserts them into PostgreSQL:
  - `institutions` table: Complete campus-level registry (1,400+ entries)
  - `universities` table: Provider-level records for foreign key linkage

Usage:
    python scripts/ingest_canada_dli.py --dry-run
    python scripts/ingest_canada_dli.py
    python scripts/ingest_canada_dli.py --force-download
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Final

import httpx
from sqlalchemy.dialects.postgresql import insert

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.phase2.db import (  # noqa: E402
    Institution,
    University,
    dispose_engine,
    get_engine,
    init_schema,
)

logger = logging.getLogger("ingest_canada_dli")

DLI_FEED_URL: Final = (
    "https://www.canada.ca/content/dam/ircc/documents/json/dli/dli-full-list.json"
)
DEFAULT_CACHE_DIR: Final = REPO_ROOT / "data" / "canada"
DEFAULT_JSON_PATH: Final = DEFAULT_CACHE_DIR / "dli-full-list.json"
CHUNK: Final = 500


def clean_text(text_val: str | None) -> str:
    """Repair unicode replacement character artifacts from the official government feed."""
    if not text_val:
        return ""
    text_clean = str(text_val).strip()
    if "\ufffd" not in text_clean:
        return text_clean
    text_clean = text_clean.replace(" \ufffd ", " - ")
    text_clean = text_clean.replace(" \ufffd", " - ")
    text_clean = text_clean.replace("\ufffds", "'s")
    text_clean = text_clean.replace("d\ufffd", "d'")
    text_clean = text_clean.replace("l\ufffd", "l'")
    text_clean = text_clean.replace("Coll\ufffdge", "Collège")
    text_clean = text_clean.replace("\ufffducacentre", "Éducacentre")
    text_clean = text_clean.replace("Montr\ufffdal", "Montréal")
    text_clean = text_clean.replace("Universit\ufffd", "Université")
    text_clean = text_clean.replace("Fran\ufffdois", "François")
    text_clean = text_clean.replace("\ufffd", "'")
    return text_clean


def fetch_dli_feed(url: str, cache_path: Path, force: bool = False) -> list[dict[str, Any]]:
    """Retrieve DLI records from local cache or official government endpoint."""
    if cache_path.is_file() and not force:
        logger.info("Loading DLI feed from cache: %s", cache_path)
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            data = payload.get("data", [])
            if data:
                return data
        except (OSError, ValueError) as exc:
            logger.warning("Cache unreadable (%s), downloading fresh copy...", exc)

    logger.info("Downloading official DLI registry from %s ...", url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    with httpx.Client(timeout=60.0, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()

    cache_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved %d bytes to %s", cache_path.stat().st_size, cache_path)
    return payload.get("data", [])


def normalize_records(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Transform raw IRCC items into normalized institution dictionaries."""
    seen_keys: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for item in raw_items:
        dli = (item.get("DLI #") or "").strip()
        name = clean_text(item.get("Institution"))
        if not dli or not name:
            continue

        province = clean_text(item.get("Province"))
        city = clean_text(item.get("City"))
        campus = clean_text(item.get("Campus"))
        campus_location = campus if campus else (city or "Main")

        pgwp_raw = str(item.get("PGWP") or "").strip().lower()
        offers_pgwp = pgwp_raw in ("yes", "details")

        pub_priv = str(item.get("Public/Private") or "").strip().lower()
        is_public = True if "public" in pub_priv else (False if "private" in pub_priv else None)

        record = {
            "dli_number": dli,
            "institution_name": name[:300],
            "province": province[:100] if province else None,
            "city": city[:150] if city else None,
            "campus_location": campus_location[:300],
            "offers_pgwp": offers_pgwp,
            "is_public": is_public,
            "country": "Canada",
            "website": None,
        }
        key = (dli, campus_location[:300], city[:150] if city else None)
        if key not in seen_keys:
            seen_keys[key] = record
        else:
            # If multiple records share the same campus, merge PGWP and public flags
            if offers_pgwp:
                seen_keys[key]["offers_pgwp"] = True
            if is_public:
                seen_keys[key]["is_public"] = True

    return list(seen_keys.values())


async def upsert_institutions(records: list[dict[str, Any]]) -> int:
    """Upsert all campus-level entries into the `institutions` table."""
    engine = get_engine()
    written = 0
    async with engine.begin() as connection:
        for start in range(0, len(records), CHUNK):
            batch = records[start : start + CHUNK]
            statement = insert(Institution).values(batch)
            statement = statement.on_conflict_do_update(
                constraint="uq_institutions_dli_campus_city",
                set_={
                    "institution_name": statement.excluded.institution_name,
                    "province": statement.excluded.province,
                    "offers_pgwp": statement.excluded.offers_pgwp,
                    "is_public": statement.excluded.is_public,
                    "country": statement.excluded.country,
                },
            )
            await connection.execute(statement)
            written += len(batch)
    return written


async def upsert_universities_from_dli(records: list[dict[str, Any]]) -> int:
    """Upsert distinct providers into `universities` table for Course FK compatibility."""
    grouped: dict[str, dict[str, Any]] = {}
    for r in records:
        dli = r["dli_number"]
        if dli not in grouped:
            grouped[dli] = r
        else:
            if r.get("is_public") and not grouped[dli].get("is_public"):
                grouped[dli] = r
            elif r.get("offers_pgwp") and not grouped[dli].get("offers_pgwp"):
                grouped[dli] = r

    uni_records = [
        {
            "university_id": dli,
            "institution_name": data["institution_name"],
            "city": data["city"][:120] if data["city"] else None,
            "state": data["province"][:20] if data["province"] else None,
            "country": "Canada",
            "institution_type": "Public" if data.get("is_public") else "Private",
            "offers_pgwp": data.get("offers_pgwp"),
            "dli_number": dli,
            "website": data.get("website"),
            "trading_name": None,
            "institution_capacity": None,
            "postcode": None,
        }
        for dli, data in grouped.items()
    ]

    engine = get_engine()
    written = 0
    async with engine.begin() as connection:
        for start in range(0, len(uni_records), CHUNK):
            batch = uni_records[start : start + CHUNK]
            statement = insert(University).values(batch)
            statement = statement.on_conflict_do_update(
                index_elements=["university_id"],
                set_={
                    "institution_name": statement.excluded.institution_name,
                    "city": statement.excluded.city,
                    "state": statement.excluded.state,
                    "country": statement.excluded.country,
                    "institution_type": statement.excluded.institution_type,
                    "offers_pgwp": statement.excluded.offers_pgwp,
                    "dli_number": statement.excluded.dli_number,
                },
            )
            await connection.execute(statement)
            written += len(batch)
    return written


def print_summary(records: list[dict[str, Any]]) -> None:
    """Display tabular breakdown of DLI dataset."""
    total = len(records)
    unique_dlis = len({r["dli_number"] for r in records})
    provinces = Counter(r["province"] or "Unknown" for r in records)
    pgwp = Counter("Yes" if r["offers_pgwp"] else "No" for r in records)
    pub = Counter("Public" if r["is_public"] else ("Private" if r["is_public"] is False else "Unknown") for r in records)

    print("\n" + "=" * 60)
    print(" IRCC DESIGNATED LEARNING INSTITUTIONS (DLI) SUMMARY")
    print("=" * 60)
    print(f"Total Campus Records:    {total:,}")
    print(f"Unique DLI Numbers:      {unique_dlis:,}")
    print("\nBy Province / Territory:")
    for prov, count in sorted(provinces.items(), key=lambda x: x[1], reverse=True):
        print(f"  {prov:<28} {count:>5,}  ({count / total * 100:5.1f}%)")
    print("\nBy Type:")
    for t, count in pub.items():
        print(f"  {t:<28} {count:>5,}  ({count / total * 100:5.1f}%)")
    print("\nOffers PGWP Programs:")
    for status, count in pgwp.items():
        print(f"  {status:<28} {count:>5,}  ({count / total * 100:5.1f}%)")
    print("=" * 60 + "\n")


async def run(args: argparse.Namespace) -> int:
    raw_items = fetch_dli_feed(args.url, Path(args.json_path), force=args.force_download)
    if not raw_items:
        logger.error("No items found in DLI feed.")
        return 1

    records = normalize_records(raw_items)
    print_summary(records)

    if args.dry_run:
        print("Dry run requested: no rows written to PostgreSQL.")
        return 0

    await init_schema()
    inst_written = await upsert_institutions(records)
    uni_written = await upsert_universities_from_dli(records)

    print(f"Successfully upserted {inst_written:,} records into 'institutions' table.")
    print(f"Successfully upserted {uni_written:,} distinct providers into 'universities' table.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DLI_FEED_URL, help="URL to official IRCC DLI JSON feed")
    parser.add_argument(
        "--json-path",
        default=str(DEFAULT_JSON_PATH),
        help="Local cache path for DLI feed",
    )
    parser.add_argument("--force-download", action="store_true", help="Download fresh copy even if cached")
    parser.add_argument("--dry-run", action="store_true", help="Parse and summarize without writing to DB")
    return parser


async def _dispatch(args: argparse.Namespace) -> int:
    try:
        return await run(args)
    finally:
        await dispose_engine()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args()
    try:
        return asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
