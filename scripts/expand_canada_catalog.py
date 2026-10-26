"""Expand Canada course catalog to 1,000+ courses across all missing international streams.

Includes:
1. Education & Teaching (Broad Field 07): M.Ed, ECE, TESOL, Curriculum, Leadership
2. Hospitality, Tourism & Event Management (Broad Field 11): Ted Rogers, Royal Roads, Humber, George Brown
3. Media, Public Relations & Journalism: Carleton, UBC, Concordia, SFU, TMU
4. Specialized Computing & Tech (Field 02): Cybersecurity, Cloud, Games, Networks, AI
5. Social Work & Mental Health: MSW, Counselling Psychology, Addictions & Mental Health
6. College Career Post-Graduate Diplomas: Humber, George Brown, Sheridan
"""

from __future__ import annotations

import asyncio
from collections import Counter
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = REPO_ROOT / "data" / "canada" / "seed_courses.json"
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from catalog_data_education import EDUCATION_COURSES
from catalog_data_hospitality import HOSPITALITY_COURSES
from catalog_data_media import MEDIA_COURSES
from catalog_data_tech import TECH_COURSES
from catalog_data_social_work import SOCIAL_WORK_COURSES
from catalog_data_college import COLLEGE_COURSES

DLIS = {
    "University of Toronto": ("O19332746152", "https://www.utoronto.ca/academics/programs"),
    "University of British Columbia (UBC)": ("O19330231062", "https://you.ubc.ca/programs/"),
    "McGill University": ("O19359011033", "https://www.mcgill.ca/study/"),
    "University of Waterloo": ("O19305471522", "https://uwaterloo.ca/future-students/programs"),
    "University of Alberta": ("O19257171832", "https://www.ualberta.ca/admissions/undergraduate/programs"),
    "McMaster University": ("O19395535729", "https://www.mcmaster.ca/programs/"),
    "Western University": ("O19375892122", "https://welcome.uwo.ca/programs/"),
    "Queen's University": ("O19376023352", "https://www.queensu.ca/academics/programs"),
    "University of Calgary": ("O18886830282", "https://www.ucalgary.ca/future-students/undergraduate/explore-programs"),
    "Simon Fraser University (SFU)": ("O18781994282", "https://www.sfu.ca/students/admission/programs.html"),
    "Université d’Ottawa/University of Ottawa": ("O19397188593", "https://www.uottawa.ca/study/programs"),
    "Dalhousie University": ("O19209939282", "https://www.dal.ca/academics/programs.html"),
    "York University": ("O19361109242", "https://futurestudents.yorku.ca/program-search"),
    "Université de Montréal": ("O19359011045", "https://admission.umontreal.ca/programmes/"),
    "University of Guelph": ("O19305391192", "https://www.uoguelph.ca/programs/"),
    "University of Saskatchewan": ("O19425660421", "https://admissions.usask.ca/programs/find-a-program.php"),
    "OCAD University": ("O19332928222", "https://www.ocadu.ca/academics/programs"),
    "Emily Carr University of Art and Design": ("O19361259712", "https://www.ecuad.ca/academics/programs"),
    "Concordia University": ("O19359011007", "https://www.concordia.ca/academics/undergraduate.html"),
    "Carleton University": ("O19332687812", "https://admissions.carleton.ca/programs/"),
    "Toronto Metropolitan University (TMU)": ("O19395677651", "https://www.torontomu.ca/programs/"),
    "University of Victoria": ("O19280533442", "https://www.uvic.ca/programs/"),
    "University of Manitoba": ("O19091528512", "https://umanitoba.ca/explore/programs-of-study"),
    "Memorial University of Newfoundland": ("O19440995346", "https://www.mun.ca/undergrad/programs/"),
    "Université Laval": ("O19359011020", "https://www.ulaval.ca/etudes/programmes"),
    "University of Northern British Columbia (UNBC)": ("O19283889692", "https://www.unbc.ca/programs"),
    "Royal Roads University": ("O19330635812", "https://www.royalroads.ca/programs"),
    "Humber College": ("O19376943122", "https://humber.ca/programs.html"),
    "George Brown College": ("O19283850612", "https://www.georgebrown.ca/programs"),
    "Sheridan College": ("O19385946782", "https://www.sheridancollege.ca/programs"),
}

