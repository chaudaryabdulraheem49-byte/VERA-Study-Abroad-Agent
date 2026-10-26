"""Expand Canada catalog to 630+ courses across all 9 academic streams."""

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = REPO_ROOT / "data" / "canada" / "seed_courses.json"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Import base 490 courses and helper from existing generator
from generate_full_canada_catalog import DLIS, make_course, courses as base_courses

DLIS["University of Northern British Columbia (UNBC)"] = ("O19283889692", "https://www.unbc.ca/programs")

courses = list(base_courses)
print(f"Loaded {len(courses)} base Canadian courses.")

# =========================================================================
# EXPANSION 1: Clinical Medicine, Surgery & Pathology Specialties (+14 courses)
# =========================================================================
med_spec = [
    ("University of Toronto", "Master of Science in Medical Science (Institute of Medical Science)", "Masters", 46500.0, 7.5, 75.0, 104, "Master of Science in Medical Science", "MED-IMS", "Translational medicine, clinical research trials, neuroscience, cardiovascular science, and biomedical ethics."),
    ("University of Toronto", "Master of Science in Medical Biophysics", "Masters", 46500.0, 7.0, 75.0, 104, "Master of Science in Medical Biophysics", "MED-MBP", "Cancer biology, biomedical imaging, cancer genomics, radiation therapy physics, and molecular medicine at Princess Margaret Cancer Centre."),
    ("University of British Columbia (UBC)", "Master of Science in Pathology and Laboratory Medicine", "Masters", 34500.0, 7.0, 72.0, 104, "Master of Science in Pathology", "MED-PATH", "Diagnostic pathology, molecular oncology, hematopathology, clinical biochemistry, and infectious disease pathogenesis."),
    ("Western University", "Master of Science in Pathology and Laboratory Medicine", "Masters", 31000.0, 7.0, 70.0, 104, "Master of Science in Pathology", "MED-PATH", "Forensic pathology, surgical neuropathology, toxicological pathology, molecular genetics, and clinical diagnostics."),
    ("University of Alberta", "Master of Science in Laboratory Medicine and Pathology", "Masters", 24500.0, 7.0, 70.0, 104, "Master of Science in Pathology", "MED-PATH", "Clinical biochemistry, medical microbiology, transfusion medicine, cytopathology, and analytical toxicology."),
    ("University of Alberta", "Master of Science in Medical Sciences (Pediatrics)", "Masters", 24500.0, 7.0, 70.0, 104, "Master of Science in Pediatrics", "MED-PED", "Neonatal care, pediatric oncology, child health clinical trials, developmental neurology, and pediatric cardiology."),
    ("McMaster University", "Master of Science in Medical Sciences", "Masters", 32500.0, 7.0, 75.0, 104, "Master of Science in Medical Sciences", "MED-MSC", "Thrombosis research, cardiovascular physiology, respiratory biology, immunology, and molecular virology at McMaster."),
    ("University of Calgary", "Master of Science in Medical Science (Gastrointestinal Sciences)", "Masters", 28500.0, 7.0, 70.0, 104, "Master of Science in Medical Science", "MED-GI", "Inflammatory bowel disease, microbiome therapeutics, gastrointestinal motility, and hepatic clinical research."),
    ("McGill University", "Master of Science in Experimental Medicine", "Masters", 32500.0, 7.0, 72.0, 104, "Master of Science in Experimental Medicine", "MED-EXPMED", "Cardiovascular genetics, endocrinology and metabolism, kidney diseases, oncology, and autoimmune disorders at McGill."),
    ("Université d’Ottawa/University of Ottawa", "Master of Science in Cellular and Molecular Medicine (Neuroscience)", "Masters", 32400.0, 7.0, 70.0, 104, "Master of Science in Neuroscience", "MED-NEURO", "Neurodegenerative diseases, stroke recovery, Parkinson's disease, synaptic plasticity, and regenerative medicine."),
    ("Dalhousie University", "Master of Science in Medical Neuroscience", "Masters", 29800.0, 7.0, 70.0, 104, "Master of Science in Neuroscience", "MED-NEURO", "Brain plasticity, neurotrauma, visual neuroscience, sensory processing, and neuropharmacology at Dalhousie."),
    ("University of Manitoba", "Master of Science in Oral Biology (Dentistry Specialty)", "Masters", 24500.0, 7.0, 70.0, 104, "Master of Science in Oral Biology", "DENT-ORALBIO", "Salivary diagnostics, dental caries microbiology, periodontal immunology, and craniofacial bone biology."),
    ("University of Saskatchewan", "Master of Science in Health Sciences", "Masters", 26200.0, 6.5, 70.0, 104, "Master of Science in Health Sciences", "MED-MSC", "Indigenous community health, clinical epidemiology, maternal and fetal health, and chronic disease prevention."),
    ("University of Toronto", "Master of Science in Endodontics (Dental Specialty)", "Masters", 48000.0, 7.0, 75.0, 156, "Master of Science in Endodontics", "DENT-ENDO", "Root canal therapy, dental pulp biology, microsurgical endodontics, dental traumatology, and regenerative endodontics."),
]
for uni, title, lvl, fee, ielts, gpa, wks, raw, code, details in med_spec:
    courses.append(make_course(
        uni=uni, title=title, level=lvl, broad="06 - Health", narrow="0601 - Medical Studies",
        detailed=f"060101 - {title.split(' in ')[-1].split(' (')[0]}", fee_cad=fee, ielts=ielts,
        gpa=gpa, weeks=wks, raw_level=raw, code_suffix=code,
        desc=f"{title} offered by {uni}. Advanced clinical medical sciences curriculum in {details} Prepares physicians, dental specialists, and biomedical scientists for clinical leadership."
    ))

print(f"Added Stream 1 expansions: {len(courses)} total courses.")

