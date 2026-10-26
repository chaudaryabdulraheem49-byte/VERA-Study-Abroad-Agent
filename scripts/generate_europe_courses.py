"""Generate full-scale Pan-European course catalog (1,600+ programs across 13 countries).

Connects to all 260 accredited European universities upserted from ETER / DAAD portals,
spanning all 6 key academic clusters:
1. Clinical Medicine, Surgery & Health (English MD 6-yr, Dentistry DDS, Nursing, MPH, BioTech)
2. Engineering & Computer Science (Automotive, AI/ML, Robotics, Cyber, Renewable, Aerospace)
3. Business, Management & Economics (MBA, MiM, FinTech, Supply Chain, International Business)
4. Natural & Physical Sciences (Quantum, Physics, Applied Maths, Material Science)
5. Design, Architecture & Arts (M.Arch, Product Design, Urban Planning, Interaction Design)
6. Law, Policy & Social Sciences (LL.M., EU Law, International Relations, Psychology)

Outputs:
  data/europe/seed_courses.json
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.ingest_europe_institutions import EUROPE_INSTITUTIONS_DATA

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("generate_europe_courses")

OUTPUT_DIR = REPO_ROOT / "data" / "europe"
OUTPUT_FILE = OUTPUT_DIR / "seed_courses.json"

# Master curriculum pool across 6 academic clusters
PROGRAM_CATALOG: dict[str, dict[str, Any]] = {
    # -------------------------------------------------------------------------
    # CLUSTER 1: CLINICAL MEDICINE, SURGERY & HEALTH
    # -------------------------------------------------------------------------
    "med_mbbs": {
        "title": "Doctor of Medicine (M.D. / MBBS Equivalent) - 6-Year English Program",
        "level": "Bachelors",
        "raw_level": "Doctor of Medicine (M.D. / Single-Cycle)",
        "duration": 312,
        "ielts": 7.0,
        "gpa": 70.0,
        "broad": "06 - Health",
        "narrow": "0601 - Medical Studies",
        "detailed": "060101 - General Medicine and Surgery",
        "syllabus": (
            "Comprehensive 6-year English-taught undergraduate medical degree (MD / MBBS equivalent, 360 ECTS). "
            "Covers preclinical anatomy, physiology, biochemistry, pathology, pharmacology, and medical microbiology, "
            "followed by extensive clinical rotations in internal medicine, surgery, pediatrics, obstetrics & gynecology, "
            "and emergency medicine in university teaching hospitals. Fully accredited under EU Directive 2005/36/EC, "
            "qualifying graduates for medical licensure across the European Union, UK (GMC), US (USMLE / ECFMG), "
            "and worldwide clinical practice."
        ),
        "bracket": "medicine",
    },
    "med_dentistry": {
        "title": "Doctor of Dental Surgery (DDS) - 5-Year English Program",
        "level": "Bachelors",
        "raw_level": "Doctor of Dental Surgery (DDS / Single-Cycle)",
        "duration": 260,
        "ielts": 7.0,
        "gpa": 70.0,
        "broad": "06 - Health",
        "narrow": "0607 - Dental Studies",
        "detailed": "060701 - Dentistry and Oral Surgery",
        "syllabus": (
            "Accredited 5-year English-taught dental medicine programme (300 ECTS). Provides rigorous simulation "
            "and phantom head laboratory training in conservative dentistry, prosthodontics, periodontics, "
            "endodontics, orthodontics, oral and maxillofacial surgery, and pediatric dentistry. Includes direct patient "
            "care clinical practice in university dental centers, compliant with European dental council directives."
        ),
        "bracket": "dentistry",
    },
    "med_biotech": {
        "title": "M.Sc. in Medical Biotechnology and Molecular Medicine",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "06 - Health",
        "narrow": "0601 - Medical Studies",
        "detailed": "060103 - Medical Biotechnology and Gene Therapy",
        "syllabus": (
            "English-taught 2-year Master of Science (120 ECTS) bridging biomedical laboratory research with translational "
            "clinical applications. Core modules cover gene editing (CRISPR/Cas9), viral vector design, recombinant protein therapeutics, "
            "precision oncology, stem cell biology, and clinical trial pharmacology. Prepares graduates for pharmaceutical R&D, "
            "biotech startups, and biomedical doctoral programmes."
        ),
        "bracket": "standard_masters",
    },
    "med_public_health": {
        "title": "Master of Public Health (MPH) - Global Epidemiology",
        "level": "Masters",
        "raw_level": "Master of Public Health (MPH)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "06 - Health",
        "narrow": "0613 - Public Health",
        "detailed": "061301 - Epidemiology and Biostatistics",
        "syllabus": (
            "Interdisciplinary English-taught Master of Public Health (120 ECTS) focusing on infectious disease epidemiology, "
            "biostatistical modeling (R/Python), health economics, international health policy, and environmental health surveillance. "
            "Graduates lead epidemiological monitoring and public health initiatives at the WHO, European Centre for Disease Prevention "
            "and Control (ECDC), NGOs, and governmental healthcare ministries."
        ),
        "bracket": "standard_masters",
    },
    "med_biomedical_sci": {
        "title": "B.Sc. in Biomedical Sciences and Pharmacology",
        "level": "Bachelors",
        "raw_level": "Bachelor of Science (B.Sc.)",
        "duration": 156,
        "ielts": 6.0,
        "gpa": 65.0,
        "broad": "06 - Health",
        "narrow": "0601 - Medical Studies",
        "detailed": "060105 - Biomedical Sciences",
        "syllabus": (
            "English-taught 3-year undergraduate degree (180 ECTS) providing foundational and advanced training in human physiology, "
            "molecular pharmacology, drug discovery mechanisms, immunology, and toxicology. Features heavy hands-on laboratory courses "
            "and an undergraduate capstone thesis project preparing for medical school entry or biotech careers."
        ),
        "bracket": "standard_bachelors",
    },
    "med_pharmacy": {
        "title": "M.Sc. in Clinical Research and Pharmacovigilance",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "06 - Health",
        "narrow": "0605 - Pharmacy",
        "detailed": "060501 - Clinical Pharmacy and Pharmacovigilance",
        "syllabus": (
            "Specialized English-taught master's degree (120 ECTS) concentrating on Good Clinical Practice (ICH-GCP), "
            "clinical trial phases I-IV management, regulatory affairs (EMA/FDA submission protocols), adverse drug event monitoring, "
            "and pharmacoepidemiology. High placement rate across European pharmaceutical and CRO giants."
        ),
        "bracket": "standard_masters",
    },

    # -------------------------------------------------------------------------
    # CLUSTER 2: ENGINEERING & COMPUTER SCIENCE
    # -------------------------------------------------------------------------
    "eng_automotive": {
        "title": "M.Sc. in Automotive Engineering and Mobility Systems",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "03 - Engineering and Related Technologies",
        "narrow": "0301 - Manufacturing Engineering and Technology",
        "detailed": "030103 - Automotive Engineering",
        "syllabus": (
            "Advanced English-taught Master of Science (120 ECTS) covering vehicle dynamics, electric powertrains, battery management "
            "systems (BMS), autonomous driving sensor fusion (LiDAR, radar, computer vision), and automotive chassis design. "
            "Includes industry collaborative project work with leading automotive OEMs and suppliers (BMW, Mercedes-Benz, Audi, Bosch, "
            "Stellantis, Volvo), qualifying engineers for international R&D roles."
        ),
        "bracket": "standard_masters",
    },
    "eng_ai_ml": {
        "title": "M.Sc. in Artificial Intelligence and Machine Learning",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "02 - Information Technology",
        "narrow": "0201 - Computer Science",
        "detailed": "020101 - Artificial Intelligence and Machine Learning",
        "syllabus": (
            "Elite English-taught Master of Science (120 ECTS) focusing on deep learning architectures, reinforcement learning, "
            "natural language processing (LLMs and transformers), probabilistic graphical models, and neural computer vision. "
            "Features GPU cluster computing labs, algorithmic optimization, and ethical AI deployment for careers as AI Research "
            "Scientists, Machine Learning Engineers, and Data Scientists."
        ),
        "bracket": "standard_masters",
    },
    "eng_data_science": {
        "title": "M.Sc. in Data Science and Advanced Analytics",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "02 - Information Technology",
        "narrow": "0201 - Computer Science",
        "detailed": "020105 - Data Science and Analytics",
        "syllabus": (
            "Top-tier English-taught Master of Science (120 ECTS) in data engineering, statistical inference, distributed computing (Spark), "
            "predictive analytics, time-series forecasting, and machine learning at scale. Graduates lead data science initiatives in "
            "tech giants, financial institutions, and research labs worldwide."
        ),
        "bracket": "standard_masters",
    },
    "eng_robotics": {
        "title": "M.Sc. in Robotics and Autonomous Intelligent Systems",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "03 - Engineering and Related Technologies",
        "narrow": "0307 - Industrial Engineering",
        "detailed": "030701 - Robotics and Mechatronics Engineering",
        "syllabus": (
            "Intensive English-taught Master of Science (120 ECTS) spanning robot kinematics, ROS2 framework, SLAM algorithms, "
            "motion planning, control theory, tactile robotic manipulation, and human-robot collaboration (Cobots). "
            "Includes practical lab work in state-of-the-art autonomous robotics facilities."
        ),
        "bracket": "standard_masters",
    },
    "eng_cybersecurity": {
        "title": "M.Sc. in Cybersecurity and Cloud Infrastructure",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "02 - Information Technology",
        "narrow": "0203 - Information Systems",
        "detailed": "020305 - Cybersecurity and Network Security",
        "syllabus": (
            "Applied English-taught Master of Science (120 ECTS) emphasizing applied cryptography, zero-trust cloud architectures, "
            "penetration testing and ethical hacking, reverse engineering, SOC incident response, and European GDPR/NIS2 compliance. "
            "Prepares security architects, threat intelligence analysts, and cloud security engineers."
        ),
        "bracket": "standard_masters",
    },
    "eng_renewable": {
        "title": "M.Sc. in Renewable Energy Engineering and Sustainable Systems",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "03 - Engineering and Related Technologies",
        "narrow": "0399 - Other Engineering",
        "detailed": "039901 - Renewable Energy Engineering",
        "syllabus": (
            "English-taught master's programme (120 ECTS) in renewable energy transition: photovoltaic solar energy, offshore wind "
            "turbine aerodynamics, green hydrogen electrolysis, smart electrical grids, and thermal energy storage systems. "
            "Strong alignment with European Green Deal industrial projects and net-zero engineering infrastructure."
        ),
        "bracket": "standard_masters",
    },
    "eng_aerospace": {
        "title": "M.Sc. in Aerospace Engineering and Satellite Systems",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "03 - Engineering and Related Technologies",
        "narrow": "0315 - Aerospace Engineering and Technology",
        "detailed": "031501 - Aerospace Engineering",
        "syllabus": (
            "English-taught Master of Science (120 ECTS) in aerospace engineering. Focuses on computational fluid dynamics (CFD), "
            "propulsion aerodynamics, orbital mechanics, CubeSat avionics, composite materials, and space mission design in partnership "
            "with the European Space Agency (ESA) and aerospace contractors (Airbus, ArianeGroup)."
        ),
        "bracket": "standard_masters",
    },
    "eng_bsc_cs": {
        "title": "B.Sc. in Computer Science and Software Systems",
        "level": "Bachelors",
        "raw_level": "Bachelor of Science (B.Sc.)",
        "duration": 156,
        "ielts": 6.0,
        "gpa": 65.0,
        "broad": "02 - Information Technology",
        "narrow": "0201 - Computer Science",
        "detailed": "020103 - Software Engineering",
        "syllabus": (
            "Foundational 3-year English-taught undergraduate degree (180 ECTS) covering object-oriented programming (C++, Java, Python), "
            "data structures and algorithms, operating systems, distributed database systems, web development, and software lifecycle. "
            "Includes an industrial team capstone project and prepares graduates for software engineering roles across Europe."
        ),
        "bracket": "standard_bachelors",
    },
    "eng_beng_mech": {
        "title": "B.Eng. in Mechanical Engineering and Digital Manufacturing",
        "level": "Bachelors",
        "raw_level": "Bachelor of Engineering (B.Eng.)",
        "duration": 156,
        "ielts": 6.0,
        "gpa": 65.0,
        "broad": "03 - Engineering and Related Technologies",
        "narrow": "0301 - Manufacturing Engineering and Technology",
        "detailed": "030101 - Mechanical Engineering",
        "syllabus": (
            "English-taught 3-year Bachelor of Engineering (180 ECTS) covering engineering thermodynamics, solid mechanics, CAD/CAM "
            "modeling, materials science, automation, and Industry 4.0 smart manufacturing. Equips graduates for engineering design and "
            "industrial production careers across the EU."
        ),
        "bracket": "standard_bachelors",
    },
    "eng_electrical": {
        "title": "M.Sc. in Electrical and Microelectronic Engineering",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "03 - Engineering and Related Technologies",
        "narrow": "0313 - Electrical and Electronic Engineering",
        "detailed": "031301 - Electrical and Computer Engineering",
        "syllabus": (
            "English-taught Master of Science (120 ECTS) covering microelectronics, VLSI circuit design, embedded system firmware, "
            "signal processing, power electronics, and 5G/6G telecommunications hardware. Graduates join European semiconductor leaders "
            "(ASML, Infineon, NXP, STMicroelectronics) and tech enterprises."
        ),
        "bracket": "standard_masters",
    },

    # -------------------------------------------------------------------------
    # CLUSTER 3: BUSINESS, MANAGEMENT & ECONOMICS
    # -------------------------------------------------------------------------
    "biz_mim": {
        "title": "Master in International Management (MiM)",
        "level": "Masters",
        "raw_level": "Master in International Management (MiM)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "08 - Management and Commerce",
        "narrow": "0803 - Business and Management",
        "detailed": "080301 - Business Management",
        "syllabus": (
            "World-renowned English-taught Master in International Management (120 ECTS) accredited by EQUIS, AACSB, and AMBA. "
            "Covers global corporate strategy, financial accounting, international marketing, managerial economics, digital transformation, "
            "and cross-cultural organizational leadership. Includes a mandatory 6-month corporate internship with top management "
            "consultancies and multinationals."
        ),
        "bracket": "business_mim",
    },
    "biz_mba": {
        "title": "Full-Time Master of Business Administration (MBA)",
        "level": "Masters",
        "raw_level": "Master of Business Administration (MBA)",
        "duration": 52,
        "ielts": 7.0,
        "gpa": 65.0,
        "broad": "08 - Management and Commerce",
        "narrow": "0803 - Business and Management",
        "detailed": "080301 - Business Management",
        "syllabus": (
            "Intensive 1-year English-taught MBA programme designed for high-potential professionals. Emphasizes executive leadership, "
            "venture capital & private equity, corporate restructuring, sustainable business models, entrepreneurship, and global "
            "negotiation. High ROI with career placement in investment banking, management consulting (McKinsey, BCG, Bain), and Big Tech."
        ),
        "bracket": "business_mba",
    },
    "biz_fintech": {
        "title": "M.Sc. in FinTech and Financial Engineering",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "08 - Management and Commerce",
        "narrow": "0811 - Banking and Finance",
        "detailed": "081101 - Banking and Financial Engineering",
        "syllabus": (
            "High-demand English-taught Master of Science (120 ECTS) combining quantitative finance, stochastic calculus, "
            "algorithmic trading, blockchain architectures, smart contract security, and financial machine learning with Python. "
            "Prepares quantitative analysts (quants), risk managers, and FinTech innovators for major European financial hubs."
        ),
        "bracket": "standard_masters",
    },
    "biz_supply_chain": {
        "title": "M.Sc. in Global Supply Chain Management and Logistics",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "08 - Management and Commerce",
        "narrow": "0803 - Business and Management",
        "detailed": "080313 - Supply Chain Management and Logistics",
        "syllabus": (
            "Comprehensive English-taught master's degree (120 ECTS) in global freight operations, warehouse automation, "
            "stochastic inventory optimization, sustainable green logistics, and SAP S/4HANA enterprise supply chain analytics. "
            "Prepares supply chain directors and operations consultants for leading global trade networks."
        ),
        "bracket": "standard_masters",
    },
    "biz_analytics": {
        "title": "M.Sc. in Business Analytics and Big Data",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "08 - Management and Commerce",
        "narrow": "0803 - Business and Management",
        "detailed": "080319 - Business Analytics",
        "syllabus": (
            "Bridge programme in English (120 ECTS) blending business intelligence with predictive modeling. Modules include SQL data "
            "warehousing, PowerBI/Tableau visualization, prescriptive optimization, customer segmentation algorithms, and econometrics. "
            "Produces high-performing Business Analysts, Analytics Consultants, and Growth Strategists."
        ),
        "bracket": "standard_masters",
    },
    "biz_bsc_iba": {
        "title": "B.Sc. in International Business Administration",
        "level": "Bachelors",
        "raw_level": "Bachelor of Science (B.Sc.)",
        "duration": 156,
        "ielts": 6.0,
        "gpa": 65.0,
        "broad": "08 - Management and Commerce",
        "narrow": "0803 - Business and Management",
        "detailed": "080301 - Business Management",
        "syllabus": (
            "Rigorous 3-year English-taught undergraduate degree (180 ECTS) covering principles of micro/macroeconomics, corporate finance, "
            "marketing strategy, organizational behavior, business law, and data-driven decision making. Features international exchange "
            "semesters and prepares graduates for immediate employment or top-tier master's degrees."
        ),
        "bracket": "standard_bachelors",
    },

    # -------------------------------------------------------------------------
    # CLUSTER 4: NATURAL & PHYSICAL SCIENCES
    # -------------------------------------------------------------------------
    "sci_quantum": {
        "title": "M.Sc. in Quantum Science and Technology",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "01 - Natural and Physical Sciences",
        "narrow": "0103 - Physics and Astronomy",
        "detailed": "010301 - Quantum Physics and Computing",
        "syllabus": (
            "Elite English-taught Master of Science (120 ECTS) training researchers in quantum computing architectures (superconducting "
            "qubits, trapped ions), quantum cryptography (QKD), quantum optics, and open quantum systems simulation. "
            "Collaborative labs equip graduates for pioneering research in quantum hardware, quantum algorithms, and deep tech startups."
        ),
        "bracket": "standard_masters",
    },
    "sci_math": {
        "title": "M.Sc. in Applied Mathematics and Computational Science",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "01 - Natural and Physical Sciences",
        "narrow": "0101 - Mathematical Sciences",
        "detailed": "010101 - Applied Mathematics",
        "syllabus": (
            "English-taught master's programme (120 ECTS) covering numerical analysis, partial differential equations (PDEs), scientific "
            "high-performance computing (HPC), Monte Carlo methods, and mathematical optimization. Graduates excel in quantitative modeling, "
            "aerospace simulation, and scientific software engineering."
        ),
        "bracket": "standard_masters",
    },
    "sci_chemistry": {
        "title": "M.Sc. in Materials Chemistry and Nanotechnology",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "01 - Natural and Physical Sciences",
        "narrow": "0105 - Chemical Sciences",
        "detailed": "010501 - Materials Chemistry",
        "syllabus": (
            "English-taught Master of Science (120 ECTS) exploring advanced synthesis of nanomaterials, polymers, catalysts for green "
            "hydrogen, solid-state battery electrolytes, and 2D materials (graphene, MXenes). Hands-on characterization using XRD, SEM, "
            "TEM, and NMR spectrometers."
        ),
        "bracket": "standard_masters",
    },
    "sci_climate": {
        "title": "M.Sc. in Climate Physics and Environmental Sciences",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "01 - Natural and Physical Sciences",
        "narrow": "0107 - Earth Sciences",
        "detailed": "010703 - Atmospheric and Climate Sciences",
        "syllabus": (
            "Interdisciplinary English-taught Master of Science (120 ECTS) studying Earth system dynamics, climate modeling (IPCC scenarios), "
            "geophysical fluid dynamics, ocean-atmosphere interactions, and satellite remote sensing. Graduates become climate policy advisors, "
            "environmental modelers, and sustainability scientists."
        ),
        "bracket": "standard_masters",
    },
    "sci_bsc_physics": {
        "title": "B.Sc. in Physics and Modern Technology",
        "level": "Bachelors",
        "raw_level": "Bachelor of Science (B.Sc.)",
        "duration": 156,
        "ielts": 6.0,
        "gpa": 65.0,
        "broad": "01 - Natural and Physical Sciences",
        "narrow": "0103 - Physics and Astronomy",
        "detailed": "010301 - Physics",
        "syllabus": (
            "Rigorous 3-year English-taught undergraduate degree (180 ECTS) in classical mechanics, electromagnetism, quantum mechanics, "
            "thermodynamics, atomic physics, and computational physics lab methods. Establishes an exceptional scientific foundation for "
            "advanced research or high-tech industry careers."
        ),
        "bracket": "standard_bachelors",
    },

    # -------------------------------------------------------------------------
    # CLUSTER 5: DESIGN, ARCHITECTURE & ARTS
    # -------------------------------------------------------------------------
    "arch_march": {
        "title": "Master of Architecture (M.Arch) - Sustainable Urban Design",
        "level": "Masters",
        "raw_level": "Master of Architecture (M.Arch)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "04 - Architecture and Building",
        "narrow": "0401 - Architecture and Urban Environment",
        "detailed": "040101 - Architecture",
        "syllabus": (
            "Professional English-taught Master of Architecture (120 ECTS) compliant with the EU Architects' Directive. "
            "Combines architectural design studios, circular building materials, parametric computational modeling (Rhino/Grasshopper), "
            "bioclimatic building physics, and historic preservation. Prepares licensed architects for leading European and international practices."
        ),
        "bracket": "standard_masters",
    },
    "arch_product_design": {
        "title": "M.Sc. in Product and Industrial Design Engineering",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "10 - Creative Arts",
        "narrow": "1005 - Graphic and Design Studies",
        "detailed": "100501 - Industrial Design",
        "syllabus": (
            "Innovative English-taught Master of Science (120 ECTS) unifying human-centered design thinking, ergonomics, rapid prototyping, "
            "sustainable materials selection, and smart IoT product engineering. Graduates design consumer electronics, medical devices, "
            "and sustainable mobility hardware for leading design studios worldwide."
        ),
        "bracket": "standard_masters",
    },
    "arch_interaction_design": {
        "title": "M.Sc. in Interaction Design and Human-Computer Interaction",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "02 - Information Technology",
        "narrow": "0201 - Computer Science",
        "detailed": "020199 - Human-Computer Interaction",
        "syllabus": (
            "Cutting-edge English-taught Master of Science (120 ECTS) exploring user experience (UX) research, spatial computing (AR/VR), "
            "voice user interfaces, cognitive psychology, and accessibility design. Features intensive prototyping studios for digital product "
            "designers, UX researchers, and creative technologists."
        ),
        "bracket": "standard_masters",
    },
    "arch_bsc_arch": {
        "title": "Bachelor of Science in Architectural Design",
        "level": "Bachelors",
        "raw_level": "Bachelor of Science (B.Sc.)",
        "duration": 156,
        "ielts": 6.0,
        "gpa": 65.0,
        "broad": "04 - Architecture and Building",
        "narrow": "0401 - Architecture and Urban Environment",
        "detailed": "040101 - Architecture",
        "syllabus": (
            "Accredited 3-year English-taught undergraduate degree (180 ECTS) in architectural drafting, structural engineering fundamentals, "
            "history and theory of architecture, BIM design technology, and studio workshop projects. Serves as the primary entry degree to "
            "master's level professional licensing across the EU."
        ),
        "bracket": "standard_bachelors",
    },

    # -------------------------------------------------------------------------
    # CLUSTER 6: LAW, POLICY & SOCIAL SCIENCES
    # -------------------------------------------------------------------------
    "law_llm": {
        "title": "Master of Laws (LL.M.) in International and European Law",
        "level": "Masters",
        "raw_level": "Master of Laws (LL.M.)",
        "duration": 52,
        "ielts": 7.0,
        "gpa": 65.0,
        "broad": "09 - Society and Culture",
        "narrow": "0909 - Law",
        "detailed": "090901 - International and European Law",
        "syllabus": (
            "Prestigious 1-year English-taught Master of Laws (60-90 ECTS) covering EU constitutional law, European single market "
            "regulations, international dispute resolution, competition & antitrust law, and cross-border commercial arbitration. "
            "Prepares international lawyers for European institutions (CJEU, EC), global law firms, and corporate legal departments."
        ),
        "bracket": "standard_masters",
    },
    "law_ir": {
        "title": "Master in International Relations and European Diplomacy",
        "level": "Masters",
        "raw_level": "Master of Arts (M.A.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "09 - Society and Culture",
        "narrow": "0901 - Political Science and Policy Studies",
        "detailed": "090103 - International Relations",
        "syllabus": (
            "Interdisciplinary English-taught Master's programme (120 ECTS) analyzing geopolitical security, multilateral diplomacy, "
            "European external relations, conflict resolution, international trade treaties, and human rights governance. "
            "Produces diplomats, policy advisors, and international security analysts for the UN, EU, NATO, and think tanks."
        ),
        "bracket": "standard_masters",
    },
    "law_mpp": {
        "title": "Master of Public Policy (MPP) - Governance and Digitalization",
        "level": "Masters",
        "raw_level": "Master of Public Policy (MPP)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "09 - Society and Culture",
        "narrow": "0901 - Political Science and Policy Studies",
        "detailed": "090101 - Public Policy",
        "syllabus": (
            "Practice-oriented English-taught Master of Public Policy (120 ECTS) in evidence-based policy formulation, regulatory impact "
            "assessment, public sector budgeting, e-governance, and sustainability transitions. Equips future government leaders, "
            "NGO directors, and public sector consultants."
        ),
        "bracket": "standard_masters",
    },
    "law_cognitive": {
        "title": "M.Sc. in Cognitive Science and Behavioral Decision Making",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "09 - Society and Culture",
        "narrow": "0907 - Behavioral Science",
        "detailed": "090701 - Psychology and Cognitive Science",
        "syllabus": (
            "Advanced English-taught master's degree (120 ECTS) intersecting experimental psychology, cognitive neuroscience, "
            "behavioral economics, and computational cognition. Features fMRI and eye-tracking laboratory research for careers "
            "in behavioral insights teams, user research, and cognitive neuroscience research."
        ),
        "bracket": "standard_masters",
    },
    "law_ba_ir": {
        "title": "B.A. in International Relations and Global Affairs",
        "level": "Bachelors",
        "raw_level": "Bachelor of Arts (B.A.)",
        "duration": 156,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "09 - Society and Culture",
        "narrow": "0901 - Political Science and Policy Studies",
        "detailed": "090103 - International Relations",
        "syllabus": (
            "Foundational 3-year English-taught undergraduate degree (180 ECTS) in comparative politics, political philosophy, "
            "international economics, international law, and diplomatic history. Prepares students for careers in diplomacy, journalism, "
            "consulting, and global public administration."
        ),
        "bracket": "standard_bachelors",
    },
    # -------------------------------------------------------------------------
    # NEW BALANCING TEMPLATES
    # -------------------------------------------------------------------------
    "eng_civil": {
        "title": "M.Sc. in Sustainable Civil and Structural Engineering",
        "level": "Masters",
        "raw_level": "Master of Science (M.Sc.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "03 - Engineering and Related Technologies",
        "narrow": "0309 - Civil Engineering",
        "detailed": "030901 - Civil Engineering",
        "syllabus": (
            "Accredited English-taught Master of Science (120 ECTS) specializing in earthquake-resistant structures, low-carbon concrete, "
            "smart geotechnical engineering, transportation networks, and sustainable urban infrastructure. Compliant with Eurocodes."
        ),
        "bracket": "standard_masters",
    },
    "med_nursing": {
        "title": "B.Sc. in International Nursing and Healthcare Practice",
        "level": "Bachelors",
        "raw_level": "Bachelor of Science (B.Sc.)",
        "duration": 156,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "06 - Health",
        "narrow": "0603 - Nursing",
        "detailed": "060301 - General Nursing",
        "syllabus": (
            "Direct clinical entry English-taught 3-year Bachelor of Science (180 ECTS) in evidence-based acute and community nursing, "
            "patient safety, clinical pharmacology, and hospital simulation wards. Compliant with European nursing directives."
        ),
        "bracket": "standard_bachelors",
    },
    "arch_urban_planning": {
        "title": "Master of Architecture (M.Arch) - Sustainable Urban Planning and Resilient Cities",
        "level": "Masters",
        "raw_level": "Master of Architecture (M.Arch)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "04 - Architecture and Building",
        "narrow": "0401 - Architecture and Urban Environment",
        "detailed": "040103 - Urban Design and Regional Planning",
        "syllabus": (
            "Professional English-taught Master of Architecture (120 ECTS) in eco-city master planning, transit-oriented development (TOD), "
            "climate-resilient landscape architecture, spatial data GIS analytics, and historic urban regeneration."
        ),
        "bracket": "standard_masters",
    },
    "design_media": {
        "title": "Master of Arts in Digital Media and Interaction Design",
        "level": "Masters",
        "raw_level": "Master of Arts (M.A.)",
        "duration": 104,
        "ielts": 6.5,
        "gpa": 65.0,
        "broad": "10 - Creative Arts",
        "narrow": "1005 - Graphic and Design Studies",
        "detailed": "100503 - Digital Media Design",
        "syllabus": (
            "Interdisciplinary English-taught Master of Arts (120 ECTS) exploring interactive digital storytelling, generative AI for arts, "
            "immersive audiovisual design, game art, and creative physical computing installations."
        ),
        "bracket": "standard_masters",
    },
}


def compute_tuition_fee(country: str, is_public: bool, fee_bracket: str) -> float:
    """Calculate realistic normalized EUR tuition according to national policies."""
    # Germany: Public = 0.0 EUR (tuition-free), Private = 32,000 EUR
    if country == "Germany":
        if is_public:
            return 0.0
        return 32000.0 if fee_bracket in {"business_mba", "business_mim"} else 26000.0

    # Austria: Public = 0.0 EUR (spec says 0 for German/Austrian tuition-free public programs)
    if country == "Austria":
        if is_public:
            return 0.0
        return 22000.0

    # Poland: Low-cost hub. Medicine MD = 14,000 EUR, Dentistry = 15,000 EUR, Tech/Business = 3,500 EUR
    if country == "Poland":
        if fee_bracket == "medicine":
            return 14000.0
        if fee_bracket == "dentistry":
            return 15000.0
        if fee_bracket in {"business_mba", "business_mim"}:
            return 8500.0
        return 3500.0 if "bachelors" in fee_bracket else 4200.0

    # Italy: Public = 2,500 - 3,500 EUR. Private (Bocconi, Humanitas) = 14,000 - 18,000 EUR
    if country == "Italy":
        if not is_public:
            return 18000.0 if fee_bracket in {"business_mba", "medicine"} else 14000.0
        if fee_bracket == "medicine":
            return 3200.0
        return 2200.0 if "bachelors" in fee_bracket else 2800.0

    # Switzerland: Public (ETH, EPFL, UZH) = ~1,600 EUR/year. Private/Business (St. Gallen) = 6,500 - 18,000 EUR
    if country == "Switzerland":
        if is_public:
            return 1650.0
        return 22000.0 if fee_bracket == "business_mba" else 8500.0

    # France: Public = 2,770 EUR (Bachelors), 3,770 EUR (Masters). Grandes Écoles/Business = 18,000 - 32,000 EUR
    if country == "France":
        if not is_public or fee_bracket in {"business_mba", "business_mim"}:
            return 32000.0 if fee_bracket == "business_mba" else 19500.0
        return 2770.0 if "bachelors" in fee_bracket else 3770.0

    # Netherlands: Non-EEA rate
    if country == "Netherlands":
        if fee_bracket == "business_mba":
            return 36000.0
        if fee_bracket == "medicine":
            return 32000.0
        return 12500.0 if "bachelors" in fee_bracket else 18500.0

    # Sweden: Non-EEA rate
    if country == "Sweden":
        if fee_bracket == "business_mba":
            return 28000.0
        return 13000.0 if "bachelors" in fee_bracket else 16500.0

    # Ireland: Non-EEA rate
    if country == "Ireland":
        if fee_bracket == "medicine":
            return 52000.0
        if fee_bracket == "business_mba":
            return 34000.0
        return 16500.0 if "bachelors" in fee_bracket else 22500.0

    # Finland: Non-EEA rate
    if country == "Finland":
        return 12000.0 if "bachelors" in fee_bracket else 15000.0

    # Norway: Non-EEA public rate
    if country == "Norway":
        return 13500.0 if "bachelors" in fee_bracket else 16000.0

    # Denmark: Non-EEA rate
    if country == "Denmark":
        if fee_bracket == "business_mba":
            return 30000.0
        return 12000.0 if "bachelors" in fee_bracket else 16000.0

    # Belgium: Non-EEA rate
    if country == "Belgium":
        if fee_bracket == "business_mba":
            return 28000.0
        return 4200.0 if "bachelors" in fee_bracket else 5800.0

    return 6000.0


def select_program_keys_for_institution(inst: dict[str, Any]) -> list[str]:
    """Curate 6 to 8 tailored program keys per university matching its strengths."""
    name = inst["name"].lower()
    country = inst["country"]

    # 1. Specialized Medical Universities (e.g. Poland Medicals, Karolinska, RCSI, Med Uni Vienna)
    if any(k in name for k in ["medical", "medicine", "karolinska", "rcsi", "charité"]):
        keys = ["med_mbbs", "med_dentistry", "med_biotech", "med_public_health", "med_biomedical_sci", "med_pharmacy", "med_nursing"]
        return keys

    # 2. Specialized Business & Management Schools
    if any(k in name for k in ["business", "management", "economics", "hec", "insead", "essec", "escp", "edhec", "bocconi", "wu ", "cbs", "rsm", "esmt", "whu", "vlerick", "solvay", "kozminski", "sgh"]):
        return ["biz_mim", "biz_mba", "biz_fintech", "biz_supply_chain", "biz_analytics", "biz_bsc_iba", "law_llm"]

    # 3. Specialized Architecture & Art Universities
    if any(k in name for k in ["art", "design", "architecture", "iuav", "naba", "bauhaus", "ensci"]):
        return ["arch_march", "arch_urban_planning", "arch_bsc_arch", "arch_product_design", "arch_interaction_design", "design_media"]

    # 4. Specialized Technical & Engineering Universities (TU9, Polytechs, KTH, Chalmers, DTU, PoliMi, PoliTo, EPFL, ETH, etc.)
    if any(k in name for k in ["technical", "technology", "polytechnic", "tu ", "chalmers", "kth", "dtu", "kit", "epfl", "eth ", "politecnico", "polytechnique", "rwth"]):
        keys = [
            "eng_ai_ml",
            "eng_data_science",
            "eng_robotics",
            "eng_cybersecurity",
            "eng_renewable",
            "eng_civil",
            "eng_bsc_cs",
            "eng_electrical",
        ]
        # Prominent automotive universities in Germany & Italy
        if country in {"Germany", "Italy"} or any(k in name for k in ["tum", "rwth", "stuttgart", "berlin", "dresden", "kit", "braunschweig", "politecnico", "chalmers"]):
            keys.insert(0, "eng_automotive")

        # Top architecture & urban design technical institutes
        if any(k in name for k in ["politecnico", "delft", "eindhoven", "kth", "chalmers", "tum", "berlin", "aalto"]):
            keys.append("arch_march")
            keys.append("arch_urban_planning")
            keys.append("arch_bsc_arch")

        if any(k in name for k in ["polytechnique", "delft", "munich", "berlin", "madrid", "braunschweig"]):
            keys.append("eng_aerospace")

        return keys[:8]

    # 5. Comprehensive Universities: Ensure vibrant multi-cluster balance
    keys = [
        "eng_data_science",
        "biz_mim",
        "sci_quantum",
        "arch_march",
        "law_llm",
        "med_biotech",
        "eng_bsc_cs",
    ]

    # Add country & city specific high demand programs:
    # Polish comprehensive unis offer medicine / dentistry
    if country == "Poland" and any(k in name for k in ["warsaw", "jagiellonian", "wroclaw", "lodz", "poznan", "gdansk"]):
        keys.append("med_mbbs")
        keys.append("med_dentistry")
    elif country == "Italy" and any(k in name for k in ["bologna", "sapienza", "milan", "padua", "pavia", "tor vergata"]):
        keys.append("med_mbbs")
        keys.append("arch_urban_planning")
    elif country == "Germany" and any(k in name for k in ["heidelberg", "munich", "bonn", "freiburg", "tübingen", "göttingen"]):
        keys.append("eng_ai_ml")
        keys.append("sci_chemistry")
    elif country == "Netherlands":
        keys.append("biz_supply_chain")
        keys.append("arch_product_design")
    elif country == "Ireland":
        keys.append("biz_analytics")
        keys.append("med_public_health")
    elif country == "Sweden":
        keys.append("eng_renewable")
        keys.append("arch_urban_planning")
    elif country == "France":
        keys.append("biz_mba")
        keys.append("sci_math")
    elif country == "Switzerland":
        keys.append("eng_robotics")
        keys.append("biz_fintech")
    else:
        keys.append("sci_climate")
        keys.append("med_public_health")

    return keys[:8]


def generate_catalog() -> list[dict[str, Any]]:
    """Synthesize complete European course catalog across all 260 universities."""
    courses: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for inst in EUROPE_INSTITUTIONS_DATA:
        uni_id = inst["uni_id"]
        uni_name = inst["name"]
        country = inst["country"]
        city = inst["city"]
        is_public = inst["is_public"]
        website = inst["website"]

        keys = select_program_keys_for_institution(inst)

        for pkey in keys:
            tpl = PROGRAM_CATALOG[pkey]
            title = tpl["title"]
            degree_level = tpl["level"]
            key = (uni_name, title)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            fee_eur = compute_tuition_fee(country, is_public, tpl["bracket"])
            fee_usd = round(fee_eur * 1.08, 2) if fee_eur > 0 else 0.0

            tuition_note = "Tuition-free public university (0 EUR tuition; standard student semester administrative fee applies)." if fee_eur == 0 else f"Standard non-EEA tuition is €{fee_eur:,.0f} per academic year."
            syllabus = (
                f"{title} ({degree_level}) offered by {uni_name} in {city}, {country}. "
                f"Language of instruction: 100% taught in English. "
                f"{tpl['syllabus']} "
                f"Duration: {tpl['duration']} weeks. "
                f"{tuition_note} "
                f"Graduates are eligible for post-study work authorization and job seeker residence permits in {country} and the European Union."
            )

            intakes = ["Winter (September/October)", "Summer (March/April)"]
            next_deadline = "2027-01-15" if degree_level == "Masters" else "2026-07-15"

            courses.append(
                {
                    "course_title": title,
                    "university_name": uni_name,
                    "university_id": uni_id,
                    "country": country,
                    "degree_level": degree_level,
                    "tuition_fee": fee_eur,
                    "tuition_fee_amount": fee_eur,
                    "tuition_fee_eur": fee_eur,
                    "tuition_fee_usd": fee_usd,
                    "currency": "EUR",
                    "intakes": intakes,
                    "deadline_type": "ESTIMATED_ROLLING",
                    "next_deadline": next_deadline,
                    "min_ielts": tpl["ielts"],
                    "min_ielts_score": tpl["ielts"],
                    "min_gpa": tpl["gpa"],
                    "min_gpa_percent": tpl["gpa"],
                    "syllabus_description": syllabus,
                    "duration_weeks": tpl["duration"],
                    "course_level_raw": tpl["raw_level"],
                    "field_broad": tpl["broad"],
                    "field_narrow": tpl["narrow"],
                    "field_detailed": tpl["detailed"],
                    "post_study_work_eligible": True,
                    "source_url": website,
                    "external_course_code": f"EU-{country[:2].upper()}-{len(courses)+1:05d}",
                }
            )

    return courses


def main() -> None:
    logger.info("Generating Pan-European courses across 260 universities...")
    courses = generate_catalog()
    logger.info(f"Total courses synthesized: {len(courses)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(courses, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Successfully saved {len(courses)} courses to {OUTPUT_FILE}")

    country_counts = Counter(c["country"] for c in courses)
    degree_counts = Counter(c["degree_level"] for c in courses)
    field_counts = Counter(c["field_broad"].split(" - ", 1)[-1] for c in courses)

    print("\n" + "=" * 65)
    print(" EUROPEAN COURSE CATALOG GENERATION SUMMARY")
    print("=" * 65)
    print(f"Total Programs Generated: {len(courses)}")
    print(f"Bachelors Programs:       {degree_counts.get('Bachelors', 0)}")
    print(f"Masters Programs:         {degree_counts.get('Masters', 0)}")
    print("\nCourses by Country:")
    for country, count in country_counts.most_common():
        pct = 100.0 * count / len(courses)
        print(f"  {country:<16} {count:>5} programs ({pct:5.1f}%)")

    print("\nCourses by Academic Cluster:")
    for field, count in field_counts.most_common():
        pct = 100.0 * count / len(courses)
        print(f"  {field:<35} {count:>5} ({pct:5.1f}%)")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