def make_course_entry(
    uni: str,
    title: str,
    level: str,
    broad: str,
    narrow: str,
    detailed: str,
    fee_cad: float,
    ielts: float,
    gpa: float,
    weeks: int,
    raw_level: str,
    code_suffix: str,
    desc: str,
    intakes: list[str] | None = None,
) -> dict:
    dli, base_url = DLIS[uni]
    uni_clean = uni.replace("Université d’Ottawa/", "").replace(" (UBC)", "").replace(" (SFU)", "").replace(" (TMU)", "")
    words = [w for w in uni_clean.split() if w[0].isupper()]
    acronym = "".join(w[0] for w in words)[:5]
    code = f"CAD-{acronym}-{code_suffix}"[:30]
    intakes_list = intakes or ["September", "January"]
    return {
        "course_title": title,
        "course_name": title,
        "university_name": uni,
        "institution_name": uni,
        "university_id": dli,
        "dli_number": dli,
        "external_course_code": code,
        "country": "Canada",
        "degree_level": level,
        "course_level_raw": raw_level,
        "tuition_fee_cad": float(fee_cad),
        "tuition_fee": float(fee_cad),
        "currency": "CAD",
        "min_ielts_score": float(ielts),
        "min_ielts": float(ielts),
        "min_gpa_percent": float(gpa),
        "min_gpa": float(gpa),
        "duration_weeks": int(weeks),
        "intakes": intakes_list,
        "field_broad": broad,
        "field_narrow": narrow,
        "field_detailed": detailed,
        "syllabus_description": desc,
        "source_url": base_url,
    }

async def fetch_db_gap_courses(existing_pairs: set[tuple[str, str]]) -> list[dict]:
    """Fetch any Canadian courses in Postgres that are not in the seed file."""
    try:
        from app.services.phase2.db import Course, dispose_engine, get_engine
        from sqlalchemy import select

        engine = get_engine()
        async with engine.connect() as conn:
            res = await conn.execute(select(Course).where(Course.country == "Canada"))
            db_courses = res.all()
        await dispose_engine()

        added = []
        for c in db_courses:
            pair = (c.university_name, c.course_title)
            if pair not in existing_pairs:
                dli = c.university_id or DLIS.get(c.university_name, ("", ""))[0]
                fee = float(c.tuition_fee_cad or c.tuition_fee_amount or 40000.0)
                ielts = float(c.min_ielts_score or 6.5)
                gpa = float(c.min_gpa_percent or 65.0)
                added.append({
                    "course_title": c.course_title,
                    "course_name": c.course_title,
                    "university_name": c.university_name,
                    "institution_name": c.university_name,
                    "university_id": dli,
                    "dli_number": dli,
                    "external_course_code": c.external_course_code or f"CAD-GAP-{len(added)}",
                    "country": "Canada",
                    "degree_level": c.degree_level,
                    "course_level_raw": c.course_level_raw or f"{c.degree_level} Degree",
                    "tuition_fee_cad": fee,
                    "tuition_fee": fee,
                    "currency": "CAD",
                    "min_ielts_score": ielts,
                    "min_ielts": ielts,
                    "min_gpa_percent": gpa,
                    "min_gpa": gpa,
                    "duration_weeks": int(c.duration_weeks or 104),
                    "intakes": ["September", "January"],
                    "field_broad": c.field_broad or "Higher Education",
                    "field_narrow": c.field_narrow,
                    "field_detailed": c.field_detailed,
                    "syllabus_description": c.syllabus_description or f"{c.course_title} at {c.university_name}",
                    "source_url": c.source_url or "https://www.educanada.ca/",
                })
        return added
    except Exception as e:
        print(f"Note: Could not query database for gap courses ({e}); proceeding with file catalog.")
        return []

def normalize_existing_course(c: dict) -> dict:
    """Ensure standard alias fields exist on every course."""
    title = c.get("course_title") or c.get("course_name") or ""
    uni = c.get("university_name") or c.get("institution_name") or ""
    dli = c.get("university_id") or c.get("dli_number") or DLIS.get(uni, ("", ""))[0]
    fee = float(c.get("tuition_fee_cad") or c.get("tuition_fee") or 40000.0)
    ielts = float(c.get("min_ielts_score") or c.get("min_ielts") or 6.5)
    gpa = float(c.get("min_gpa_percent") or c.get("min_gpa") or 65.0)
    intakes = c.get("intakes") or ["September", "January"]
    if isinstance(intakes, str):
        try:
            intakes = json.loads(intakes)
        except Exception:
            intakes = ["September", "January"]

    c["course_title"] = title
    c["course_name"] = title
    c["university_name"] = uni
    c["institution_name"] = uni
    c["university_id"] = dli
    c["dli_number"] = dli
    c["country"] = "Canada"
    c["tuition_fee_cad"] = fee
    c["tuition_fee"] = fee
    c["currency"] = "CAD"
    c["min_ielts_score"] = ielts
    c["min_ielts"] = ielts
    c["min_gpa_percent"] = gpa
    c["min_gpa"] = gpa
    c["intakes"] = intakes
    return c