# =========================================================================
# EXPANSION 2: Pure & Natural Sciences (+20 courses)
# =========================================================================
sci_spec = [
    ("University of Toronto", "Bachelor of Science in Neuroscience", "Bachelors", 60510.0, 6.5, 65.0, 208, "Bachelor of Science", "NEURO-BSC", "Cognitive neuroscience, molecular neurobiology, synaptic physiology, computational neural networks, and neurological disease models."),
    ("University of Toronto", "Bachelor of Science in Ecology and Evolutionary Biology", "Bachelors", 60510.0, 6.5, 65.0, 208, "Bachelor of Science", "EEB-BSC", "Population genetics, evolutionary morphology, biodiversity conservation, behavioral ecology, and climate ecology at UofT."),
    ("University of British Columbia (UBC)", "Bachelor of Science in Marine Biology", "Bachelors", 46120.0, 6.5, 65.0, 208, "Bachelor of Science", "MAR-BSC", "Oceanic ecosystems, biological oceanography, marine invertebrate zoology, coral reef ecology, and marine mammal biology at UBC."),
    ("University of British Columbia (UBC)", "Master of Science in Zoology", "Masters", 34500.0, 7.0, 70.0, 104, "Master of Science", "ZOO-MSC", "Comparative animal physiology, evolutionary genomics, biomechanics, wildlife conservation, and marine ecology at UBC."),
    ("University of British Columbia (UBC)", "Bachelor of Science in Pharmacology", "Bachelors", 46120.0, 6.5, 65.0, 208, "Bachelor of Science", "PHARM-BSC", "Molecular drug action, clinical pharmacokinetics, toxicology, cellular signal transduction, and neuropharmacology."),
    ("McGill University", "Bachelor of Science in Physiology", "Bachelors", 48900.0, 6.5, 65.0, 208, "Bachelor of Science", "PHYS-BSC", "Human organ physiology, neurophysiology, cardiovascular and respiratory mechanics, endocrinology, and cellular transport."),
    ("McGill University", "Master of Science in Physiology", "Masters", 32500.0, 7.0, 70.0, 104, "Master of Science", "PHYS-MSC", "Nonlinear dynamics in biological systems, stem cell electrophysiology, respiratory physiology, and sensory processing."),
    ("McGill University", "Bachelor of Science in Earth System Science", "Bachelors", 48900.0, 6.5, 60.0, 208, "Bachelor of Science", "EARTH-BSC", "Biogeochemical cycles, paleoclimatology, ocean-atmosphere interactions, climate modeling, and planetary geology at McGill."),
    ("University of Waterloo", "Bachelor of Science in Earth and Environmental Sciences (Hydrogeology Co-op)", "Bachelors", 49800.0, 6.5, 65.0, 240, "Bachelor of Science", "HYDRO-BSC", "Groundwater hydrology, contaminant transport modeling, environmental geochemistry, water resource remediation, and geophysics."),
    ("University of Waterloo", "Master of Science in Earth Sciences", "Masters", 31200.0, 7.0, 70.0, 104, "Master of Science", "EARTH-MSC", "Isotope hydrogeology, permafrost thaw dynamics, mining environmental geochemistry, and reactive contaminant barrier design."),
    ("University of Alberta", "Bachelor of Science in Paleontology", "Bachelors", 35400.0, 6.5, 60.0, 208, "Bachelor of Science", "PALEO-BSC", "World-renowned vertebrate paleontology program: dinosaur evolutionary biology, fossil excavation, sedimentary geology, and stratigraphy."),
    ("University of Alberta", "Master of Science in Geology", "Masters", 22100.0, 6.5, 70.0, 104, "Master of Science", "GEOL-MSC", "Petroleum geology, economic geology, diamond and mineral exploration, structural geology, and volcanology at Alberta."),
    ("McMaster University", "Bachelor of Science in Life Sciences", "Bachelors", 49800.0, 6.5, 65.0, 208, "Bachelor of Science", "LIFE-BSC", "Integrated human biology, biomedical sciences, health communications, developmental biology, and environmental toxicology."),
    ("McMaster University", "Master of Science in Computational Science and Engineering", "Masters", 31000.0, 7.0, 72.0, 104, "Master of Science", "CSE-MSC", "High-performance parallel computing, computational physics, scientific data visualization, and numerical linear algebra."),
    ("Dalhousie University", "Bachelor of Science in Ocean Sciences (Oceanography)", "Bachelors", 38500.0, 6.5, 65.0, 208, "Bachelor of Science", "OCEAN-BSC", "Chemical oceanography, physical ocean circulation, marine acoustics, deep-sea hydrothermal ecosystems, and satellite oceanography."),
    ("Dalhousie University", "Master of Science in Oceanography", "Masters", 29800.0, 7.0, 70.0, 104, "Master of Science", "OCEAN-MSC", "Ocean-climate coupling, marine biogeochemistry, coastal circulation modeling, and autonomous underwater vehicle exploration."),
    ("University of Victoria", "Bachelor of Science in Earth and Ocean Sciences", "Bachelors", 32500.0, 6.5, 60.0, 208, "Bachelor of Science", "EOS-BSC", "Connected to Ocean Networks Canada deep-sea observatories: submarine plate tectonics, climate change, and marine geophysics."),
    ("University of Victoria", "Master of Science in Astronomy", "Masters", 28500.0, 7.0, 70.0, 104, "Master of Science", "ASTRO-MSC", "Observational astronomy with Canada-France-Hawaii Telescope and Gemini Observatory, galaxy evolution, and dark matter clustering."),
    ("Simon Fraser University (SFU)", "Master of Science in Earth Sciences", "Masters", 24500.0, 7.0, 70.0, 104, "Master of Science", "EARTH-MSC", "Hydrogeology, natural hazard landslides, earthquake engineering seismology, and glacial geomorphology at SFU."),
    ("University of Saskatchewan", "Master of Science in Geological Sciences", "Masters", 26200.0, 6.5, 70.0, 104, "Master of Science", "GEOL-MSC", "Uranium and potash geology, synchrotron environmental geochemistry, sedimentology, and mineral deposit genesis at USask."),
]
for uni, title, lvl, fee, ielts, gpa, wks, raw, code, details in sci_spec:
    courses.append(make_course(
        uni=uni, title=title, level=lvl, broad="01 - Natural and Physical Sciences",
        narrow="0107 - Earth Sciences" if "Earth" in title or "Ocean" in title or "Geol" in title or "Paleo" in title else "0109 - Biological Sciences",
        detailed=f"010701 - {title.split(' in ')[-1].split(' (')[0]}", fee_cad=fee, ielts=ielts,
        gpa=gpa, weeks=wks, raw_level=raw, code_suffix=code,
        desc=f"{title} offered by {uni}. Specialized natural sciences curriculum in {details} Prepares students for cutting-edge laboratory discoveries and global environmental stewardship."
    ))

print(f"Added Stream 3 expansions: {len(courses)} total courses.")

