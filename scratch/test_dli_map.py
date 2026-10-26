"""Generate full-spectrum 600+ Canadian degree seed courses catalog."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = REPO_ROOT / "data" / "canada" / "seed_courses.json"

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
}

print(f"Loaded {len(DLIS)} DLI mappings.")