def main() -> None:
    print("=" * 65)
    print(" EXPANDING CANADIAN COURSE CATALOG TO 1,000+ PROGRAMMES")
    print("=" * 65)

    # 1. Load base seed courses
    base_courses = []
    if OUTPUT_FILE.is_file():
        raw = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        base_courses = [normalize_existing_course(c) for c in raw]
        print(f"Loaded {len(base_courses):,} existing courses from {OUTPUT_FILE.name}")
    else:
        print("Existing seed file not found; initializing empty catalog.")

    existing_pairs = set((c["university_name"], c["course_title"]) for c in base_courses)

    # 2. Check Postgres DB gap courses
    gap_courses = asyncio.run(fetch_db_gap_courses(existing_pairs))
    if gap_courses:
        print(f"Found {len(gap_courses)} courses in PostgreSQL not in seed; synchronizing...")
        for gc in gap_courses:
            pair = (gc["university_name"], gc["course_title"])
            if pair not in existing_pairs:
                base_courses.append(gc)
                existing_pairs.add(pair)

    # 3. Process new streams
    new_stream_specs = [
        ("Stream 1: Education & Teaching (Broad Field 07)", EDUCATION_COURSES),
        ("Stream 2: Hospitality, Tourism & Event Management (Field 11)", HOSPITALITY_COURSES),
        ("Stream 3: Media, Public Relations & Journalism (Field 10 & 09)", MEDIA_COURSES),
        ("Stream 4: Specialized Computing & Tech (Field 02)", TECH_COURSES),
        ("Stream 5: Social Work & Mental Health (Field 09 & 06)", SOCIAL_WORK_COURSES),
        ("Stream 6: College Career Post-Graduate Diplomas", COLLEGE_COURSES),
    ]

    added_count = 0
    skipped_count = 0

    for stream_name, course_list in new_stream_specs:
        stream_added = 0
        for item in course_list:
            if len(item) == 13:
                uni, title, lvl, fee, ielts, gpa, wks, raw, code, broad, narrow, detailed, desc = item
            else:
                uni, title, lvl, fee, ielts, gpa, wks, raw, code, narrow, detailed, desc = item
                if narrow.startswith("07"):
                    broad = "07 - Education"
                elif narrow.startswith("11"):
                    broad = "11 - Food, Hospitality and Personal Services"
                elif narrow.startswith("02"):
                    broad = "02 - Information Technology"
                elif narrow.startswith("10"):
                    broad = "10 - Creative Arts"
                elif narrow.startswith("09"):
                    broad = "09 - Society and Culture"
                elif narrow.startswith("06"):
                    broad = "06 - Health"
                elif narrow.startswith("08"):
                    broad = "08 - Management and Commerce"
                elif narrow.startswith("04"):
                    broad = "04 - Architecture and Building"
                elif narrow.startswith("03"):
                    broad = "03 - Engineering and Related Technologies"
                elif narrow.startswith("05"):
                    broad = "05 - Agriculture, Environmental and Related Studies"
                else:
                    broad = "09 - Society and Culture"

            pair = (uni, title)
            if pair in existing_pairs:
                skipped_count += 1
                continue

            entry = make_course_entry(
                uni=uni,
                title=title,
                level=lvl,
                broad=broad,
                narrow=narrow,
                detailed=detailed,
                fee_cad=fee,
                ielts=ielts,
                gpa=gpa,
                weeks=wks,
                raw_level=raw,
                code_suffix=code,
                desc=desc,
            )
            base_courses.append(entry)
            existing_pairs.add(pair)
            added_count += 1
            stream_added += 1
        print(f"  + Added {stream_added:>3} courses from {stream_name}")

    total = len(base_courses)
    print("\n" + "-" * 65)
    print(f"New courses added:       {added_count:,}")
    if skipped_count:
        print(f"Duplicates skipped:      {skipped_count:,}")
    print(f"Total catalog courses:   {total:,}")
    print("-" * 65)

    # 4. Save to disk
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(base_courses, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved complete catalog to: {OUTPUT_FILE}")

    # 5. Print analytics breakdown
    broad_counter = Counter(c["field_broad"] for c in base_courses)
    level_counter = Counter(c["degree_level"] for c in base_courses)
    uni_counter = Counter(c["university_name"] for c in base_courses)

    print("\nDiscipline Distribution (Broad Fields):")
    for field, count in sorted(broad_counter.items(), key=lambda x: x[1], reverse=True):
        print(f"  {field:<50} {count:>4,}  ({count / total * 100:5.1f}%)")

    print("\nDegree Level Distribution:")
    for lvl, count in sorted(level_counter.items(), key=lambda x: x[1], reverse=True):
        print(f"  {lvl:<30} {count:>4,}  ({count / total * 100:5.1f}%)")

    print(f"\nCovered DLIs / Institutions: {len(uni_counter)}")
    for uni, count in sorted(uni_counter.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {uni:<38} {count:>4,} program(s)")
    if len(uni_counter) > 10:
        print(f"  ... and {len(uni_counter) - 10} more institutions.")

    print("=" * 65 + "\n")

if __name__ == "__main__":
    main()