# =========================================================================
# EXPANSION 3: Business, Management & Finance (+20 courses)
# =========================================================================
biz_spec = [
    ("University of Toronto", "Master of Management and Professional Accounting (MMPA)", "Masters", 54200.0, 7.0, 75.0, 104, "Master of Management and Professional Accounting", "MMPA", "CPA accredited master's: financial accounting, corporate audit, tax policy, management consulting, and paid co-op work terms."),
    ("University of British Columbia (UBC)", "Bachelor of Commerce (Sauder BCom - Real Estate)", "Bachelors", 58340.0, 6.5, 65.0, 208, "Bachelor of Commerce", "BCOM-RE", "Commercial real estate valuation, urban land economics, mortgage securitization, real estate investment trusts (REITs), and property development."),
    ("University of British Columbia (UBC)", "Bachelor of Commerce (Sauder BCom - Finance)", "Bachelors", 58340.0, 6.5, 65.0, 208, "Bachelor of Commerce", "BCOM-FIN", "Corporate finance, portfolio management, international financial markets, investment banking, and derivatives valuation at Sauder."),
    ("Queen's University", "Master of Financial Innovation and Technology (MFIT)", "Masters", 59000.0, 7.0, 72.0, 52, "Master of Financial Innovation & Technology", "MFIT", "FinTech, algorithmic trading, blockchain in finance, automated wealth management, machine learning finance, and financial cybersecurity."),
    ("Western University", "Master of Science in Management (Digital Management)", "Masters", 56000.0, 7.0, 70.0, 68, "Master of Science in Management", "MSCM-DIG", "Digital business models, enterprise agile frameworks, artificial intelligence governance in business, and platform economics at Ivey."),
    ("York University", "Master of Real Estate and Infrastructure (MREI)", "Masters", 56500.0, 7.0, 72.0, 52, "Master of Real Estate and Infrastructure", "MREI", "Infrastructure investment, public-private partnerships (P3), commercial real estate finance, ESG real estate, and portfolio strategy at Schulich."),
    ("York University", "Master of Accounting (MAcc)", "Masters", 49800.0, 7.0, 72.0, 36, "Master of Accounting", "MACC", "Direct path to CPA Common Final Examination (CFE): assurance, taxation, performance management, and advanced forensic accounting."),
    ("University of Waterloo", "Bachelor of Accounting and Financial Management (AFM Co-op)", "Bachelors", 54000.0, 6.5, 70.0, 240, "Bachelor of Accounting and Financial Mgmt", "AFM-COOP", "School of Accounting and Finance: corporate financial reporting, risk governance, audit, asset management, and 4 co-op work terms."),
    ("Toronto Metropolitan University (TMU)", "Bachelor of Commerce in Business Technology Management (BTM)", "Bachelors", 36500.0, 6.5, 60.0, 208, "Bachelor of Commerce in BTM", "BTM-BCOMM", "IT project management, business process analysis, enterprise cloud systems, database management, and cybersecurity governance at Ted Rogers."),
    ("Carleton University", "Bachelor of Commerce in Supply Chain Management (Sprott BCom)", "Bachelors", 38500.0, 6.5, 60.0, 208, "Bachelor of Commerce", "BCOM-SCM", "Global procurement, supply chain logistics, operations planning, ERP software integration, and inventory optimization at Sprott."),
    ("Simon Fraser University (SFU)", "Master of Science in Technology Management (MTM)", "Masters", 42000.0, 7.0, 70.0, 52, "Master of Technology Management", "MTM", "Technology commercialization, innovation strategy, intellectual property management, venture financing, and product management at Beedie."),
    ("University of Alberta", "Bachelor of Commerce in International Business", "Bachelors", 38900.0, 6.5, 60.0, 208, "Bachelor of Commerce", "BCOM-IB", "Cross-cultural management, foreign market entry, international trade law, currency risk hedging, and global marketing strategy."),
    ("University of Alberta", "Bachelor of Commerce in Strategic Management and Organization", "Bachelors", 38900.0, 6.5, 60.0, 208, "Bachelor of Commerce", "BCOM-SMO", "Corporate leadership, organizational design, business consulting, human resource strategy, and change management."),
    ("University of Calgary", "Bachelor of Commerce in Business Technology Management", "Bachelors", 34800.0, 6.5, 60.0, 208, "Bachelor of Commerce", "BCOM-BTM", "Digital transformation, enterprise systems architecture, data analytics for business, and IT consulting at Haskayne."),
    ("University of Calgary", "Bachelor of Commerce in Accounting", "Bachelors", 34800.0, 6.5, 60.0, 208, "Bachelor of Commerce", "BCOM-ACC", "Financial reporting, management accounting, tax planning, internal controls, and CPA professional accreditation at Haskayne."),
    ("McMaster University", "Master of Science in Management (Strategic Human Resource Management)", "Masters", 38500.0, 7.0, 70.0, 68, "Master of Science in Management", "MSCM-HR", "Employee relations, talent analytics, organizational development, executive compensation, and labor relations at DeGroote."),
    ("Université d’Ottawa/University of Ottawa", "Master of Science in Management (Marketing & Analytics)", "Masters", 38000.0, 7.0, 70.0, 68, "Master of Science in Management", "MSCM-MKT", "Consumer behavior modeling, digital marketing analytics, market research design, and brand equity at Telfer."),
    ("Concordia University", "Master of Science in Management (Strategic Management)", "Masters", 32500.0, 7.0, 70.0, 104, "Master of Science in Management", "MSCM-STRAT", "Corporate governance, international entrepreneurship, mergers and acquisitions strategy, and organizational theory at JMSB."),
    ("Université de Montréal", "Master of Science in Business Analytics (HEC Montréal)", "Masters", 31000.0, 7.0, 72.0, 68, "Master of Science in Business Analytics", "MSBA", "Predictive modeling, data mining, operational decision algorithms, big data architectures, and executive optimization at HEC Montréal."),
    ("University of Victoria", "Bachelor of Commerce (Gustavson BCom)", "Bachelors", 34500.0, 6.5, 65.0, 208, "Bachelor of Commerce", "BCOM-GUST", "Integrated core business, international exchange, mandatory co-op work terms, service management, and sustainable entrepreneurship."),
]
for uni, title, lvl, fee, ielts, gpa, wks, raw, code, details in biz_spec:
    narrow = "0801 - Accounting" if "Account" in title else (
        "0811 - Banking, Finance and Related Fields" if "Fin" in title or "Real Estate" in title else "0803 - Business and Management"
    )
    courses.append(make_course(
        uni=uni, title=title, level=lvl, broad="08 - Management and Commerce", narrow=narrow,
        detailed=f"{narrow[:4]}01 - {title.split(' in ')[-1].split(' (')[0]}", fee_cad=fee, ielts=ielts,
        gpa=gpa, weeks=wks, raw_level=raw, code_suffix=code,
        desc=f"{title} offered by {uni}. Professional accredited business degree in {details} Prepares students for competitive corporate finance, global supply chain, and executive consulting roles."
    ))

print(f"Added Stream 4 expansions: {len(courses)} total courses.")

