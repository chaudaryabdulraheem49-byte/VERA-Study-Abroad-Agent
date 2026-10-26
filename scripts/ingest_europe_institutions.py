"""Ingest European Accredited Universities (ETER / National Portals) across 13 Countries.

Upserts 260 top accredited universities across 13 target European destination countries:
Germany, Netherlands, Ireland, Sweden, France, Italy, Switzerland, Finland,
Norway, Denmark, Poland, Austria, and Belgium.

Populates:
  - `institutions` table: Campus-level registry with official ETER ID / registry code
  - `universities` table: Provider-level record for foreign key linkage with courses

Usage:
    python scripts/ingest_europe_institutions.py --dry-run
    python scripts/ingest_europe_institutions.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Final

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

logger = logging.getLogger("ingest_europe_institutions")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CHUNK: Final = 100

EUROPE_INSTITUTIONS_DATA: Final[list[dict[str, Any]]] = [
    # -------------------------------------------------------------------------
    # 1. GERMANY (42 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-DE-TUM", "dli": "ETER-DE-TUM", "name": "Technical University of Munich (TUM)",
        "city": "Munich", "state": "Bavaria", "country": "Germany", "type": "Public TU9 / Excellence University",
        "is_public": True, "website": "https://www.tum.de"
    },
    {
        "uni_id": "EU-DE-LMU", "dli": "ETER-DE-LMU", "name": "Ludwig Maximilian University of Munich (LMU Munich)",
        "city": "Munich", "state": "Bavaria", "country": "Germany", "type": "Public Excellence University",
        "is_public": True, "website": "https://www.lmu.de"
    },
    {
        "uni_id": "EU-DE-RWTH", "dli": "ETER-DE-RWTH", "name": "RWTH Aachen University",
        "city": "Aachen", "state": "North Rhine-Westphalia", "country": "Germany", "type": "Public TU9 / Excellence University",
        "is_public": True, "website": "https://www.rwth-aachen.de"
    },
    {
        "uni_id": "EU-DE-TUBERLIN", "dli": "ETER-DE-TUB", "name": "Technical University of Berlin (TU Berlin)",
        "city": "Berlin", "state": "Berlin", "country": "Germany", "type": "Public TU9 / Excellence University",
        "is_public": True, "website": "https://www.tu.berlin"
    },
    {
        "uni_id": "EU-DE-KIT", "dli": "ETER-DE-KIT", "name": "Karlsruhe Institute of Technology (KIT)",
        "city": "Karlsruhe", "state": "Baden-Württemberg", "country": "Germany", "type": "Public TU9 / Excellence University",
        "is_public": True, "website": "https://www.kit.edu"
    },
    {
        "uni_id": "EU-DE-STUTTGART", "dli": "ETER-DE-UST", "name": "University of Stuttgart",
        "city": "Stuttgart", "state": "Baden-Württemberg", "country": "Germany", "type": "Public TU9 University",
        "is_public": True, "website": "https://www.uni-stuttgart.de"
    },
    {
        "uni_id": "EU-DE-HEIDELBERG", "dli": "ETER-DE-HD", "name": "Heidelberg University",
        "city": "Heidelberg", "state": "Baden-Württemberg", "country": "Germany", "type": "Public Excellence University",
        "is_public": True, "website": "https://www.uni-heidelberg.de"
    },
    {
        "uni_id": "EU-DE-FREIBURG", "dli": "ETER-DE-FR", "name": "University of Freiburg",
        "city": "Freiburg", "state": "Baden-Württemberg", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://uni-freiburg.de"
    },
    {
        "uni_id": "EU-DE-TUDRESDEN", "dli": "ETER-DE-TUD", "name": "Technical University of Dresden (TU Dresden)",
        "city": "Dresden", "state": "Saxony", "country": "Germany", "type": "Public TU9 / Excellence University",
        "is_public": True, "website": "https://tu-dresden.de"
    },
    {
        "uni_id": "EU-DE-BONN", "dli": "ETER-DE-BN", "name": "University of Bonn",
        "city": "Bonn", "state": "North Rhine-Westphalia", "country": "Germany", "type": "Public Excellence University",
        "is_public": True, "website": "https://www.uni-bonn.de"
    },
    {
        "uni_id": "EU-DE-FAU", "dli": "ETER-DE-FAU", "name": "Friedrich-Alexander University Erlangen-Nürnberg (FAU)",
        "city": "Erlangen", "state": "Bavaria", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.fau.de"
    },
    {
        "uni_id": "EU-DE-HAMBURG", "dli": "ETER-DE-HH", "name": "University of Hamburg",
        "city": "Hamburg", "state": "Hamburg", "country": "Germany", "type": "Public Excellence University",
        "is_public": True, "website": "https://www.uni-hamburg.de"
    },
    {
        "uni_id": "EU-DE-TUDARMSTADT", "dli": "ETER-DE-TUDAR", "name": "Technical University of Darmstadt (TU Darmstadt)",
        "city": "Darmstadt", "state": "Hesse", "country": "Germany", "type": "Public TU9 University",
        "is_public": True, "website": "https://www.tu-darmstadt.de"
    },
    {
        "uni_id": "EU-DE-GOETTINGEN", "dli": "ETER-DE-GOE", "name": "University of Göttingen",
        "city": "Göttingen", "state": "Lower Saxony", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-goettingen.de"
    },
    {
        "uni_id": "EU-DE-TUEBINGEN", "dli": "ETER-DE-TUE", "name": "University of Tübingen",
        "city": "Tübingen", "state": "Baden-Württemberg", "country": "Germany", "type": "Public Excellence University",
        "is_public": True, "website": "https://uni-tuebingen.de"
    },
    {
        "uni_id": "EU-DE-HUMBOLDT", "dli": "ETER-DE-HUB", "name": "Humboldt University of Berlin",
        "city": "Berlin", "state": "Berlin", "country": "Germany", "type": "Public Excellence University",
        "is_public": True, "website": "https://www.hu-berlin.de"
    },
    {
        "uni_id": "EU-DE-FUBERLIN", "dli": "ETER-DE-FUB", "name": "Free University of Berlin (FU Berlin)",
        "city": "Berlin", "state": "Berlin", "country": "Germany", "type": "Public Excellence University",
        "is_public": True, "website": "https://www.fu-berlin.de"
    },
    {
        "uni_id": "EU-DE-COLOGNE", "dli": "ETER-DE-KOELN", "name": "University of Cologne",
        "city": "Cologne", "state": "North Rhine-Westphalia", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-koeln.de"
    },
    {
        "uni_id": "EU-DE-FRANKFURT", "dli": "ETER-DE-FRA", "name": "Goethe University Frankfurt",
        "city": "Frankfurt", "state": "Hesse", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-frankfurt.de"
    },
    {
        "uni_id": "EU-DE-HANNOVER", "dli": "ETER-DE-LUH", "name": "Leibniz University Hannover",
        "city": "Hannover", "state": "Lower Saxony", "country": "Germany", "type": "Public TU9 University",
        "is_public": True, "website": "https://www.uni-hannover.de"
    },
    {
        "uni_id": "EU-DE-BREMEN", "dli": "ETER-DE-BRE", "name": "University of Bremen",
        "city": "Bremen", "state": "Bremen", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-bremen.de"
    },
    {
        "uni_id": "EU-DE-MUENSTER", "dli": "ETER-DE-MS", "name": "University of Münster",
        "city": "Münster", "state": "North Rhine-Westphalia", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-muenster.de"
    },
    {
        "uni_id": "EU-DE-BOCHUM", "dli": "ETER-DE-RUB", "name": "Ruhr University Bochum",
        "city": "Bochum", "state": "North Rhine-Westphalia", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.ruhr-uni-bochum.de"
    },
    {
        "uni_id": "EU-DE-DUISBURG", "dli": "ETER-DE-UDE", "name": "University of Duisburg-Essen",
        "city": "Duisburg", "state": "North Rhine-Westphalia", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-due.de"
    },
    {
        "uni_id": "EU-DE-FREIBERG", "dli": "ETER-DE-BAF", "name": "TU Bergakademie Freiberg",
        "city": "Freiberg", "state": "Saxony", "country": "Germany", "type": "Public Resource & Tech University",
        "is_public": True, "website": "https://tu-freiberg.de"
    },
    {
        "uni_id": "EU-DE-TUBRAUN", "dli": "ETER-DE-TUBS", "name": "Technical University of Braunschweig (TU Braunschweig)",
        "city": "Braunschweig", "state": "Lower Saxony", "country": "Germany", "type": "Public TU9 University",
        "is_public": True, "website": "https://www.tu-braunschweig.de"
    },
    {
        "uni_id": "EU-DE-MANNHEIM", "dli": "ETER-DE-MAN", "name": "University of Mannheim",
        "city": "Mannheim", "state": "Baden-Württemberg", "country": "Germany", "type": "Public Business & Social Science Hub",
        "is_public": True, "website": "https://www.uni-mannheim.de"
    },
    {
        "uni_id": "EU-DE-WUERZBURG", "dli": "ETER-DE-WUE", "name": "University of Würzburg",
        "city": "Würzburg", "state": "Bavaria", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-wuerzburg.de"
    },
    {
        "uni_id": "EU-DE-LEIPZIG", "dli": "ETER-DE-LEI", "name": "University of Leipzig",
        "city": "Leipzig", "state": "Saxony", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-leipzig.de"
    },
    {
        "uni_id": "EU-DE-JENA", "dli": "ETER-DE-JEN", "name": "University of Jena",
        "city": "Jena", "state": "Thuringia", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-jena.de"
    },
    {
        "uni_id": "EU-DE-POTSDAM", "dli": "ETER-DE-POT", "name": "University of Potsdam",
        "city": "Potsdam", "state": "Brandenburg", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-potsdam.de"
    },
    {
        "uni_id": "EU-DE-ULM", "dli": "ETER-DE-ULM", "name": "Ulm University",
        "city": "Ulm", "state": "Baden-Württemberg", "country": "Germany", "type": "Public STEM & Medical University",
        "is_public": True, "website": "https://www.uni-ulm.de"
    },
    {
        "uni_id": "EU-DE-BAYREUTH", "dli": "ETER-DE-BAY", "name": "University of Bayreuth",
        "city": "Bayreuth", "state": "Bavaria", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-bayreuth.de"
    },
    {
        "uni_id": "EU-DE-AUGSBURG", "dli": "ETER-DE-AUG", "name": "University of Augsburg",
        "city": "Augsburg", "state": "Bavaria", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-augsburg.de"
    },
    {
        "uni_id": "EU-DE-PASSAU", "dli": "ETER-DE-PAS", "name": "University of Passau",
        "city": "Passau", "state": "Bavaria", "country": "Germany", "type": "Public Law & Digital Hub",
        "is_public": True, "website": "https://www.uni-passau.de"
    },
    {
        "uni_id": "EU-DE-ILMENAU", "dli": "ETER-DE-ILM", "name": "Technical University of Ilmenau",
        "city": "Ilmenau", "state": "Thuringia", "country": "Germany", "type": "Public Technical University",
        "is_public": True, "website": "https://www.tu-ilmenau.de"
    },
    {
        "uni_id": "EU-DE-TUHH", "dli": "ETER-DE-TUHH", "name": "Hamburg University of Technology (TUHH)",
        "city": "Hamburg", "state": "Hamburg", "country": "Germany", "type": "Public Technical University",
        "is_public": True, "website": "https://www.tuhh.de"
    },
    {
        "uni_id": "EU-DE-HOHENHEIM", "dli": "ETER-DE-HOH", "name": "University of Hohenheim",
        "city": "Stuttgart", "state": "Baden-Württemberg", "country": "Germany", "type": "Public Agricultural & Bioeconomy Hub",
        "is_public": True, "website": "https://www.uni-hohenheim.de"
    },
    {
        "uni_id": "EU-DE-TUDORTMUND", "dli": "ETER-DE-TUDO", "name": "Dortmund University of Technology (TU Dortmund)",
        "city": "Dortmund", "state": "North Rhine-Westphalia", "country": "Germany", "type": "Public Technical University",
        "is_public": True, "website": "https://www.tu-dortmund.de"
    },
    {
        "uni_id": "EU-DE-KONSTANZ", "dli": "ETER-DE-KN", "name": "University of Konstanz",
        "city": "Konstanz", "state": "Baden-Württemberg", "country": "Germany", "type": "Public Research University",
        "is_public": True, "website": "https://www.uni-konstanz.de"
    },
    {
        "uni_id": "EU-DE-FSFM", "dli": "ETER-DE-FS", "name": "Frankfurt School of Finance & Management",
        "city": "Frankfurt", "state": "Hesse", "country": "Germany", "type": "Private Business School",
        "is_public": False, "website": "https://www.frankfurt-school.de"
    },
    {
        "uni_id": "EU-DE-ESMT", "dli": "ETER-DE-ESMT", "name": "ESMT Berlin",
        "city": "Berlin", "state": "Berlin", "country": "Germany", "type": "Private International Business School",
        "is_public": False, "website": "https://esmt.berlin"
    },

    # -------------------------------------------------------------------------
    # 2. NETHERLANDS (22 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-NL-TUDELFT", "dli": "ETER-NL-TUD", "name": "Delft University of Technology (TU Delft)",
        "city": "Delft", "state": "South Holland", "country": "Netherlands", "type": "Public Technical University",
        "is_public": True, "website": "https://www.tudelft.nl"
    },
    {
        "uni_id": "EU-NL-UVA", "dli": "ETER-NL-UVA", "name": "University of Amsterdam (UvA)",
        "city": "Amsterdam", "state": "North Holland", "country": "Netherlands", "type": "Public Research University",
        "is_public": True, "website": "https://www.uva.nl"
    },
    {
        "uni_id": "EU-NL-ERASMUS", "dli": "ETER-NL-EUR", "name": "Erasmus University Rotterdam",
        "city": "Rotterdam", "state": "South Holland", "country": "Netherlands", "type": "Public Research University",
        "is_public": True, "website": "https://www.eur.nl"
    },
    {
        "uni_id": "EU-NL-TUE", "dli": "ETER-NL-TUE", "name": "Eindhoven University of Technology (TU/e)",
        "city": "Eindhoven", "state": "North Brabant", "country": "Netherlands", "type": "Public Technical University",
        "is_public": True, "website": "https://www.tue.nl"
    },
    {
        "uni_id": "EU-NL-UTRECHT", "dli": "ETER-NL-UU", "name": "Utrecht University",
        "city": "Utrecht", "state": "Utrecht", "country": "Netherlands", "type": "Public Research University",
        "is_public": True, "website": "https://www.uu.nl"
    },
    {
        "uni_id": "EU-NL-LEIDEN", "dli": "ETER-NL-LEI", "name": "Leiden University",
        "city": "Leiden", "state": "South Holland", "country": "Netherlands", "type": "Public Research University",
        "is_public": True, "website": "https://www.universiteitleiden.nl"
    },
    {
        "uni_id": "EU-NL-GRONINGEN", "dli": "ETER-NL-RUG", "name": "University of Groningen",
        "city": "Groningen", "state": "Groningen", "country": "Netherlands", "type": "Public Research University",
        "is_public": True, "website": "https://www.rug.nl"
    },
    {
        "uni_id": "EU-NL-MAASTRICHT", "dli": "ETER-NL-UM", "name": "Maastricht University",
        "city": "Maastricht", "state": "Limburg", "country": "Netherlands", "type": "Public Problem-Based Learning Hub",
        "is_public": True, "website": "https://www.maastrichtuniversity.nl"
    },
    {
        "uni_id": "EU-NL-WAGENINGEN", "dli": "ETER-NL-WUR", "name": "Wageningen University & Research",
        "city": "Wageningen", "state": "Gelderland", "country": "Netherlands", "type": "Public Agri-Tech & Life Science Hub",
        "is_public": True, "website": "https://www.wur.nl"
    },
    {
        "uni_id": "EU-NL-RADBOUD", "dli": "ETER-NL-RU", "name": "Radboud University",
        "city": "Nijmegen", "state": "Gelderland", "country": "Netherlands", "type": "Public Research University",
        "is_public": True, "website": "https://www.ru.nl"
    },
    {
        "uni_id": "EU-NL-TWENTE", "dli": "ETER-NL-UT", "name": "University of Twente",
        "city": "Enschede", "state": "Overijssel", "country": "Netherlands", "type": "Public High-Tech Human-Touch University",
        "is_public": True, "website": "https://www.utwente.nl"
    },
    {
        "uni_id": "EU-NL-VU", "dli": "ETER-NL-VU", "name": "Vrije Universiteit Amsterdam (VU Amsterdam)",
        "city": "Amsterdam", "state": "North Holland", "country": "Netherlands", "type": "Public Research University",
        "is_public": True, "website": "https://vu.nl"
    },
    {
        "uni_id": "EU-NL-TILBURG", "dli": "ETER-NL-TIL", "name": "Tilburg University",
        "city": "Tilburg", "state": "North Brabant", "country": "Netherlands", "type": "Public Law, Business & Data Hub",
        "is_public": True, "website": "https://www.tilburguniversity.edu"
    },
    {
        "uni_id": "EU-NL-RSM", "dli": "ETER-NL-RSM", "name": "Rotterdam School of Management",
        "city": "Rotterdam", "state": "South Holland", "country": "Netherlands", "type": "Public Triple-Accredited Business School",
        "is_public": True, "website": "https://www.rsm.nl"
    },
    {
        "uni_id": "EU-NL-THUAS", "dli": "ETER-NL-THUAS", "name": "The Hague University of Applied Sciences",
        "city": "The Hague", "state": "South Holland", "country": "Netherlands", "type": "Public University of Applied Sciences",
        "is_public": True, "website": "https://www.thehagueuniversity.com"
    },
    {
        "uni_id": "EU-NL-HANZE", "dli": "ETER-NL-HANZE", "name": "Hanze University of Applied Sciences",
        "city": "Groningen", "state": "Groningen", "country": "Netherlands", "type": "Public University of Applied Sciences",
        "is_public": True, "website": "https://www.hanze.nl"
    },
    {
        "uni_id": "EU-NL-FONTYS", "dli": "ETER-NL-FONT", "name": "Fontys University of Applied Sciences",
        "city": "Eindhoven", "state": "North Brabant", "country": "Netherlands", "type": "Public University of Applied Sciences",
        "is_public": True, "website": "https://fontys.edu"
    },
    {
        "uni_id": "EU-NL-SAXION", "dli": "ETER-NL-SAX", "name": "Saxion University of Applied Sciences",
        "city": "Enschede", "state": "Overijssel", "country": "Netherlands", "type": "Public University of Applied Sciences",
        "is_public": True, "website": "https://www.saxion.edu"
    },
    {
        "uni_id": "EU-NL-AUAS", "dli": "ETER-NL-AUAS", "name": "Amsterdam University of Applied Sciences (AUAS)",
        "city": "Amsterdam", "state": "North Holland", "country": "Netherlands", "type": "Public University of Applied Sciences",
        "is_public": True, "website": "https://www.amsterdamuas.com"
    },
    {
        "uni_id": "EU-NL-BREDA", "dli": "ETER-NL-BUAS", "name": "Breda University of Applied Sciences",
        "city": "Breda", "state": "North Brabant", "country": "Netherlands", "type": "Public Tourism & Media Institute",
        "is_public": True, "website": "https://www.buas.nl"
    },
    {
        "uni_id": "EU-NL-AVANS", "dli": "ETER-NL-AVANS", "name": "Avans University of Applied Sciences",
        "city": "Breda", "state": "North Brabant", "country": "Netherlands", "type": "Public University of Applied Sciences",
        "is_public": True, "website": "https://www.avans.nl"
    },
    {
        "uni_id": "EU-NL-NYENRODE", "dli": "ETER-NL-NYEN", "name": "Nyenrode Business University",
        "city": "Breukelen", "state": "Utrecht", "country": "Netherlands", "type": "Private Business University",
        "is_public": False, "website": "https://www.nyenrode.nl"
    },

    # -------------------------------------------------------------------------
    # 3. IRELAND (16 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-IE-TCD", "dli": "ETER-IE-TCD", "name": "Trinity College Dublin",
        "city": "Dublin", "state": "Leinster", "country": "Ireland", "type": "Public Ancient University",
        "is_public": True, "website": "https://www.tcd.ie"
    },
    {
        "uni_id": "EU-IE-UCD", "dli": "ETER-IE-UCD", "name": "University College Dublin (UCD)",
        "city": "Dublin", "state": "Leinster", "country": "Ireland", "type": "Public Research University",
        "is_public": True, "website": "https://www.ucd.ie"
    },
    {
        "uni_id": "EU-IE-GALWAY", "dli": "ETER-IE-NUIG", "name": "University of Galway",
        "city": "Galway", "state": "Connacht", "country": "Ireland", "type": "Public Research University",
        "is_public": True, "website": "https://www.universityofgalway.ie"
    },
    {
        "uni_id": "EU-IE-UCC", "dli": "ETER-IE-UCC", "name": "University College Cork (UCC)",
        "city": "Cork", "state": "Munster", "country": "Ireland", "type": "Public Research University",
        "is_public": True, "website": "https://www.ucc.ie"
    },
    {
        "uni_id": "EU-IE-DCU", "dli": "ETER-IE-DCU", "name": "Dublin City University (DCU)",
        "city": "Dublin", "state": "Leinster", "country": "Ireland", "type": "Public Enterprise University",
        "is_public": True, "website": "https://www.dcu.ie"
    },
    {
        "uni_id": "EU-IE-UL", "dli": "ETER-IE-UL", "name": "University of Limerick (UL)",
        "city": "Limerick", "state": "Munster", "country": "Ireland", "type": "Public Research University",
        "is_public": True, "website": "https://www.ul.ie"
    },
    {
        "uni_id": "EU-IE-MAYNOOTH", "dli": "ETER-IE-MAY", "name": "Maynooth University",
        "city": "Maynooth", "state": "Leinster", "country": "Ireland", "type": "Public Research University",
        "is_public": True, "website": "https://www.maynoothuniversity.ie"
    },
    {
        "uni_id": "EU-IE-TUDUBLIN", "dli": "ETER-IE-TUD", "name": "Technological University Dublin (TU Dublin)",
        "city": "Dublin", "state": "Leinster", "country": "Ireland", "type": "Public Technological University",
        "is_public": True, "website": "https://www.tudublin.ie"
    },
    {
        "uni_id": "EU-IE-MTU", "dli": "ETER-IE-MTU", "name": "Munster Technological University (MTU)",
        "city": "Cork", "state": "Munster", "country": "Ireland", "type": "Public Technological University",
        "is_public": True, "website": "https://www.mtu.ie"
    },
    {
        "uni_id": "EU-IE-ATU", "dli": "ETER-IE-ATU", "name": "Atlantic Technological University (ATU)",
        "city": "Galway", "state": "Connacht", "country": "Ireland", "type": "Public Technological University",
        "is_public": True, "website": "https://www.atu.ie"
    },
    {
        "uni_id": "EU-IE-SETU", "dli": "ETER-IE-SETU", "name": "South East Technological University (SETU)",
        "city": "Waterford", "state": "Munster", "country": "Ireland", "type": "Public Technological University",
        "is_public": True, "website": "https://www.setu.ie"
    },
    {
        "uni_id": "EU-IE-TUS", "dli": "ETER-IE-TUS", "name": "Technological University of the Shannon (TUS)",
        "city": "Limerick", "state": "Munster", "country": "Ireland", "type": "Public Technological University",
        "is_public": True, "website": "https://www.tus.ie"
    },
    {
        "uni_id": "EU-IE-RCSI", "dli": "ETER-IE-RCSI", "name": "Royal College of Surgeons in Ireland (RCSI)",
        "city": "Dublin", "state": "Leinster", "country": "Ireland", "type": "Public Medical University",
        "is_public": True, "website": "https://www.rcsi.com"
    },
    {
        "uni_id": "EU-IE-NCI", "dli": "ETER-IE-NCI", "name": "National College of Ireland (NCI)",
        "city": "Dublin", "state": "Leinster", "country": "Ireland", "type": "Public State-Aided College",
        "is_public": True, "website": "https://www.ncirl.ie"
    },
    {
        "uni_id": "EU-IE-DKIT", "dli": "ETER-IE-DKIT", "name": "Dundalk Institute of Technology",
        "city": "Dundalk", "state": "Leinster", "country": "Ireland", "type": "Public Institute of Technology",
        "is_public": True, "website": "https://www.dkit.ie"
    },
    {
        "uni_id": "EU-IE-GRIFFITH", "dli": "ETER-IE-GRIFF", "name": "Griffith College Dublin",
        "city": "Dublin", "state": "Leinster", "country": "Ireland", "type": "Private Higher Education Institute",
        "is_public": False, "website": "https://www.griffith.ie"
    },

    # -------------------------------------------------------------------------
    # 4. SWEDEN (18 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-SE-KTH", "dli": "ETER-SE-KTH", "name": "KTH Royal Institute of Technology",
        "city": "Stockholm", "state": "Stockholm", "country": "Sweden", "type": "Public Technical University",
        "is_public": True, "website": "https://www.kth.se"
    },
    {
        "uni_id": "EU-SE-LUND", "dli": "ETER-SE-LUND", "name": "Lund University",
        "city": "Lund", "state": "Skåne", "country": "Sweden", "type": "Public Research University",
        "is_public": True, "website": "https://www.lunduniversity.lu.se"
    },
    {
        "uni_id": "EU-SE-CHALMERS", "dli": "ETER-SE-CHAL", "name": "Chalmers University of Technology",
        "city": "Gothenburg", "state": "Västra Götaland", "country": "Sweden", "type": "Public Technical University",
        "is_public": True, "website": "https://www.chalmers.se"
    },
    {
        "uni_id": "EU-SE-UPPSALA", "dli": "ETER-SE-UPP", "name": "Uppsala University",
        "city": "Uppsala", "state": "Uppsala", "country": "Sweden", "type": "Public Research University",
        "is_public": True, "website": "https://www.uu.se"
    },
    {
        "uni_id": "EU-SE-STOCKHOLM", "dli": "ETER-SE-SU", "name": "Stockholm University",
        "city": "Stockholm", "state": "Stockholm", "country": "Sweden", "type": "Public Research University",
        "is_public": True, "website": "https://www.su.se"
    },
    {
        "uni_id": "EU-SE-KAROLINSKA", "dli": "ETER-SE-KI", "name": "Karolinska Institute",
        "city": "Stockholm", "state": "Stockholm", "country": "Sweden", "type": "Public Medical Research University",
        "is_public": True, "website": "https://ki.se"
    },
    {
        "uni_id": "EU-SE-GOTHENBURG", "dli": "ETER-SE-GU", "name": "University of Gothenburg",
        "city": "Gothenburg", "state": "Västra Götaland", "country": "Sweden", "type": "Public Research University",
        "is_public": True, "website": "https://www.gu.se"
    },
    {
        "uni_id": "EU-SE-LINKOPING", "dli": "ETER-SE-LIU", "name": "Linköping University",
        "city": "Linköping", "state": "Östergötland", "country": "Sweden", "type": "Public Research University",
        "is_public": True, "website": "https://liu.se"
    },
    {
        "uni_id": "EU-SE-UMEA", "dli": "ETER-SE-UMU", "name": "Umeå University",
        "city": "Umeå", "state": "Västerbotten", "country": "Sweden", "type": "Public Research University",
        "is_public": True, "website": "https://www.umu.se"
    },
    {
        "uni_id": "EU-SE-LULEA", "dli": "ETER-SE-LTU", "name": "Luleå University of Technology",
        "city": "Luleå", "state": "Norrbotten", "country": "Sweden", "type": "Public Technical University",
        "is_public": True, "website": "https://www.ltu.se"
    },
    {
        "uni_id": "EU-SE-OREBRO", "dli": "ETER-SE-ORU", "name": "Örebro University",
        "city": "Örebro", "state": "Örebro", "country": "Sweden", "type": "Public Research University",
        "is_public": True, "website": "https://www.oru.se"
    },
    {
        "uni_id": "EU-SE-KARLSTAD", "dli": "ETER-SE-KAU", "name": "Karlstad University",
        "city": "Karlstad", "state": "Värmland", "country": "Sweden", "type": "Public University",
        "is_public": True, "website": "https://www.kau.se"
    },
    {
        "uni_id": "EU-SE-LINNAEUS", "dli": "ETER-SE-LNU", "name": "Linnaeus University",
        "city": "Växjö", "state": "Kronoberg", "country": "Sweden", "type": "Public University",
        "is_public": True, "website": "https://lnu.se"
    },
    {
        "uni_id": "EU-SE-MALMO", "dli": "ETER-SE-MAU", "name": "Malmö University",
        "city": "Malmö", "state": "Skåne", "country": "Sweden", "type": "Public University",
        "is_public": True, "website": "https://mau.se"
    },
    {
        "uni_id": "EU-SE-MIDSWEDEN", "dli": "ETER-SE-MIUN", "name": "Mid Sweden University",
        "city": "Sundsvall", "state": "Västernorrland", "country": "Sweden", "type": "Public University",
        "is_public": True, "website": "https://www.miun.se"
    },
    {
        "uni_id": "EU-SE-MALARDALEN", "dli": "ETER-SE-MDU", "name": "Mälardalen University",
        "city": "Västerås", "state": "Västmanland", "country": "Sweden", "type": "Public University",
        "is_public": True, "website": "https://www.mdu.se"
    },
    {
        "uni_id": "EU-SE-JONKOPING", "dli": "ETER-SE-JU", "name": "Jönköping University",
        "city": "Jönköping", "state": "Jönköping", "country": "Sweden", "type": "Public Foundation University",
        "is_public": True, "website": "https://ju.se"
    },
    {
        "uni_id": "EU-SE-SSE", "dli": "ETER-SE-SSE", "name": "Stockholm School of Economics (SSE)",
        "city": "Stockholm", "state": "Stockholm", "country": "Sweden", "type": "Private Business School",
        "is_public": False, "website": "https://www.hhs.se"
    },

    # -------------------------------------------------------------------------
    # 5. FRANCE (30 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-FR-SORBONNE", "dli": "ETER-FR-SORB", "name": "Sorbonne University",
        "city": "Paris", "state": "Île-de-France", "country": "France", "type": "Public Research University",
        "is_public": True, "website": "https://www.sorbonne-universite.fr"
    },
    {
        "uni_id": "EU-FR-POLYTECH", "dli": "ETER-FR-X", "name": "École Polytechnique",
        "city": "Palaiseau", "state": "Île-de-France", "country": "France", "type": "Public Grande École of Engineering",
        "is_public": True, "website": "https://www.polytechnique.edu"
    },
    {
        "uni_id": "EU-FR-PSL", "dli": "ETER-FR-PSL", "name": "Paris Sciences et Lettres University (PSL)",
        "city": "Paris", "state": "Île-de-France", "country": "France", "type": "Public Collegiate University",
        "is_public": True, "website": "https://psl.eu"
    },
    {
        "uni_id": "EU-FR-SACLAY", "dli": "ETER-FR-UPS", "name": "Paris-Saclay University",
        "city": "Orsay", "state": "Île-de-France", "country": "France", "type": "Public Intensive Research Hub",
        "is_public": True, "website": "https://www.universite-paris-saclay.fr"
    },
    {
        "uni_id": "EU-FR-SCIENCESPO", "dli": "ETER-FR-SCPO", "name": "Sciences Po Paris",
        "city": "Paris", "state": "Île-de-France", "country": "France", "type": "Public Political & Social Sciences Grande École",
        "is_public": True, "website": "https://www.sciencespo.fr"
    },
    {
        "uni_id": "EU-FR-CSUPELEC", "dli": "ETER-FR-CSUP", "name": "CentraleSupélec",
        "city": "Gif-sur-Yvette", "state": "Île-de-France", "country": "France", "type": "Public Engineering Grande École",
        "is_public": True, "website": "https://www.centralesupelec.fr"
    },
    {
        "uni_id": "EU-FR-HEC", "dli": "ETER-FR-HEC", "name": "HEC Paris",
        "city": "Jouy-en-Josas", "state": "Île-de-France", "country": "France", "type": "Private Leading European Business School",
        "is_public": False, "website": "https://www.hec.edu"
    },
    {
        "uni_id": "EU-FR-INSEAD", "dli": "ETER-FR-INSEAD", "name": "INSEAD Business School",
        "city": "Fontainebleau", "state": "Île-de-France", "country": "France", "type": "Private Global Management School",
        "is_public": False, "website": "https://www.insead.edu"
    },
    {
        "uni_id": "EU-FR-PARISCITE", "dli": "ETER-FR-UPC", "name": "University of Paris Cité",
        "city": "Paris", "state": "Île-de-France", "country": "France", "type": "Public Health & Science University",
        "is_public": True, "website": "https://u-paris.fr"
    },
    {
        "uni_id": "EU-FR-GRENOBLE", "dli": "ETER-FR-UGA", "name": "University Grenoble Alpes",
        "city": "Grenoble", "state": "Auvergne-Rhône-Alpes", "country": "France", "type": "Public High-Tech Research Hub",
        "is_public": True, "website": "https://www.univ-grenoble-alpes.fr"
    },
    {
        "uni_id": "EU-FR-STRASBOURG", "dli": "ETER-FR-UNISTRA", "name": "University of Strasbourg",
        "city": "Strasbourg", "state": "Grand Est", "country": "France", "type": "Public Research University",
        "is_public": True, "website": "https://www.unistra.fr"
    },
    {
        "uni_id": "EU-FR-AMU", "dli": "ETER-FR-AMU", "name": "Aix-Marseille University",
        "city": "Marseille", "state": "Provence-Alpes-Côte d'Azur", "country": "France", "type": "Public Research University",
        "is_public": True, "website": "https://www.univ-amu.fr"
    },
    {
        "uni_id": "EU-FR-BORDEAUX", "dli": "ETER-FR-UBX", "name": "University of Bordeaux",
        "city": "Bordeaux", "state": "Nouvelle-Aquitaine", "country": "France", "type": "Public Research University",
        "is_public": True, "website": "https://www.u-bordeaux.fr"
    },
    {
        "uni_id": "EU-FR-MONTPELLIER", "dli": "ETER-FR-UMONT", "name": "University of Montpellier",
        "city": "Montpellier", "state": "Occitanie", "country": "France", "type": "Public Biology & Health Hub",
        "is_public": True, "website": "https://www.umontpellier.fr"
    },
    {
        "uni_id": "EU-FR-LYON1", "dli": "ETER-FR-LYON1", "name": "Claude Bernard University Lyon 1",
        "city": "Lyon", "state": "Auvergne-Rhône-Alpes", "country": "France", "type": "Public Science & Health University",
        "is_public": True, "website": "https://www.univ-lyon1.fr"
    },
    {
        "uni_id": "EU-FR-LYON3", "dli": "ETER-FR-LYON3", "name": "Jean Moulin University Lyon 3",
        "city": "Lyon", "state": "Auvergne-Rhône-Alpes", "country": "France", "type": "Public Humanities & Law University",
        "is_public": True, "website": "https://www.univ-lyon3.fr"
    },
    {
        "uni_id": "EU-FR-LILLE", "dli": "ETER-FR-LILLE", "name": "University of Lille",
        "city": "Lille", "state": "Hauts-de-France", "country": "France", "type": "Public Comprehensive University",
        "is_public": True, "website": "https://www.univ-lille.fr"
    },
    {
        "uni_id": "EU-FR-TOULOUSE1", "dli": "ETER-FR-TLS1", "name": "Toulouse 1 Capitole University",
        "city": "Toulouse", "state": "Occitanie", "country": "France", "type": "Public Economics & Law Hub",
        "is_public": True, "website": "https://www.ut-capitole.fr"
    },
    {
        "uni_id": "EU-FR-TOULOUSE3", "dli": "ETER-FR-TLS3", "name": "Paul Sabatier University (Toulouse 3)",
        "city": "Toulouse", "state": "Occitanie", "country": "France", "type": "Public Aerospace & Science Hub",
        "is_public": True, "website": "https://www.univ-tlse3.fr"
    },
    {
        "uni_id": "EU-FR-PONTS", "dli": "ETER-FR-ENPC", "name": "École des Ponts ParisTech",
        "city": "Champs-sur-Marne", "state": "Île-de-France", "country": "France", "type": "Public Civil & Transport Engineering Grande École",
        "is_public": True, "website": "https://ecoledesponts.fr"
    },
    {
        "uni_id": "EU-FR-TELECOM", "dli": "ETER-FR-TPARIS", "name": "Télécom Paris",
        "city": "Palaiseau", "state": "Île-de-France", "country": "France", "type": "Public Digital & Cyber Engineering Grande École",
        "is_public": True, "website": "https://www.telecom-paris.fr"
    },
    {
        "uni_id": "EU-FR-ISAE", "dli": "ETER-FR-SUPAERO", "name": "ISAE-SUPAERO",
        "city": "Toulouse", "state": "Occitanie", "country": "France", "type": "Public Premier Aerospace Engineering Institute",
        "is_public": True, "website": "https://www.isae-supaero.fr"
    },
    {
        "uni_id": "EU-FR-ESSEC", "dli": "ETER-FR-ESSEC", "name": "ESSEC Business School",
        "city": "Cergy", "state": "Île-de-France", "country": "France", "type": "Private Top European Business School",
        "is_public": False, "website": "https://www.essec.edu"
    },
    {
        "uni_id": "EU-FR-ESCP", "dli": "ETER-FR-ESCP", "name": "ESCP Business School",
        "city": "Paris", "state": "Île-de-France", "country": "France", "type": "Private Multi-Campus Pan-European Business School",
        "is_public": False, "website": "https://escp.eu"
    },
    {
        "uni_id": "EU-FR-EDHEC", "dli": "ETER-FR-EDHEC", "name": "EDHEC Business School",
        "city": "Lille", "state": "Hauts-de-France", "country": "France", "type": "Private Quantitative Finance & Management School",
        "is_public": False, "website": "https://www.edhec.edu"
    },
    {
        "uni_id": "EU-FR-EMLYON", "dli": "ETER-FR-EMLYON", "name": "emlyon business school",
        "city": "Lyon", "state": "Auvergne-Rhône-Alpes", "country": "France", "type": "Private Entrepreneurship & Management School",
        "is_public": False, "website": "https://em-lyon.com"
    },
    {
        "uni_id": "EU-FR-SKEMA", "dli": "ETER-FR-SKEMA", "name": "SKEMA Business School",
        "city": "Lille", "state": "Hauts-de-France", "country": "France", "type": "Private Global Business School",
        "is_public": False, "website": "https://www.skema.edu"
    },
    {
        "uni_id": "EU-FR-AUDENCIA", "dli": "ETER-FR-AUDEN", "name": "Audencia Business School",
        "city": "Nantes", "state": "Pays de la Loire", "country": "France", "type": "Private Business School",
        "is_public": False, "website": "https://www.audencia.com"
    },
    {
        "uni_id": "EU-FR-GEM", "dli": "ETER-FR-GEM", "name": "Grenoble École de Management",
        "city": "Grenoble", "state": "Auvergne-Rhône-Alpes", "country": "France", "type": "Private Innovation Management School",
        "is_public": False, "website": "https://www.grenoble-em.com"
    },
    {
        "uni_id": "EU-FR-RENNES", "dli": "ETER-FR-RSB", "name": "Rennes School of Business",
        "city": "Rennes", "state": "Brittany", "country": "France", "type": "Private International Business School",
        "is_public": False, "website": "https://www.rennes-sb.com"
    },

    # -------------------------------------------------------------------------
    # 6. ITALY (26 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-IT-POLIMI", "dli": "ETER-IT-POLIMI", "name": "Politecnico di Milano (PoliMi)",
        "city": "Milan", "state": "Lombardy", "country": "Italy", "type": "Public Architecture, Design & Tech Institute",
        "is_public": True, "website": "https://www.polimi.it"
    },
    {
        "uni_id": "EU-IT-BOLOGNA", "dli": "ETER-IT-UNIBO", "name": "University of Bologna",
        "city": "Bologna", "state": "Emilia-Romagna", "country": "Italy", "type": "Public Oldest World University",
        "is_public": True, "website": "https://www.unibo.it"
    },
    {
        "uni_id": "EU-IT-SAPIENZA", "dli": "ETER-IT-SAPI", "name": "Sapienza University of Rome",
        "city": "Rome", "state": "Lazio", "country": "Italy", "type": "Public Comprehensive University",
        "is_public": True, "website": "https://www.uniroma1.it"
    },
    {
        "uni_id": "EU-IT-BOCCONI", "dli": "ETER-IT-BOCC", "name": "Bocconi University",
        "city": "Milan", "state": "Lombardy", "country": "Italy", "type": "Private Leading Economics, Finance & Management University",
        "is_public": False, "website": "https://www.unibocconi.eu"
    },
    {
        "uni_id": "EU-IT-POLITO", "dli": "ETER-IT-POLITO", "name": "Politecnico di Torino (PoliTo)",
        "city": "Turin", "state": "Piedmont", "country": "Italy", "type": "Public Automotive & Engineering Hub",
        "is_public": True, "website": "https://www.polito.it"
    },
    {
        "uni_id": "EU-IT-STATALE", "dli": "ETER-IT-UNIMI", "name": "University of Milan (Statale)",
        "city": "Milan", "state": "Lombardy", "country": "Italy", "type": "Public Research & Medicine University",
        "is_public": True, "website": "https://www.unimi.it"
    },
    {
        "uni_id": "EU-IT-PADUA", "dli": "ETER-IT-UNIPD", "name": "University of Padua",
        "city": "Padua", "state": "Veneto", "country": "Italy", "type": "Public Historic Research University",
        "is_public": True, "website": "https://www.unipd.it"
    },
    {
        "uni_id": "EU-IT-FLORENCE", "dli": "ETER-IT-UNIFI", "name": "University of Florence",
        "city": "Florence", "state": "Tuscany", "country": "Italy", "type": "Public Architecture, Arts & Science Hub",
        "is_public": True, "website": "https://www.unifi.it"
    },
    {
        "uni_id": "EU-IT-PISA", "dli": "ETER-IT-UNIPI", "name": "University of Pisa",
        "city": "Pisa", "state": "Tuscany", "country": "Italy", "type": "Public Science & Computing Pioneer",
        "is_public": True, "website": "https://www.unipi.it"
    },
    {
        "uni_id": "EU-IT-TORVERGATA", "dli": "ETER-IT-ROMA2", "name": "University of Rome Tor Vergata",
        "city": "Rome", "state": "Lazio", "country": "Italy", "type": "Public English Medicine & Economics Hub",
        "is_public": True, "website": "https://web.uniroma2.it"
    },
    {
        "uni_id": "EU-IT-FEDERICO2", "dli": "ETER-IT-UNINA", "name": "University of Naples Federico II",
        "city": "Naples", "state": "Campania", "country": "Italy", "type": "Public Engineering & Medicine Hub",
        "is_public": True, "website": "https://www.unina.it"
    },
    {
        "uni_id": "EU-IT-TURIN", "dli": "ETER-IT-UNITO", "name": "University of Turin",
        "city": "Turin", "state": "Piedmont", "country": "Italy", "type": "Public Research University",
        "is_public": True, "website": "https://www.unito.it"
    },
    {
        "uni_id": "EU-IT-GENOA", "dli": "ETER-IT-UNIGE", "name": "University of Genoa",
        "city": "Genoa", "state": "Liguria", "country": "Italy", "type": "Public Maritime & Engineering Hub",
        "is_public": True, "website": "https://unige.it"
    },
    {
        "uni_id": "EU-IT-TRENTO", "dli": "ETER-IT-UNITN", "name": "University of Trento",
        "city": "Trento", "state": "Trentino-Alto Adige", "country": "Italy", "type": "Public High-Ranked Innovation University",
        "is_public": True, "website": "https://www.unitn.it"
    },
    {
        "uni_id": "EU-IT-SANRAFFAELE", "dli": "ETER-IT-UNISR", "name": "Vita-Salute San Raffaele University",
        "city": "Milan", "state": "Lombardy", "country": "Italy", "type": "Private Premier English Medicine & BioTech Hub",
        "is_public": False, "website": "https://www.unisr.it"
    },
    {
        "uni_id": "EU-IT-HUMANITAS", "dli": "ETER-IT-HUM", "name": "Humanitas University",
        "city": "Milan", "state": "Lombardy", "country": "Italy", "type": "Private Medical & Healthcare Sciences University",
        "is_public": False, "website": "https://www.hunimed.eu"
    },
    {
        "uni_id": "EU-IT-PAVIA", "dli": "ETER-IT-UNIPV", "name": "University of Pavia",
        "city": "Pavia", "state": "Lombardy", "country": "Italy", "type": "Public Historic Medicine & Engineering Hub",
        "is_public": True, "website": "https://web.unipv.it"
    },
    {
        "uni_id": "EU-IT-SIENA", "dli": "ETER-IT-UNISI", "name": "University of Siena",
        "city": "Siena", "state": "Tuscany", "country": "Italy", "type": "Public Pharmacy, BioTech & Economics University",
        "is_public": True, "website": "https://www.unisi.it"
    },
    {
        "uni_id": "EU-IT-CAFOSCARI", "dli": "ETER-IT-UNIVE", "name": "Ca' Foscari University of Venice",
        "city": "Venice", "state": "Veneto", "country": "Italy", "type": "Public Economics, Languages & Humanities Hub",
        "is_public": True, "website": "https://www.unive.it"
    },
    {
        "uni_id": "EU-IT-VERONA", "dli": "ETER-IT-UNIVR", "name": "University of Verona",
        "city": "Verona", "state": "Veneto", "country": "Italy", "type": "Public Life Sciences & Computing Hub",
        "is_public": True, "website": "https://www.univr.it"
    },
    {
        "uni_id": "EU-IT-TRIESTE", "dli": "ETER-IT-UNITS", "name": "University of Trieste",
        "city": "Trieste", "state": "Friuli Venezia Giulia", "country": "Italy", "type": "Public Physics & Marine Research Hub",
        "is_public": True, "website": "https://www.units.it"
    },
    {
        "uni_id": "EU-IT-BRESCIA", "dli": "ETER-IT-UNIBS", "name": "University of Brescia",
        "city": "Brescia", "state": "Lombardy", "country": "Italy", "type": "Public Engineering & Health Hub",
        "is_public": True, "website": "https://www.unibs.it"
    },
    {
        "uni_id": "EU-IT-UNIMORE", "dli": "ETER-IT-MORE", "name": "University of Modena and Reggio Emilia (UNIMORE)",
        "city": "Modena", "state": "Emilia-Romagna", "country": "Italy", "type": "Public Motorvehicle & Mechanics Hub",
        "is_public": True, "website": "https://www.unimore.it"
    },
    {
        "uni_id": "EU-IT-BARI", "dli": "ETER-IT-UNIBA", "name": "University of Bari Aldo Moro",
        "city": "Bari", "state": "Apulia", "country": "Italy", "type": "Public Comprehensive University",
        "is_public": True, "website": "https://www.uniba.it"
    },
    {
        "uni_id": "EU-IT-LUISS", "dli": "ETER-IT-LUISS", "name": "Luiss Guido Carli University",
        "city": "Rome", "state": "Lazio", "country": "Italy", "type": "Private Governance, Law & Economics School",
        "is_public": False, "website": "https://www.luiss.edu"
    },
    {
        "uni_id": "EU-IT-CATHOLIC", "dli": "ETER-IT-UCSC", "name": "Università Cattolica del Sacro Cuore",
        "city": "Milan", "state": "Lombardy", "country": "Italy", "type": "Private Medicine, Business & Humanities University",
        "is_public": False, "website": "https://www.unicatt.it"
    },

    # -------------------------------------------------------------------------
    # 7. SWITZERLAND (12 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-CH-ETHZ", "dli": "ETER-CH-ETHZ", "name": "ETH Zurich",
        "city": "Zurich", "state": "Zurich", "country": "Switzerland", "type": "Public Federal Institute of Technology",
        "is_public": True, "website": "https://ethz.ch"
    },
    {
        "uni_id": "EU-CH-EPFL", "dli": "ETER-CH-EPFL", "name": "EPFL (École Polytechnique Fédérale de Lausanne)",
        "city": "Lausanne", "state": "Vaud", "country": "Switzerland", "type": "Public Federal Institute of Technology",
        "is_public": True, "website": "https://www.epfl.ch"
    },
    {
        "uni_id": "EU-CH-UZH", "dli": "ETER-CH-UZH", "name": "University of Zurich (UZH)",
        "city": "Zurich", "state": "Zurich", "country": "Switzerland", "type": "Public Comprehensive Research University",
        "is_public": True, "website": "https://www.uzh.ch"
    },
    {
        "uni_id": "EU-CH-GENEVA", "dli": "ETER-CH-UNIGE", "name": "University of Geneva",
        "city": "Geneva", "state": "Geneva", "country": "Switzerland", "type": "Public International Relations & Science Hub",
        "is_public": True, "website": "https://www.unige.ch"
    },
    {
        "uni_id": "EU-CH-BASEL", "dli": "ETER-CH-UNIBAS", "name": "University of Basel",
        "city": "Basel", "state": "Basel-Stadt", "country": "Switzerland", "type": "Public Pharma & Life Sciences Hub",
        "is_public": True, "website": "https://www.unibas.ch"
    },
    {
        "uni_id": "EU-CH-BERN", "dli": "ETER-CH-UNIBE", "name": "University of Bern",
        "city": "Bern", "state": "Bern", "country": "Switzerland", "type": "Public Space & Climate Research University",
        "is_public": True, "website": "https://www.unibe.ch"
    },
    {
        "uni_id": "EU-CH-LAUSANNE", "dli": "ETER-CH-UNIL", "name": "University of Lausanne (UNIL)",
        "city": "Lausanne", "state": "Vaud", "country": "Switzerland", "type": "Public Geosciences & Medicine Hub",
        "is_public": True, "website": "https://www.unil.ch"
    },
    {
        "uni_id": "EU-CH-STGALLEN", "dli": "ETER-CH-HSG", "name": "University of St. Gallen (HSG)",
        "city": "St. Gallen", "state": "St. Gallen", "country": "Switzerland", "type": "Public Top Finance & Business University",
        "is_public": True, "website": "https://www.unisg.ch"
    },
    {
        "uni_id": "EU-CH-FRIBOURG", "dli": "ETER-CH-UNIFR", "name": "University of Fribourg",
        "city": "Fribourg", "state": "Fribourg", "country": "Switzerland", "type": "Public Bilingual Law & Science University",
        "is_public": True, "website": "https://www.unifr.ch"
    },
    {
        "uni_id": "EU-CH-USI", "dli": "ETER-CH-USI", "name": "Università della Svizzera italiana (USI)",
        "city": "Lugano", "state": "Ticino", "country": "Switzerland", "type": "Public Informatics & Architecture Hub",
        "is_public": True, "website": "https://www.usi.ch"
    },
    {
        "uni_id": "EU-CH-NEUCHATEL", "dli": "ETER-CH-UNINE", "name": "University of Neuchâtel",
        "city": "Neuchâtel", "state": "Neuchâtel", "country": "Switzerland", "type": "Public Microtechnology & Law Hub",
        "is_public": True, "website": "https://www.unine.ch"
    },
    {
        "uni_id": "EU-CH-IHEID", "dli": "ETER-CH-IHEID", "name": "Geneva Graduate Institute (IHEID)",
        "city": "Geneva", "state": "Geneva", "country": "Switzerland", "type": "Public International Affairs & Development Institute",
        "is_public": True, "website": "https://www.graduateinstitute.ch"
    },

    # -------------------------------------------------------------------------
    # 8. FINLAND (15 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-FI-AALTO", "dli": "ETER-FI-AALTO", "name": "Aalto University",
        "city": "Espoo", "state": "Uusimaa", "country": "Finland", "type": "Public Tech, Business & Design Flagship",
        "is_public": True, "website": "https://www.aalto.fi"
    },
    {
        "uni_id": "EU-FI-HELSINKI", "dli": "ETER-FI-HY", "name": "University of Helsinki",
        "city": "Helsinki", "state": "Uusimaa", "country": "Finland", "type": "Public Multidisciplinary Research University",
        "is_public": True, "website": "https://www.helsinki.fi"
    },
    {
        "uni_id": "EU-FI-TAMPERE", "dli": "ETER-FI-TAU", "name": "Tampere University",
        "city": "Tampere", "state": "Pirkanmaa", "country": "Finland", "type": "Public Technology & Health Hub",
        "is_public": True, "website": "https://www.tuni.fi"
    },
    {
        "uni_id": "EU-FI-OULU", "dli": "ETER-FI-OY", "name": "University of Oulu",
        "city": "Oulu", "state": "North Ostrobothnia", "country": "Finland", "type": "Public Wireless 6G & ICT Pioneer",
        "is_public": True, "website": "https://www.oulu.fi"
    },
    {
        "uni_id": "EU-FI-LUT", "dli": "ETER-FI-LUT", "name": "LUT University (Lappeenranta-Lahti)",
        "city": "Lappeenranta", "state": "South Karelia", "country": "Finland", "type": "Public Clean Energy & Circular Tech University",
        "is_public": True, "website": "https://www.lut.fi"
    },
    {
        "uni_id": "EU-FI-TURKU", "dli": "ETER-FI-UTU", "name": "University of Turku",
        "city": "Turku", "state": "Southwest Finland", "country": "Finland", "type": "Public Life Sciences & Marine Tech University",
        "is_public": True, "website": "https://www.utu.fi"
    },
    {
        "uni_id": "EU-FI-JYVASKYLA", "dli": "ETER-FI-JYU", "name": "University of Jyväskylä",
        "city": "Jyväskylä", "state": "Central Finland", "country": "Finland", "type": "Public Cybersecurity & Education Flagship",
        "is_public": True, "website": "https://www.jyu.fi"
    },
    {
        "uni_id": "EU-FI-UEF", "dli": "ETER-FI-UEF", "name": "University of Eastern Finland",
        "city": "Kuopio", "state": "North Savo", "country": "Finland", "type": "Public Forestry, Health & Photonics Hub",
        "is_public": True, "website": "https://www.uef.fi"
    },
    {
        "uni_id": "EU-FI-VAASA", "dli": "ETER-FI-UVAASA", "name": "University of Vaasa",
        "city": "Vaasa", "state": "Ostrobothnia", "country": "Finland", "type": "Public Energy Business & Tech University",
        "is_public": True, "website": "https://www.univaasa.fi"
    },
    {
        "uni_id": "EU-FI-ABO", "dli": "ETER-FI-ABO", "name": "Åbo Akademi University",
        "city": "Turku", "state": "Southwest Finland", "country": "Finland", "type": "Public Chemical Engineering & Biosciences Hub",
        "is_public": True, "website": "https://www.abo.fi"
    },
    {
        "uni_id": "EU-FI-HANKEN", "dli": "ETER-FI-HANKEN", "name": "Hanken School of Economics",
        "city": "Helsinki", "state": "Uusimaa", "country": "Finland", "type": "Public Triple-Crown Business School",
        "is_public": True, "website": "https://www.hanken.fi"
    },
    {
        "uni_id": "EU-FI-METROPOLIA", "dli": "ETER-FI-METRO", "name": "Metropolia University of Applied Sciences",
        "city": "Helsinki", "state": "Uusimaa", "country": "Finland", "type": "Public Largest UAS in Finland",
        "is_public": True, "website": "https://www.metropolia.fi"
    },
    {
        "uni_id": "EU-FI-HAAGAHELIA", "dli": "ETER-FI-HAAGA", "name": "Haaga-Helia University of Applied Sciences",
        "city": "Helsinki", "state": "Uusimaa", "country": "Finland", "type": "Public Business & Hospitality UAS",
        "is_public": True, "website": "https://www.haaga-helia.fi"
    },
    {
        "uni_id": "EU-FI-LAUREA", "dli": "ETER-FI-LAUREA", "name": "Laurea University of Applied Sciences",
        "city": "Vantaa", "state": "Uusimaa", "country": "Finland", "type": "Public Service Innovation & Safety UAS",
        "is_public": True, "website": "https://www.laurea.fi"
    },
    {
        "uni_id": "EU-FI-TAMK", "dli": "ETER-FI-TAMK", "name": "Tampere University of Applied Sciences (TAMK)",
        "city": "Tampere", "state": "Pirkanmaa", "country": "Finland", "type": "Public Applied Engineering UAS",
        "is_public": True, "website": "https://www.tuni.fi/tamk"
    },

    # -------------------------------------------------------------------------
    # 9. NORWAY (12 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-NO-UIO", "dli": "ETER-NO-UIO", "name": "University of Oslo (UiO)",
        "city": "Oslo", "state": "Oslo", "country": "Norway", "type": "Public Flagship Research University",
        "is_public": True, "website": "https://www.uio.no"
    },
    {
        "uni_id": "EU-NO-NTNU", "dli": "ETER-NO-NTNU", "name": "Norwegian University of Science and Technology (NTNU)",
        "city": "Trondheim", "state": "Trøndelag", "country": "Norway", "type": "Public Primary Technical University",
        "is_public": True, "website": "https://www.ntnu.edu"
    },
    {
        "uni_id": "EU-NO-UIB", "dli": "ETER-NO-UIB", "name": "University of Bergen (UiB)",
        "city": "Bergen", "state": "Vestland", "country": "Norway", "type": "Public Marine & Climate Research Hub",
        "is_public": True, "website": "https://www.uib.no"
    },
    {
        "uni_id": "EU-NO-UIT", "dli": "ETER-NO-UIT", "name": "UiT The Arctic University of Norway",
        "city": "Tromsø", "state": "Troms og Finnmark", "country": "Norway", "type": "Public Northernmost Arctic University",
        "is_public": True, "website": "https://uit.no"
    },
    {
        "uni_id": "EU-NO-UIS", "dli": "ETER-NO-UIS", "name": "University of Stavanger (UiS)",
        "city": "Stavanger", "state": "Rogaland", "country": "Norway", "type": "Public Energy & Offshore Technology Hub",
        "is_public": True, "website": "https://www.uis.no"
    },
    {
        "uni_id": "EU-NO-NMBU", "dli": "ETER-NO-NMBU", "name": "Norwegian University of Life Sciences (NMBU)",
        "city": "Ås", "state": "Viken", "country": "Norway", "type": "Public Sustainability & BioSciences University",
        "is_public": True, "website": "https://www.nmbu.no"
    },
    {
        "uni_id": "EU-NO-UIA", "dli": "ETER-NO-UIA", "name": "University of Agder (UiA)",
        "city": "Kristiansand", "state": "Agder", "country": "Norway", "type": "Public Artificial Intelligence & Mechatronics Hub",
        "is_public": True, "website": "https://www.uia.no"
    },
    {
        "uni_id": "EU-NO-BI", "dli": "ETER-NO-BI", "name": "BI Norwegian Business School",
        "city": "Oslo", "state": "Oslo", "country": "Norway", "type": "Private Triple-Accredited Business School",
        "is_public": False, "website": "https://www.bi.edu"
    },
    {
        "uni_id": "EU-NO-NHH", "dli": "ETER-NO-NHH", "name": "NHH Norwegian School of Economics",
        "city": "Bergen", "state": "Vestland", "country": "Norway", "type": "Public Leading Economics & Business School",
        "is_public": True, "website": "https://www.nhh.no"
    },
    {
        "uni_id": "EU-NO-OSLOMET", "dli": "ETER-NO-OMET", "name": "Oslo Metropolitan University (OsloMet)",
        "city": "Oslo", "state": "Oslo", "country": "Norway", "type": "Public Urban Applied Sciences University",
        "is_public": True, "website": "https://www.oslomet.no"
    },
    {
        "uni_id": "EU-NO-HVL", "dli": "ETER-NO-HVL", "name": "Western Norway University of Applied Sciences (HVL)",
        "city": "Bergen", "state": "Vestland", "country": "Norway", "type": "Public Maritime & Engineering Institute",
        "is_public": True, "website": "https://www.hvl.no"
    },
    {
        "uni_id": "EU-NO-NORD", "dli": "ETER-NO-NORD", "name": "Nord University",
        "city": "Bodø", "state": "Nordland", "country": "Norway", "type": "Public Aquaculture & Coastal Ecology Hub",
        "is_public": True, "website": "https://www.nord.no"
    },

    # -------------------------------------------------------------------------
    # 10. DENMARK (10 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-DK-DTU", "dli": "ETER-DK-DTU", "name": "Technical University of Denmark (DTU)",
        "city": "Kongens Lyngby", "state": "Capital Region", "country": "Denmark", "type": "Public Elite Engineering & Tech University",
        "is_public": True, "website": "https://www.dtu.dk"
    },
    {
        "uni_id": "EU-DK-KU", "dli": "ETER-DK-KU", "name": "University of Copenhagen (UCPH)",
        "city": "Copenhagen", "state": "Capital Region", "country": "Denmark", "type": "Public Research Flagship",
        "is_public": True, "website": "https://www.ku.dk"
    },
    {
        "uni_id": "EU-DK-CBS", "dli": "ETER-DK-CBS", "name": "Copenhagen Business School (CBS)",
        "city": "Frederiksberg", "state": "Capital Region", "country": "Denmark", "type": "Public International Business Hub",
        "is_public": True, "website": "https://www.cbs.dk"
    },
    {
        "uni_id": "EU-DK-AARHUS", "dli": "ETER-DK-AU", "name": "Aarhus University",
        "city": "Aarhus", "state": "Central Denmark", "country": "Denmark", "type": "Public Top Comprehensive University",
        "is_public": True, "website": "https://international.au.dk"
    },
    {
        "uni_id": "EU-DK-AALBORG", "dli": "ETER-DK-AAU", "name": "Aalborg University (AAU)",
        "city": "Aalborg", "state": "North Denmark", "country": "Denmark", "type": "Public Problem-Based Engineering Pioneer",
        "is_public": True, "website": "https://www.en.aau.dk"
    },
    {
        "uni_id": "EU-DK-SDU", "dli": "ETER-DK-SDU", "name": "University of Southern Denmark (SDU)",
        "city": "Odense", "state": "Region of Southern Denmark", "country": "Denmark", "type": "Public Robotics & Drones Pioneer",
        "is_public": True, "website": "https://www.sdu.dk"
    },
    {
        "uni_id": "EU-DK-ROSKILDE", "dli": "ETER-DK-RUC", "name": "Roskilde University (RUC)",
        "city": "Roskilde", "state": "Region Zealand", "country": "Denmark", "type": "Public Interdisciplinary Project-Based University",
        "is_public": True, "website": "https://ruc.dk"
    },
    {
        "uni_id": "EU-DK-ITU", "dli": "ETER-DK-ITU", "name": "IT University of Copenhagen (ITU)",
        "city": "Copenhagen", "state": "Capital Region", "country": "Denmark", "type": "Public Specialized Computing University",
        "is_public": True, "website": "https://en.itu.dk"
    },
    {
        "uni_id": "EU-DK-VIA", "dli": "ETER-DK-VIA", "name": "VIA University College",
        "city": "Aarhus", "state": "Central Denmark", "country": "Denmark", "type": "Public Applied Sciences College",
        "is_public": True, "website": "https://en.via.dk"
    },
    {
        "uni_id": "EU-DK-KEA", "dli": "ETER-DK-KEA", "name": "Copenhagen School of Design and Technology (KEA)",
        "city": "Copenhagen", "state": "Capital Region", "country": "Denmark", "type": "Public Academy of Higher Education",
        "is_public": True, "website": "https://kea.dk"
    },

    # -------------------------------------------------------------------------
    # 11. POLAND (25 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-PL-UW", "dli": "ETER-PL-UW", "name": "University of Warsaw",
        "city": "Warsaw", "state": "Masovian", "country": "Poland", "type": "Public Leading National University",
        "is_public": True, "website": "https://en.uw.edu.pl"
    },
    {
        "uni_id": "EU-PL-UJ", "dli": "ETER-PL-UJ", "name": "Jagiellonian University",
        "city": "Krakow", "state": "Lesser Poland", "country": "Poland", "type": "Public Historic Research University",
        "is_public": True, "website": "https://en.uj.edu.pl"
    },
    {
        "uni_id": "EU-PL-WUT", "dli": "ETER-PL-PW", "name": "Warsaw University of Technology (WUT)",
        "city": "Warsaw", "state": "Masovian", "country": "Poland", "type": "Public Premier Technical University",
        "is_public": True, "website": "https://www.pw.edu.pl"
    },
    {
        "uni_id": "EU-PL-MUW", "dli": "ETER-PL-WUM", "name": "Medical University of Warsaw (MUW)",
        "city": "Warsaw", "state": "Masovian", "country": "Poland", "type": "Public Elite English MD & Dentistry Hub",
        "is_public": True, "website": "https://www.wum.edu.pl"
    },
    {
        "uni_id": "EU-PL-PUMS", "dli": "ETER-PL-PUMS", "name": "Poznan University of Medical Sciences",
        "city": "Poznan", "state": "Greater Poland", "country": "Poland", "type": "Public Renowned English Medical University",
        "is_public": True, "website": "https://pums.ump.edu.pl"
    },
    {
        "uni_id": "EU-PL-UJMC", "dli": "ETER-PL-UJMC", "name": "Jagiellonian University Medical College",
        "city": "Krakow", "state": "Lesser Poland", "country": "Poland", "type": "Public Premier Medical College",
        "is_public": True, "website": "https://medschool.uj.edu.pl"
    },
    {
        "uni_id": "EU-PL-WROC-MED", "dli": "ETER-PL-UMED-WR", "name": "Wroclaw Medical University",
        "city": "Wroclaw", "state": "Lower Silesia", "country": "Poland", "type": "Public English Medicine Faculty",
        "is_public": True, "website": "https://www.umw.edu.pl"
    },
    {
        "uni_id": "EU-PL-MUG", "dli": "ETER-PL-GUMED", "name": "Medical University of Gdansk (MUG)",
        "city": "Gdansk", "state": "Pomeranian", "country": "Poland", "type": "Public English Medical University",
        "is_public": True, "website": "https://mug.edu.pl"
    },
    {
        "uni_id": "EU-PL-LODZ-MED", "dli": "ETER-PL-UMED-LDZ", "name": "Medical University of Lodz",
        "city": "Lodz", "state": "Lodz", "country": "Poland", "type": "Public International Medical Studies Hub",
        "is_public": True, "website": "https://umed.pl"
    },
    {
        "uni_id": "EU-PL-AGH", "dli": "ETER-PL-AGH", "name": "AGH University of Krakow",
        "city": "Krakow", "state": "Lesser Poland", "country": "Poland", "type": "Public Tech & Energy Flagship",
        "is_public": True, "website": "https://www.agh.edu.pl"
    },
    {
        "uni_id": "EU-PL-WUST", "dli": "ETER-PL-PWR", "name": "Wroclaw University of Science and Technology (WUST)",
        "city": "Wroclaw", "state": "Lower Silesia", "country": "Poland", "type": "Public Technical Research University",
        "is_public": True, "website": "https://pwr.edu.pl"
    },
    {
        "uni_id": "EU-PL-GUT", "dli": "ETER-PL-PG", "name": "Gdansk University of Technology",
        "city": "Gdansk", "state": "Pomeranian", "country": "Poland", "type": "Public Technical University",
        "is_public": True, "website": "https://pg.edu.pl"
    },
    {
        "uni_id": "EU-PL-PUT", "dli": "ETER-PL-PP", "name": "Poznan University of Technology (PUT)",
        "city": "Poznan", "state": "Greater Poland", "country": "Poland", "type": "Public Technical University",
        "is_public": True, "website": "https://www.put.poznan.pl"
    },
    {
        "uni_id": "EU-PL-SUT", "dli": "ETER-PL-POLSL", "name": "Silesian University of Technology",
        "city": "Gliwice", "state": "Silesian", "country": "Poland", "type": "Public Engineering Center",
        "is_public": True, "website": "https://www.polsl.pl"
    },
    {
        "uni_id": "EU-PL-TUL", "dli": "ETER-PL-PLODZ", "name": "Lodz University of Technology",
        "city": "Lodz", "state": "Lodz", "country": "Poland", "type": "Public Technical University",
        "is_public": True, "website": "https://p.lodz.pl"
    },
    {
        "uni_id": "EU-PL-SGH", "dli": "ETER-PL-SGH", "name": "SGH Warsaw School of Economics",
        "city": "Warsaw", "state": "Masovian", "country": "Poland", "type": "Public Oldest Business University in Poland",
        "is_public": True, "website": "https://www.sgh.waw.pl"
    },
    {
        "uni_id": "EU-PL-KOZMINSKI", "dli": "ETER-PL-ALK", "name": "Kozminski University",
        "city": "Warsaw", "state": "Masovian", "country": "Poland", "type": "Private Triple-Accredited Business School",
        "is_public": False, "website": "https://www.kozminski.edu.pl"
    },
    {
        "uni_id": "EU-PL-UWR", "dli": "ETER-PL-UWR", "name": "University of Wroclaw",
        "city": "Wroclaw", "state": "Lower Silesia", "country": "Poland", "type": "Public Research University",
        "is_public": True, "website": "https://uwr.edu.pl"
    },
    {
        "uni_id": "EU-PL-UAM", "dli": "ETER-PL-UAM", "name": "Adam Mickiewicz University Poznan",
        "city": "Poznan", "state": "Greater Poland", "country": "Poland", "type": "Public Comprehensive University",
        "is_public": True, "website": "https://amu.edu.pl"
    },
    {
        "uni_id": "EU-PL-NCU", "dli": "ETER-PL-UMK", "name": "Nicolaus Copernicus University",
        "city": "Torun", "state": "Kuyavian-Pomeranian", "country": "Poland", "type": "Public Astronomy & Medicine University",
        "is_public": True, "website": "https://www.umk.pl"
    },
    {
        "uni_id": "EU-PL-UG", "dli": "ETER-PL-UG", "name": "University of Gdansk",
        "city": "Gdansk", "state": "Pomeranian", "country": "Poland", "type": "Public Maritime & Social Sciences University",
        "is_public": True, "website": "https://ug.edu.pl"
    },
    {
        "uni_id": "EU-PL-CUE", "dli": "ETER-PL-UEK", "name": "Cracow University of Economics",
        "city": "Krakow", "state": "Lesser Poland", "country": "Poland", "type": "Public Economics University",
        "is_public": True, "website": "https://uek.krakow.pl"
    },
    {
        "uni_id": "EU-PL-LUT", "dli": "ETER-PL-POLLUB", "name": "Lublin University of Technology",
        "city": "Lublin", "state": "Lublin", "country": "Poland", "type": "Public Technical University",
        "is_public": True, "website": "https://pollub.pl"
    },
    {
        "uni_id": "EU-PL-LUBLIN-MED", "dli": "ETER-PL-UMLUB", "name": "Medical University of Lublin",
        "city": "Lublin", "state": "Lublin", "country": "Poland", "type": "Public English Medicine Program",
        "is_public": True, "website": "https://umlub.pl"
    },
    {
        "uni_id": "EU-PL-PUM", "dli": "ETER-PL-PUM", "name": "Pomeranian Medical University in Szczecin",
        "city": "Szczecin", "state": "West Pomeranian", "country": "Poland", "type": "Public English MD & Dentistry Center",
        "is_public": True, "website": "https://www.pum.edu.pl"
    },

    # -------------------------------------------------------------------------
    # 12. AUSTRIA (16 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-AT-UNIVIE", "dli": "ETER-AT-UNIVIE", "name": "University of Vienna",
        "city": "Vienna", "state": "Vienna", "country": "Austria", "type": "Public Flagship Comprehensive University",
        "is_public": True, "website": "https://www.univie.ac.at"
    },
    {
        "uni_id": "EU-AT-TUWIEN", "dli": "ETER-AT-TUW", "name": "TU Wien (Vienna University of Technology)",
        "city": "Vienna", "state": "Vienna", "country": "Austria", "type": "Public Premier Technical University",
        "is_public": True, "website": "https://www.tuwien.at"
    },
    {
        "uni_id": "EU-AT-WUVIENNA", "dli": "ETER-AT-WU", "name": "WU Vienna (Vienna University of Economics and Business)",
        "city": "Vienna", "state": "Vienna", "country": "Austria", "type": "Public Triple-Accredited Business University",
        "is_public": True, "website": "https://www.wu.ac.at"
    },
    {
        "uni_id": "EU-AT-MEDUNIVIE", "dli": "ETER-AT-MUW", "name": "Medical University of Vienna",
        "city": "Vienna", "state": "Vienna", "country": "Austria", "type": "Public Medical Research University",
        "is_public": True, "website": "https://www.meduniwien.ac.at"
    },
    {
        "uni_id": "EU-AT-INNSBRUCK", "dli": "ETER-AT-LFUI", "name": "University of Innsbruck",
        "city": "Innsbruck", "state": "Tyrol", "country": "Austria", "type": "Public Alpine Research University",
        "is_public": True, "website": "https://www.uibk.ac.at"
    },
    {
        "uni_id": "EU-AT-TUGRAZ", "dli": "ETER-AT-TUG", "name": "Graz University of Technology (TU Graz)",
        "city": "Graz", "state": "Styria", "country": "Austria", "type": "Public Technical University",
        "is_public": True, "website": "https://www.tugraz.at"
    },
    {
        "uni_id": "EU-AT-GRAZ", "dli": "ETER-AT-KFU", "name": "University of Graz",
        "city": "Graz", "state": "Styria", "country": "Austria", "type": "Public Comprehensive University",
        "is_public": True, "website": "https://www.uni-graz.at"
    },
    {
        "uni_id": "EU-AT-JKU", "dli": "ETER-AT-JKU", "name": "Johannes Kepler University Linz (JKU Linz)",
        "city": "Linz", "state": "Upper Austria", "country": "Austria", "type": "Public AI, Tech & Law Hub",
        "is_public": True, "website": "https://www.jku.at"
    },
    {
        "uni_id": "EU-AT-SALZBURG", "dli": "ETER-AT-PLUS", "name": "University of Salzburg",
        "city": "Salzburg", "state": "Salzburg", "country": "Austria", "type": "Public Science & Humanities University",
        "is_public": True, "website": "https://www.plus.ac.at"
    },
    {
        "uni_id": "EU-AT-BOKU", "dli": "ETER-AT-BOKU", "name": "University of Natural Resources and Life Sciences (BOKU)",
        "city": "Vienna", "state": "Vienna", "country": "Austria", "type": "Public Bioeconomy & Renewable Energy Hub",
        "is_public": True, "website": "https://boku.ac.at"
    },
    {
        "uni_id": "EU-AT-MEDGRAZ", "dli": "ETER-AT-MUG", "name": "Medical University of Graz",
        "city": "Graz", "state": "Styria", "country": "Austria", "type": "Public Medical Research University",
        "is_public": True, "website": "https://www.medunigraz.at"
    },
    {
        "uni_id": "EU-AT-MEDINNS", "dli": "ETER-AT-MUI", "name": "Medical University of Innsbruck",
        "city": "Innsbruck", "state": "Tyrol", "country": "Austria", "type": "Public Medical University",
        "is_public": True, "website": "https://www.i-med.ac.at"
    },
    {
        "uni_id": "EU-AT-KLAGENFURT", "dli": "ETER-AT-AAU", "name": "University of Klagenfurt",
        "city": "Klagenfurt", "state": "Carinthia", "country": "Austria", "type": "Public Informatics & Cybernetics Hub",
        "is_public": True, "website": "https://www.aau.at"
    },
    {
        "uni_id": "EU-AT-LEOBEN", "dli": "ETER-AT-MUL", "name": "Montanuniversität Leoben",
        "city": "Leoben", "state": "Styria", "country": "Austria", "type": "Public Mining, Metallurgy & Materials Tech University",
        "is_public": True, "website": "https://www.unileoben.ac.at"
    },
    {
        "uni_id": "EU-AT-CEU", "dli": "ETER-AT-CEU", "name": "Central European University (CEU)",
        "city": "Vienna", "state": "Vienna", "country": "Austria", "type": "Private International Social Sciences & Law Hub",
        "is_public": False, "website": "https://www.ceu.edu"
    },
    {
        "uni_id": "EU-AT-MODUL", "dli": "ETER-AT-MODUL", "name": "Modul University Vienna",
        "city": "Vienna", "state": "Vienna", "country": "Austria", "type": "Private International Tourism & Management School",
        "is_public": False, "website": "https://www.modul.ac.at"
    },

    # -------------------------------------------------------------------------
    # 13. BELGIUM (16 Institutions)
    # -------------------------------------------------------------------------
    {
        "uni_id": "EU-BE-KULEUVEN", "dli": "ETER-BE-KUL", "name": "KU Leuven",
        "city": "Leuven", "state": "Flanders", "country": "Belgium", "type": "Public Europe's Most Innovative University",
        "is_public": True, "website": "https://www.kuleuven.be"
    },
    {
        "uni_id": "EU-BE-GHENT", "dli": "ETER-BE-UGENT", "name": "Ghent University",
        "city": "Ghent", "state": "Flanders", "country": "Belgium", "type": "Public Top Research University",
        "is_public": True, "website": "https://www.ugent.be"
    },
    {
        "uni_id": "EU-BE-ULB", "dli": "ETER-BE-ULB", "name": "Université libre de Bruxelles (ULB)",
        "city": "Brussels", "state": "Brussels", "country": "Belgium", "type": "Public European Capital Flagship",
        "is_public": True, "website": "https://www.ulb.be"
    },
    {
        "uni_id": "EU-BE-VUB", "dli": "ETER-BE-VUB", "name": "Vrije Universiteit Brussel (VUB)",
        "city": "Brussels", "state": "Brussels", "country": "Belgium", "type": "Public International Urban University",
        "is_public": True, "website": "https://www.vub.be"
    },
    {
        "uni_id": "EU-BE-ANTWERP", "dli": "ETER-BE-UANT", "name": "University of Antwerp",
        "city": "Antwerp", "state": "Flanders", "country": "Belgium", "type": "Public Research & Global Supply Chain Hub",
        "is_public": True, "website": "https://www.uantwerpen.be"
    },
    {
        "uni_id": "EU-BE-UCLOUVAIN", "dli": "ETER-BE-UCL", "name": "UCLouvain",
        "city": "Louvain-la-Neuve", "state": "Wallonia", "country": "Belgium", "type": "Public Research University",
        "is_public": True, "website": "https://uclouvain.be"
    },
    {
        "uni_id": "EU-BE-LIEGE", "dli": "ETER-BE-ULIEGE", "name": "University of Liège",
        "city": "Liège", "state": "Wallonia", "country": "Belgium", "type": "Public Space & Engineering University",
        "is_public": True, "website": "https://www.uliege.be"
    },
    {
        "uni_id": "EU-BE-HASSELT", "dli": "ETER-BE-UHAS", "name": "Hasselt University",
        "city": "Hasselt", "state": "Flanders", "country": "Belgium", "type": "Public Innovation & Data Science Hub",
        "is_public": True, "website": "https://www.uhasselt.be"
    },
    {
        "uni_id": "EU-BE-MONS", "dli": "ETER-BE-UMONS", "name": "University of Mons",
        "city": "Mons", "state": "Wallonia", "country": "Belgium", "type": "Public Materials & Tech University",
        "is_public": True, "website": "https://web.umons.ac.be"
    },
    {
        "uni_id": "EU-BE-NAMUR", "dli": "ETER-BE-UNAMUR", "name": "University of Namur",
        "city": "Namur", "state": "Wallonia", "country": "Belgium", "type": "Public Computer Science & BioSciences Hub",
        "is_public": True, "website": "https://www.unamur.be"
    },
    {
        "uni_id": "EU-BE-AMS", "dli": "ETER-BE-AMS", "name": "Antwerp Management School",
        "city": "Antwerp", "state": "Flanders", "country": "Belgium", "type": "Private Top Business School",
        "is_public": False, "website": "https://www.antwerpmanagementschool.com"
    },
    {
        "uni_id": "EU-BE-VLERICK", "dli": "ETER-BE-VLERICK", "name": "Vlerick Business School",
        "city": "Ghent", "state": "Flanders", "country": "Belgium", "type": "Private Triple-Accredited Business School",
        "is_public": False, "website": "https://www.vlerick.com"
    },
    {
        "uni_id": "EU-BE-SOLVAY", "dli": "ETER-BE-SOLVAY", "name": "Solvay Brussels School of Economics and Management",
        "city": "Brussels", "state": "Brussels", "country": "Belgium", "type": "Public Leading Economics & Finance School",
        "is_public": True, "website": "https://sbsem.ulb.be"
    },
    {
        "uni_id": "EU-BE-ARTEVELDE", "dli": "ETER-BE-ARTE", "name": "Artevelde University of Applied Sciences",
        "city": "Ghent", "state": "Flanders", "country": "Belgium", "type": "Public University of Applied Sciences",
        "is_public": True, "website": "https://www.artevelde-uas.be"
    },
    {
        "uni_id": "EU-BE-THOMASMORE", "dli": "ETER-BE-TMORE", "name": "Thomas More University of Applied Sciences",
        "city": "Mechelen", "state": "Flanders", "country": "Belgium", "type": "Public Applied Engineering & Media Hub",
        "is_public": True, "website": "https://www.thomasmore.be"
    },
    {
        "uni_id": "EU-BE-KDG", "dli": "ETER-BE-KDG", "name": "Karel de Grote University of Applied Sciences",
        "city": "Antwerp", "state": "Flanders", "country": "Belgium", "type": "Public Tech & Applied Sciences College",
        "is_public": True, "website": "https://www.kdg.be"
    },
]


async def upsert_european_institutions(records: list[dict[str, Any]]) -> int:
    """Upsert European institutions into PostgreSQL `institutions` table."""
    engine = get_engine()
    written = 0
    async with engine.begin() as connection:
        for start in range(0, len(records), CHUNK):
            batch = records[start : start + CHUNK]
            inst_records = [
                {
                    "dli_number": r["dli"],
                    "institution_name": r["name"],
                    "province": r["state"],
                    "campus_location": "Main Campus",
                    "city": r["city"],
                    "offers_pgwp": True,
                    "is_public": r["is_public"],
                    "country": r["country"],
                    "website": r["website"],
                }
                for r in batch
            ]
            statement = insert(Institution).values(inst_records)
            statement = statement.on_conflict_do_update(
                index_elements=["dli_number", "campus_location", "city"],
                set_={
                    "institution_name": statement.excluded.institution_name,
                    "province": statement.excluded.province,
                    "offers_pgwp": statement.excluded.offers_pgwp,
                    "is_public": statement.excluded.is_public,
                    "country": statement.excluded.country,
                    "website": statement.excluded.website,
                },
            )
            await connection.execute(statement)
            written += len(batch)
    return written


async def upsert_european_universities(records: list[dict[str, Any]]) -> int:
    """Upsert providers into `universities` table for Course FK linkage."""
    engine = get_engine()
    written = 0
    async with engine.begin() as connection:
        for start in range(0, len(records), CHUNK):
            batch = records[start : start + CHUNK]
            uni_records = [
                {
                    "university_id": r["uni_id"][:20],
                    "institution_name": r["name"][:300],
                    "city": r["city"][:120],
                    "state": r["state"][:20],
                    "country": r["country"],
                    "institution_type": r["type"][:100],
                    "offers_pgwp": True,
                    "dli_number": r["dli"],
                    "website": r["website"],
                    "trading_name": None,
                    "institution_capacity": None,
                    "postcode": None,
                }
                for r in batch
            ]
            statement = insert(University).values(uni_records)
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
                    "website": statement.excluded.website,
                },
            )
            await connection.execute(statement)
            written += len(batch)
    return written


def print_summary(records: list[dict[str, Any]]) -> None:
    total = len(records)
    by_country = Counter(r["country"] for r in records)
    pub_count = sum(1 for r in records if r["is_public"])
    priv_count = total - pub_count

    print("\n" + "=" * 65)
    print(" EUROPEAN HIGHER EDUCATION INSTITUTIONS (ETER/DAAD) SUMMARY")
    print("=" * 65)
    print(f"Total Accredited Institutions: {total:,}")
    print(f"Public Universities:           {pub_count:,} ({pub_count / total * 100:.1f}%)")
    print(f"Private Elite / Business:      {priv_count:,} ({priv_count / total * 100:.1f}%)")
    print("\nInstitutions by Country (13 European Nations):")
    print(f"  {'Country':<20} {'Institutions':<14} {'Share':<10}")
    print("  " + "-" * 44)
    for country, count in sorted(by_country.items(), key=lambda x: x[1], reverse=True):
        print(f"  {country:<20} {count:>8,}       {count / total * 100:5.1f}%")
    print("=" * 65 + "\n")


async def run(dry_run: bool = False) -> int:
    await init_schema()
    print_summary(EUROPE_INSTITUTIONS_DATA)

    if dry_run:
        print("[DRY-RUN] No database writes performed.")
        return 0

    print("Upserting European institutions into 'institutions' table...")
    inst_count = await upsert_european_institutions(EUROPE_INSTITUTIONS_DATA)
    print(f"Successfully upserted {inst_count:,} institutions.")

    print("Upserting European providers into 'universities' table...")
    uni_count = await upsert_european_universities(EUROPE_INSTITUTIONS_DATA)
    print(f"Successfully upserted {uni_count:,} universities.")

    await dispose_engine()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest 260 European universities across 13 countries.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without writing to DB")
    args = parser.parse_args()
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