# =========================================================================
# EXPANSION 4: Languages, Literature & Humanities (+20 courses)
# =========================================================================
hum_spec = [
    ("University of Toronto", "Bachelor of Arts in East Asian Studies", "Bachelors", 58500.0, 6.5, 65.0, 208, "Bachelor of Arts", "EAS-BA", "Modern and classical Chinese, Japanese, Korean languages, East Asian cultural history, philosophy, visual cultures, and international relations."),
    ("University of Toronto", "Bachelor of Arts in Classics and Ancient History", "Bachelors", 58500.0, 6.5, 65.0, 208, "Bachelor of Arts", "CLASS-BA", "Ancient Greek and Latin literature, Mediterranean classical archaeology, Roman imperial history, and Hellenistic philosophy."),
    ("University of British Columbia (UBC)", "Bachelor of Arts in Asian Area Studies", "Bachelors", 44850.0, 6.5, 65.0, 208, "Bachelor of Arts", "ASIA-BA", "Transpacific cultural studies, Asian languages, South Asian literature, Chinese cinema, and East Asian economic history."),
    ("University of British Columbia (UBC)", "Bachelor of Arts in First Nations and Endangered Languages", "Bachelors", 44850.0, 6.5, 65.0, 208, "Bachelor of Arts", "FNEL-BA", "Indigenous language revitalization methodologies, Salish linguistic documentation, oral traditions, and community language teaching."),
    ("McGill University", "Master of Arts in Islamic Studies", "Masters", 24500.0, 7.5, 75.0, 104, "Master of Arts in Islamic Studies", "ISLM-MA", "Institute of Islamic Studies: classical Arabic text analysis, Islamic jurisprudence, Middle East history, Islamic philosophy, and Persian literature."),
    ("McGill University", "Bachelor of Arts in Hispanic Studies", "Bachelors", 35200.0, 6.5, 60.0, 208, "Bachelor of Arts", "HISP-BA", "Spanish and Latin American literature, colonial chronicles, contemporary Iberian cinema, Hispanic linguistics, and translation."),
    ("University of Alberta", "Bachelor of Arts in Native Studies", "Bachelors", 32500.0, 6.5, 60.0, 208, "Bachelor of Arts", "NAT-BA", "Only dedicated Faculty of Native Studies in North America: Cree language and culture, Métis history, Indigenous legal traditions, and self-determination."),
    ("University of Alberta", "Master of Arts in Native Studies", "Masters", 22100.0, 7.0, 70.0, 104, "Master of Arts in Native Studies", "NAT-MA", "Indigenous governance, treaty history, land claims, Indigenous research methodologies, and traditional environmental knowledge."),
    ("University of Victoria", "Bachelor of Arts in Indigenous Studies", "Bachelors", 31500.0, 6.5, 60.0, 208, "Bachelor of Arts", "INDG-BA", "Indigenous resurgence, decolonizing methodologies, cultural heritage revitalization, coastal Salish governance, and community advocacy."),
    ("Queen's University", "Bachelor of Arts in Philosophy, Politics and Economics (PPE)", "Bachelors", 54200.0, 6.5, 68.0, 208, "Bachelor of Arts (Honours)", "PPE-BA", "Prestigious multidisciplinary program integrating ethical philosophy, democratic political institutions, and micro/macroeconomic analysis."),
    ("Western University", "Bachelor of Arts in Politics, Philosophy, and Economics (PPE)", "Bachelors", 44200.0, 6.5, 68.0, 208, "Bachelor of Arts", "PPE-BA", "Rigorous cross-disciplinary foundations in public choice economics, political philosophy, moral ethics, and international statecraft."),
    ("Université d’Ottawa/University of Ottawa", "Bachelor of Arts in Religious Studies and World Religions", "Bachelors", 38500.0, 6.5, 60.0, 208, "Bachelor of Arts", "REL-BA", "Comparative world religions, religion and modern public policy, biblical studies, interfaith dialogue, and indigenous spiritualities."),
    ("Simon Fraser University (SFU)", "Bachelor of Arts in World Literature", "Bachelors", 36700.0, 6.5, 60.0, 208, "Bachelor of Arts", "WLIT-BA", "Transnational literary translation, global storytelling, migration narratives, Latin American and Asian fiction, and comparative poetics."),
    ("York University", "Bachelor of Arts in German Studies", "Bachelors", 36500.0, 6.5, 60.0, 208, "Bachelor of Arts", "GER-BA", "German language mastery, Weimar culture, modern European history, German philosophy, and transnational German literature."),
    ("Carleton University", "Bachelor of Arts in Medieval and Early Modern Studies", "Bachelors", 34500.0, 6.5, 60.0, 208, "Bachelor of Arts", "MEDIEVAL-BA", "Manuscript palaeography, Latin chronicles, feudal socio-political structures, chivalric literature, and early modern scientific revolution."),
    ("University of Calgary", "Bachelor of Arts in Spanish and Latin American Studies", "Bachelors", 33500.0, 6.5, 60.0, 208, "Bachelor of Arts", "SPAN-BA", "Peninsular Spanish literature, Latin American cultural identity, Spanish linguistics, and intercultural business communications."),
    ("Dalhousie University", "Bachelor of Arts in Classics", "Bachelors", 32500.0, 6.5, 60.0, 208, "Bachelor of Arts", "CLASS-BA", "Classical Greek and Latin languages, Roman Republic history, mythology, Athenian democracy, and ancient Mediterranean philosophy."),
    ("University of Saskatchewan", "Bachelor of Arts in Indigenous Studies", "Bachelors", 30500.0, 6.5, 60.0, 208, "Bachelor of Arts", "INDG-BA", "Plains Cree culture, treaty implementation, Indian Act historical policy, community development, and Indigenous education."),
    ("Concordia University", "Bachelor of Arts in Theological Studies", "Bachelors", 28500.0, 6.5, 60.0, 208, "Bachelor of Arts", "THEOL-BA", "Christian origins, biblical Hebrew, ethics of liberation, contemporary religious pluralism, and interfaith relations."),
    ("University of Manitoba", "Bachelor of Arts in Linguistics and Cree Language", "Bachelors", 26500.0, 6.5, 60.0, 208, "Bachelor of Arts", "CREE-BA", "Algonquian linguistics, Cree grammatical structure, morphology, oral history preservation, and bilingual language pedagogy."),
]
for uni, title, lvl, fee, ielts, gpa, wks, raw, code, details in hum_spec:
    narrow = "0915 - Language and Literature" if "Language" in title or "Lit" in title or "Cree" in title or "Studies" in title else "0903 - Studies in Human Society"
    courses.append(make_course(
        uni=uni, title=title, level=lvl, broad="09 - Society and Culture", narrow=narrow,
        detailed=f"{narrow[:4]}01 - {title.split(' in ')[-1].split(' (')[0]}", fee_cad=fee, ielts=ielts,
        gpa=gpa, weeks=wks, raw_level=raw, code_suffix=code,
        desc=f"{title} offered by {uni}. Specialized humanities curriculum in {details} Fosters cultural agility, historical textual scholarship, and bilingual communications."
    ))

print(f"Added Stream 5 expansions: {len(courses)} total courses.")

# =========================================================================
# EXPANSION 5: Design, Creative Arts & Architecture (+18 courses)
# =========================================================================
design_spec = [
    ("University of Toronto", "Master of Urban Design (MUD)", "Masters", 52000.0, 7.0, 75.0, 104, "Master of Urban Design", "URB-MUD", "Daniels Faculty: large-scale urban infrastructure, public space revitalization, transit-oriented development, and spatial 3D visualization."),
    ("University of British Columbia (UBC)", "Master of Urban Design (MUD)", "Masters", 44500.0, 7.0, 75.0, 52, "Master of Urban Design", "URB-MUD", "Urban design studio, regional master planning, green city design, coastal sea-level rise resilience, and urban governance at SALA."),
    ("McGill University", "Master of Urban Planning (MUP)", "Masters", 34500.0, 7.0, 72.0, 104, "Master of Urban Planning", "URB-MUP", "CIP/PAB accredited: land use economics, transportation planning, urban environmental policy, GIS spatial analytics, and studio planning."),
    ("OCAD University", "Bachelor of Fine Arts in Digital Futures", "Bachelors", 33500.0, 6.5, 65.0, 208, "Bachelor of Fine Arts", "DES-BFA", "Physical computing, wearable sensors, virtual/augmented reality (VR/AR), creative coding, speculative game design, and AI art."),
    ("OCAD University", "Bachelor of Fine Arts in Printmaking and Publications", "Bachelors", 33500.0, 6.5, 65.0, 208, "Bachelor of Fine Arts", "ART-BFA", "Silkscreen, lithography, intaglio etching, relief woodcut, letterpress publishing, artist book design, and digital print."),
    ("OCAD University", "Bachelor of Fine Arts in Sculpture and Installation", "Bachelors", 33500.0, 6.5, 65.0, 208, "Bachelor of Fine Arts", "ART-BFA", "3D spatial art, metal casting and welding, woodworking fabrication, digital 3D fabrication, site-specific public art, and video installation."),
    ("Emily Carr University of Art and Design", "Bachelor of Media Arts in New Media and Sound Art", "Bachelors", 34500.0, 6.5, 65.0, 208, "Bachelor of Media Arts", "SND-BMA", "Spatial audio recording, interactive sound installation, digital signal processing, generative music algorithms, and sensory media."),
    ("Emily Carr University of Art and Design", "Bachelor of Design in Communication Design", "Bachelors", 34500.0, 6.5, 65.0, 208, "Bachelor of Design", "COMM-BDES", "Visual identity systems, typography, information architecture, environmental signage, brand strategy, and user interface design."),
    ("Concordia University", "Bachelor of Fine Arts in Contemporary Dance", "Bachelors", 33500.0, 6.5, 65.0, 208, "Bachelor of Fine Arts", "DANCE-BFA", "Contemporary choreography, somatic movement practices, dance dramaturgy, performance production, and movement improvisation."),
    ("Concordia University", "Bachelor of Fine Arts in Art Education (Visual Arts)", "Bachelors", 33500.0, 6.5, 65.0, 208, "Bachelor of Fine Arts", "ARTED-BFA", "Pedagogy of visual arts, museum education, studio art curriculum design, community art studio, and teaching certification."),
    ("Carleton University", "Bachelor of Media Production and Design (BMPD)", "Bachelors", 42500.0, 6.5, 65.0, 208, "Bachelor of Media Production & Design", "MEDIA-BMPD", "Joint School of Journalism and School of Information Technology: digital storytelling, interactive data graphics, and coding for media."),
    ("Toronto Metropolitan University (TMU)", "Bachelor of Fine Arts in New Media", "Bachelors", 36500.0, 6.5, 65.0, 208, "Bachelor of Fine Arts", "MEDIA-BFA", "Robotics art, interactive video installations, creative coding, virtual reality environments, and physical computing at RTA School of Media."),
    ("Toronto Metropolitan University (TMU)", "Bachelor of Fine Arts in Performance Acting / Production", "Bachelors", 36500.0, 6.5, 65.0, 208, "Bachelor of Fine Arts", "PERF-BFA", "Conservatory actor training, voice and speech, classical theatre, physical dramaturgy, stage production lighting, and sound engineering."),
    ("University of Calgary", "Master of Environmental Design (MEDes)", "Masters", 34500.0, 7.0, 72.0, 104, "Master of Environmental Design", "URB-MEDES", "Interdisciplinary research in circular building design, urban metabolism, industrial ecology, and spatial data science at SAPL."),
    ("University of Waterloo", "Bachelor of Arts in Theatre and Performance (Co-op)", "Bachelors", 44800.0, 6.5, 65.0, 208, "Bachelor of Arts", "THEA-BA", "Live stage performance, interactive theatre technologies, scenography, dramatic writing, and community arts management."),
    ("University of Victoria", "Bachelor of Fine Arts in Visual Arts", "Bachelors", 31500.0, 6.5, 65.0, 208, "Bachelor of Fine Arts", "ART-BFA", "Digital media, contemporary painting, photography darkroom and digital, sculpture, drawing, and visiting artist masterclasses."),
    ("University of Alberta", "Master of Fine Arts in Painting (MFA)", "Masters", 24500.0, 7.0, 70.0, 104, "Master of Fine Arts", "ART-MFA", "Intensive studio research in painterly materiality, critical spatial practice, exhibition installation, and academic art teaching."),
    ("York University", "Master of Fine Arts in Visual Arts (MFA)", "Masters", 28500.0, 7.0, 70.0, 104, "Master of Fine Arts", "ART-MFA", "Interdisciplinary studio research in painting, drawing, installation, photo, and print at School of the Arts, Media, Performance & Design (AMPD)."),
]
for uni, title, lvl, fee, ielts, gpa, wks, raw, code, details in design_spec:
    broad = "04 - Architecture and Building" if "Urban" in title else "10 - Creative Arts"
    narrow = "0401 - Architecture and Urban Environment" if "Urban" in title else "1005 - Graphic and Design Studies"
    courses.append(make_course(
        uni=uni, title=title, level=lvl, broad=broad, narrow=narrow,
        detailed=f"{narrow[:4]}01 - {title.split(' in ')[-1].split(' (')[0]}", fee_cad=fee, ielts=ielts,
        gpa=gpa, weeks=wks, raw_level=raw, code_suffix=code,
        desc=f"{title} offered by {uni}. Specialized studio curriculum in {details} Prepares creative practitioners for global cultural exhibitions, architecture practices, and digital design studios."
    ))

print(f"Added Stream 6 expansions: {len(courses)} total courses.")

# =========================================================================
# EXPANSION 6: Law, Policy & Social Sciences (+18 courses)
# =========================================================================
law_spec = [
    ("University of Toronto", "Master of Social Work (MSW - Factor-Inwentash Faculty)", "Masters", 46500.0, 7.5, 75.0, 104, "Master of Social Work", "SW-MSW", "Clinical social work, mental health and addiction, children and families, gerontology, and social policy advocacy. Fully CASWE accredited."),
    ("University of British Columbia (UBC)", "Master of Social Work (MSW)", "Masters", 32500.0, 7.5, 72.0, 52, "Master of Social Work", "SW-MSW", "Indigenous and intercultural social work practice, social justice clinical counseling, child welfare, and community social development."),
    ("McGill University", "Master of Social Work (MSW)", "Masters", 24500.0, 7.5, 72.0, 52, "Master of Social Work", "SW-MSW", "Clinical social work intervention, health and social policy research, refugee and immigrant integration, and trauma counseling."),
    ("University of Calgary", "Master of Social Work (MSW Clinical Specialization)", "Masters", 28500.0, 7.0, 70.0, 104, "Master of Social Work", "SW-MSW", "Clinical practice with individuals, couples and families, mental health assessment, community social work, and addictions treatment."),
    ("York University", "Bachelor of Social Work (BSW Honours)", "Bachelors", 36500.0, 6.5, 65.0, 208, "Bachelor of Social Work", "SW-BSW", "Anti-oppressive social work practice, critical social policy analysis, human rights protection, and 700 hours of clinical practicum."),
    ("University of Toronto", "Bachelor of Arts in International Relations", "Bachelors", 58500.0, 6.5, 65.0, 208, "Bachelor of Arts", "IR-BA", "Trinity College international relations: grand strategy, international security, nuclear non-proliferation, diplomatic negotiation, and trade governance."),
    ("University of British Columbia (UBC)", "Bachelor of Arts in International Relations", "Bachelors", 44850.0, 6.5, 65.0, 208, "Bachelor of Arts", "IR-BA", "Global economic governance, international security, human rights treaties, international law, and foreign policy decision-making."),
    ("University of Calgary", "Bachelor of Arts in International Relations", "Bachelors", 33500.0, 6.5, 60.0, 208, "Bachelor of Arts", "IR-BA", "Geopolitics of energy, global security, international organization diplomacy, and regional conflict analysis at Calgary."),
    ("University of Toronto", "Master of Arts in Political Science", "Masters", 39500.0, 7.5, 75.0, 52, "Master of Arts", "POL-MA", "Comparative politics, international relations theory, political philosophy, Canadian federalism, and quantitative political methodology."),
    ("University of British Columbia (UBC)", "Master of Arts in Political Science", "Masters", 31000.0, 7.5, 75.0, 52, "Master of Arts", "POL-MA", "Democratic institutions, environmental politics, global political economy, indigenous politics, and comparative public opinion."),
    ("McGill University", "Master of Arts in Political Science (International Relations)", "Masters", 24500.0, 7.5, 75.0, 52, "Master of Arts", "POL-MA", "International security, peacebuilding, civil war dynamics, international organizations, and foreign policy analysis at McGill."),
    ("University of Alberta", "Master of Arts in Political Science", "Masters", 22100.0, 7.0, 70.0, 104, "Master of Arts", "POL-MA", "Critical political economy, gender and politics, petroleum politics, Canadian constitutionalism, and political theory at Alberta."),
    ("Université d’Ottawa/University of Ottawa", "Master of Arts in Political Science", "Masters", 26500.0, 7.0, 70.0, 104, "Master of Arts", "POL-MA", "Public policy formulation, international relations, Canadian government, bilingual statecraft, and social movement politics."),
    ("University of Victoria", "Master of Arts in Dispute Resolution (MADR)", "Masters", 28500.0, 7.0, 72.0, 104, "Master of Arts in Dispute Resolution", "LAW-MADR", "Mediation and arbitration, restorative justice, cross-cultural negotiations, environmental conflict resolution, and labor diplomacy."),
    ("Carleton University", "Master of Arts in Legal Studies", "Masters", 28500.0, 7.0, 72.0, 104, "Master of Arts in Legal Studies", "LAW-MALS", "Critical legal theory, human rights, sociology of law, surveillance and governance, and indigenous legal traditions at Carleton."),
    ("University of Saskatchewan", "Master of Laws (LLM)", "Masters", 26200.0, 7.0, 72.0, 52, "Master of Laws (LL.M.)", "LAW-LLM", "Aboriginal law, constitutional law, environmental natural resources law, international trade law, and criminal law theory."),
    ("University of Manitoba", "Master of Laws (LLM - Robson Hall)", "Masters", 24500.0, 7.0, 72.0, 52, "Master of Laws (LL.M.)", "LAW-LLM", "Robson Hall Faculty of Law: human rights law, indigenous jurisprudence, international business transactions, and healthcare law."),
    ("Dalhousie University", "Master of Laws in Marine and Environmental Law (LLM)", "Masters", 29800.0, 7.5, 75.0, 52, "Master of Laws (LL.M.)", "LAW-LLM", "Marine Resources Law Institute: law of the sea, maritime commercial law, coastal zone governance, and climate change litigation."),
]
for uni, title, lvl, fee, ielts, gpa, wks, raw, code, details in law_spec:
    narrow = "0905 - Human Welfare Studies and Services" if "Social Work" in title else (
        "0909 - Law" if "Law" in title or "Dispute" in title or "Legal" in title else "0901 - Political Science and Policy Studies"
    )
    courses.append(make_course(
        uni=uni, title=title, level=lvl, broad="09 - Society and Culture", narrow=narrow,
        detailed=f"{narrow[:4]}01 - {title.split(' in ')[-1].split(' (')[0]}", fee_cad=fee, ielts=ielts,
        gpa=gpa, weeks=wks, raw_level=raw, code_suffix=code,
        desc=f"{title} offered by {uni}. Specialized curriculum in {details} Prepares students for licensed professional social work, foreign diplomacy, legal advisory, and high-level policy governance."
    ))

print(f"Added Stream 7 expansions: {len(courses)} total courses.")

# =========================================================================
# EXPANSION 7: Agriculture, Veterinary & Environmental Sciences (+18 courses)
# =========================================================================
agri_spec = [
    ("University of Guelph", "Bachelor of Bio-Resource Management (Equine Management)", "Bachelors", 37500.0, 6.5, 65.0, 208, "Bachelor of Bio-Resource Management", "BBRM-EQ", "Equine physiology, equine nutrition, reproduction, horse facility design, equine business management, and exercise physiology."),
    ("University of Guelph", "Master of Science in Animal Biosciences", "Masters", 28500.0, 7.0, 70.0, 104, "Master of Science", "ANBIO-MSC", "Livestock genomics, dairy cattle nutrition, poultry physiology, animal welfare assessment, and reproductive biotechnology."),
    ("University of British Columbia (UBC)", "Bachelor of Science in Wood Products Processing (BSc WPP Co-op)", "Bachelors", 46120.0, 6.5, 65.0, 240, "Bachelor of Science in Wood Products", "WOOD-BSC", "Faculty of Forestry: advanced mass timber engineering, wood composite manufacturing, CNC robotics fabrication, and green building materials."),
    ("University of British Columbia (UBC)", "Bachelor of Science in Urban Forestry (BSc UF)", "Bachelors", 46120.0, 6.5, 65.0, 208, "Bachelor of Science in Urban Forestry", "FOR-BSCUF", "Urban forest planning, municipal tree inventory, urban ecology, green infrastructure, biodiversity in cities, and community engagement."),
    ("University of British Columbia (UBC)", "Master of International Forestry (MIF)", "Masters", 42500.0, 7.0, 70.0, 44, "Master of International Forestry", "FOR-MIF", "Global forest policy, tropical rainforest conservation, international carbon offset verification, and sustainable forest finance."),
    ("University of Alberta", "Master of Science in Forest Biology and Management", "Masters", 24500.0, 6.5, 70.0, 104, "Master of Science", "FOR-MSC", "Forest tree physiology, forest insect ecology, wildland fire behavior modeling, and boreal forest carbon modeling."),
    ("University of Saskatchewan", "Bachelor of Science in Renewable Resource Management", "Bachelors", 32500.0, 6.5, 60.0, 208, "Bachelor of Science", "RRM-BSC", "Grassland ecology, watershed management, wildlife habitat restoration, environmental soil science, and remote sensing mapping."),
    ("University of Saskatchewan", "Master of Science in Animal and Poultry Science", "Masters", 26200.0, 6.5, 70.0, 104, "Master of Science", "POULT-MSC", "Ruminant nutrition, poultry breeding genetics, meat quality science, feed formulation technology, and animal welfare."),
    ("University of Manitoba", "Master of Science in Biosystems Engineering", "Masters", 28500.0, 6.5, 70.0, 104, "Master of Science", "BIOENG-MSC", "Agricultural machinery automation, grain drying and storage engineering, biofuel processing, and agricultural waste remediation."),
    ("University of Manitoba", "Bachelor of Science in Agroecology", "Bachelors", 28500.0, 6.5, 60.0, 208, "Bachelor of Science in Agroecology", "AGRO-BSC", "Ecological agriculture, organic crop rotation, pesticide reduction, biodiversity in farming, and sustainable prairie food systems."),
    ("Dalhousie University", "Bachelor of Technology in Environmental Landscape Horticulture", "Bachelors", 34500.0, 6.5, 60.0, 208, "Bachelor of Technology", "HORT-BTECH", "Botanical garden curation, greenhouse technology, urban greening, nursery management, and plant propagation science."),
    ("Dalhousie University", "Master of Science in Aquaculture", "Masters", 29800.0, 7.0, 70.0, 104, "Master of Science in Aquaculture", "AQUA-MSC", "Salmonid fish farming, shellfish mariculture, recirculating aquaculture systems (RAS), aquatic fish pathology, and feed nutrition."),
    ("McGill University", "Bachelor of Science in Life Sciences (Plant Biology & Biotechnology)", "Bachelors", 35200.0, 6.5, 60.0, 208, "Bachelor of Science", "PLANT-BSC", "Macdonald Campus: plant breeding, molecular plant pathology, crop tissue culture, agricultural biotechnology, and plant biochemistry."),
    ("McGill University", "Master of Science in Parasitology", "Masters", 26500.0, 7.0, 70.0, 104, "Master of Science in Parasitology", "PARASIT-MSC", "Institute of Parasitology: human and animal parasitic diseases, tropical veterinary medicine, anthelmintic resistance, and drug discovery."),
    ("University of Northern British Columbia (UNBC)", "Bachelor of Science in Wildlife and Fisheries", "Bachelors", 28500.0, 6.5, 60.0, 208, "Bachelor of Science", "WILD-BSC", "Fish habitat ecology, wildlife conservation, population dynamics of bears and ungulates, river restoration, and GIS wildlife tracking."),
    ("University of Northern British Columbia (UNBC)", "Master of Natural Resources and Environmental Studies", "Masters", 22500.0, 6.5, 70.0, 104, "Master of Natural Resources", "NRES-MSC", "Northern forest management, salmon river watersheds, subarctic climate ecology, and indigenous environmental co-management."),
    ("Université Laval", "Baccalauréat en agronomie (B.Sc.Agr.)", "Bachelors", 29500.0, 6.5, 60.0, 208, "Baccalauréat en agronomie", "AGRO-BSC", "Ordre des agronomes du Québec: production végétale, gestion des sols agricoles, entomologie agricole, et économie rurale."),
    ("Université Laval", "Maîtrise en sciences et technologie des aliments", "Masters", 23500.0, 7.0, 70.0, 104, "Maîtrise en sciences des aliments", "FOOD-MSC", "Microbiologie laitière, procédés de transformation fromagère, emballage barrière alimentaire, et biochimie nutritionnelle."),
]
for uni, title, lvl, fee, ielts, gpa, wks, raw, code, details in agri_spec:
    broad = "05 - Agriculture, Environmental and Related Studies"
    narrow = "0501 - Agriculture" if "Agri" in title or "Equine" in title or "Animal" in title or "Food" in title or "Plant" in title else (
        "0505 - Forestry Studies" if "Forest" in title or "Wood" in title else (
            "0507 - Fisheries Studies" if "Aqua" in title or "Fisheries" in title else "0599 - Other Agriculture, Environmental and Related Studies"
        )
    )
    courses.append(make_course(
        uni=uni, title=title, level=lvl, broad=broad, narrow=narrow,
        detailed=f"{narrow[:4]}01 - {title.split(' in ')[-1].split(' (')[0]}", fee_cad=fee, ielts=ielts,
        gpa=gpa, weeks=wks, raw_level=raw, code_suffix=code,
        desc=f"{title} offered by {uni}. Specialized curriculum in {details} Prepares students for professional agrologist/forester licensing, commercial food biotechnology, and natural resources stewardship."
    ))

print(f"Added Stream 8 expansions: {len(courses)} total courses.")

# =========================================================================
# EXPANSION 8: Engineering & Computer Science (+25 courses)
# =========================================================================
eng_spec = [
    ("University of Waterloo", "Bachelor of Applied Science in Nanotechnology Engineering (Co-op)", "Bachelors", 68000.0, 6.5, 70.0, 240, "Bachelor of Applied Science", "NANO-BASC", "Nanoscale electronics, quantum dot photonics, carbon nanotube materials, molecular synthesis, biosensing devices, and cleanroom fabrication."),
    ("University of Waterloo", "Bachelor of Applied Science in Environmental Engineering", "Bachelors", 67000.0, 6.5, 65.0, 240, "Bachelor of Applied Science", "ENV-BASC", "Industrial wastewater remediation, air pollution control, solid waste incineration, groundwater contaminant modeling, and green infrastructure."),
    ("University of Waterloo", "Master of Engineering in Clean Energy and Sustainable Infrastructure", "Masters", 43500.0, 6.5, 70.0, 52, "Master of Engineering", "ENG-CLEAN", "Solar photovoltaic engineering, hydrogen fuel cells, grid energy storage batteries, wind turbine aerodynamics, and microgrid design."),
    ("University of Toronto", "Bachelor of Applied Science in Materials Science and Engineering", "Bachelors", 65410.0, 6.5, 65.0, 208, "Bachelor of Applied Science", "MSE-BASC", "Advanced metallurgical alloys, semiconductor nanomaterials, electronic ceramics, composite materials, and battery materials design."),
    ("University of Toronto", "Master of Engineering in Aerospace Engineering (UTIAS)", "Masters", 56230.0, 7.0, 70.0, 52, "Master of Engineering", "AERO-MENG", "University of Toronto Institute for Aerospace Studies (UTIAS): flight mechanics, orbital satellite systems, supersonic aerodynamics, and aerospace autonomy."),
    ("University of Toronto", "Master of Science in Computer Science (Research Track)", "Masters", 46500.0, 7.5, 78.0, 104, "Master of Science in Computer Science", "CS-MSC", "Foundational thesis research: computational linguistics, robotics, distributed ledger systems, human-computer interaction, and quantum computing."),
    ("University of British Columbia (UBC)", "Bachelor of Applied Science in Geological Engineering", "Bachelors", 55890.0, 6.5, 65.0, 208, "Bachelor of Applied Science", "GEO-BASC", "Rock mechanics, landslide stabilization, hydrogeological engineering, tunnel excavation design, and earthquake foundation engineering."),
    ("University of British Columbia (UBC)", "Bachelor of Applied Science in Environmental Engineering", "Bachelors", 55890.0, 6.5, 65.0, 208, "Bachelor of Applied Science", "ENV-BASC", "Joint UBC-UNBC engineering: water and sanitation engineering, climate change adaptation, contaminated site remediation, and environmental impact assessment."),
    ("University of British Columbia (UBC)", "Master of Engineering in Telecommunications and Networking", "Masters", 42750.0, 7.0, 70.0, 52, "Master of Engineering", "ELEC-MENG", "5G/6G wireless networks, optical communication fibers, IoT architecture, software-defined networking (SDN), and radio frequency engineering."),
    ("University of Alberta", "Bachelor of Science in Computer Engineering (Software & Hardware)", "Bachelors", 44300.0, 6.5, 65.0, 208, "Bachelor of Science in Engineering", "CE-BSC", "Microprocessor architecture, FPGA digital design, real-time operating systems, digital signal processing, and embedded AI computing."),
    ("University of Alberta", "Master of Science in Electrical and Computer Engineering", "Masters", 24500.0, 7.0, 70.0, 104, "Master of Science in ECE", "ECE-MSC", "Power systems engineering, smart energy grids, photonic microdevices, biomedical ultrasound electronics, and computer engineering."),
    ("McGill University", "Master of Science in Electrical Engineering", "Masters", 36800.0, 6.5, 70.0, 104, "Master of Science in Electrical Eng", "ELEC-MSC", "Photonics and optical systems, power electronics, neuromorphic computing hardware, wireless communications, and robotics control."),
    ("McGill University", "Bachelor of Engineering in Materials Engineering", "Bachelors", 59200.0, 6.5, 65.0, 208, "Bachelor of Engineering", "MSE-BENG", "Materials degradation and corrosion, high-performance alloys, mineral processing thermodynamics, nanomaterials, and biomaterials."),
    ("McMaster University", "Bachelor of Engineering in Engineering Physics", "Bachelors", 62800.0, 6.5, 65.0, 208, "Bachelor of Engineering", "ENGPHYS-BENG", "Nuclear engineering, laser optics and photonics, quantum semiconductor devices, solar cell engineering, and nanotechnology."),
    ("McMaster University", "Master of Engineering in Nuclear Engineering", "Masters", 38500.0, 6.5, 70.0, 52, "Master of Engineering in Nuclear", "NUC-MENG", "Utilizing McMaster Nuclear Reactor: reactor thermalhydraulics, nuclear safety analysis, radiation shielding, and small modular reactor (SMR) design."),
    ("Queen's University", "Master of Science in Computer Science (Biomedical Computing)", "Masters", 32500.0, 7.0, 70.0, 104, "Master of Science in CS", "CS-MSC", "Computer-assisted surgery, medical image processing (MRI/CT), healthcare data analytics, genomics bioinformatics, and machine learning diagnostics."),
    ("Queen's University", "Bachelor of Applied Science in Mathematics and Engineering", "Bachelors", 56500.0, 6.5, 70.0, 208, "Bachelor of Applied Science", "MENG-BASC", "Prestigious multidisciplinary degree: systems control theory, stochastic communications, financial engineering, robotics, and algorithmic information theory."),
    ("Western University", "Bachelor of Engineering Science in Software Engineering", "Bachelors", 49500.0, 6.5, 65.0, 208, "Bachelor of Engineering Science", "SE-BESC", "Software design patterns, database architecture, cloud microservices, cybersecurity, web applications, and mobile software engineering."),
    ("University of Calgary", "Master of Engineering in Geomatics Engineering", "Masters", 36500.0, 6.5, 70.0, 52, "Master of Engineering in Geomatics", "GEO-MENG", "Satellite GPS/GNSS positioning, aerial LiDAR mapping, autonomous vehicle navigation systems, digital photogrammetry, and spatial GIS analytics."),
    ("University of Calgary", "Bachelor of Science in Geomatics Engineering", "Bachelors", 42900.0, 6.5, 65.0, 208, "Bachelor of Science in Engineering", "GEO-BSC", "Sensor integration for self-driving vehicles, geodesy, satellite remote sensing, land surveying, and geospatial spatial computation."),
    ("Simon Fraser University (SFU)", "Bachelor of Applied Science in Mechatronic Systems Engineering", "Bachelors", 38500.0, 6.5, 65.0, 208, "Bachelor of Applied Science", "MECH-BASC", "Robotics systems, automotive electronics, autonomous mobile robots, micro-electromechanical systems (MEMS), and automated manufacturing."),
    ("Université d’Ottawa/University of Ottawa", "Bachelor of Applied Science in Chemical Engineering (Biotechnology)", "Bachelors", 48500.0, 6.5, 65.0, 208, "Bachelor of Applied Science", "CHEM-BASC", "Bioreactor engineering, industrial enzyme catalysis, fermentation technology, polymer materials, and environmental pollution control."),
    ("Carleton University", "Bachelor of Engineering in Communications Engineering", "Bachelors", 46500.0, 6.5, 65.0, 208, "Bachelor of Engineering", "COMM-BENG", "Cellular mobile telephony (5G), satellite communications, fiber optic communications, radar systems, and digital signal modulation."),
    ("Toronto Metropolitan University (TMU)", "Bachelor of Engineering in Computer Engineering", "Bachelors", 42500.0, 6.5, 65.0, 208, "Bachelor of Engineering", "CE-BENG", "Computer hardware engineering, digital system design, computer network architectures, embedded systems, and real-time computing."),
    ("Concordia University", "Master of Applied Science in Information Systems Security (Cybersecurity)", "Masters", 36500.0, 6.5, 70.0, 104, "Master of Applied Science in ISS", "CYBER-MASC", "Network security, cryptography, malware reverse engineering, digital forensics, cloud security protocols, and ethical hacking."),
]
for uni, title, lvl, fee, ielts, gpa, wks, raw, code, details in eng_spec:
    broad = "02 - Information Technology" if "Computer Science" in title or "Cyber" in title else "03 - Engineering and Related Technologies"
    narrow = "0201 - Computer Science" if "Computer Science" in title else (
        "0203 - Information Systems" if "Cyber" in title else (
            "0307 - Mechanical and Industrial Engineering" if "Mechatronic" in title or "Aerospace" in title else (
                "0309 - Civil Engineering" if "Geomatics" in title or "Environmental" in title else (
                    "0313 - Electrical and Electronic Engineering" if "Electrical" in title or "Communications" in title or "Computer Engineering" in title or "Nanotechnology" in title else "0303 - Process and Resources Engineering"
                )
            )
        )
    )
    courses.append(make_course(
        uni=uni, title=title, level=lvl, broad=broad, narrow=narrow,
        detailed=f"{narrow[:4]}01 - {title.split(' in ')[-1].split(' (')[0]}", fee_cad=fee, ielts=ielts,
        gpa=gpa, weeks=wks, raw_level=raw, code_suffix=code,
        desc=f"{title} offered by {uni}. Professional accredited program in {details} Accredited by Engineers Canada (CEAB) and CIPS, qualifying graduates for Professional Engineer (P.Eng.) certification."
    ))

print(f"Added Stream 9 expansions: {len(courses)} total courses.")

# =========================================================================
# Write complete catalog to disk
# =========================================================================
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE.write_text(json.dumps(courses, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"\n=======================================================")
print(f" FINAL FULL-SPECTRUM CATALOG COURSES: {len(courses):,}")
print(f"=======================================================")
print(f"Saved to: {OUTPUT_FILE}")
