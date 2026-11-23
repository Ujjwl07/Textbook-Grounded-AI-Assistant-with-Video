"""Chapter names and book parts for the rationalised (2023+) NCERT syllabus.

Used by extract.py when a PDF's filename carries only a chapter number
(e.g. ``Class11_Physics_Ch4.pdf``) and no title.
"""
from typing import Optional

# (class_level, subject) -> {chapter_number: chapter_name}
NCERT_CHAPTERS: dict[tuple[str, str], dict[int, str]] = {
    ("11", "Physics"): {
        1: "Units and Measurement",
        2: "Motion in a Straight Line",
        3: "Motion in a Plane",
        4: "Laws of Motion",
        5: "Work, Energy and Power",
        6: "System of Particles and Rotational Motion",
        7: "Gravitation",
        8: "Mechanical Properties of Solids",
        9: "Mechanical Properties of Fluids",
        10: "Thermal Properties of Matter",
        11: "Thermodynamics",
        12: "Kinetic Theory",
        13: "Oscillations",
        14: "Waves",
    },
    ("11", "Chemistry"): {
        1: "Some Basic Concepts of Chemistry",
        2: "Structure of Atom",
        3: "Classification of Elements and Periodicity in Properties",
        4: "Chemical Bonding and Molecular Structure",
        5: "Thermodynamics",
        6: "Equilibrium",
        7: "Redox Reactions",
        8: "Organic Chemistry - Some Basic Principles and Techniques",
        9: "Hydrocarbons",
    },
    ("11", "Biology"): {
        1: "The Living World",
        2: "Biological Classification",
        3: "Plant Kingdom",
        4: "Animal Kingdom",
        5: "Morphology of Flowering Plants",
        6: "Anatomy of Flowering Plants",
        7: "Structural Organisation in Animals",
        8: "Cell: The Unit of Life",
        9: "Biomolecules",
        10: "Cell Cycle and Cell Division",
        11: "Photosynthesis in Higher Plants",
        12: "Respiration in Plants",
        13: "Plant Growth and Development",
        14: "Breathing and Exchange of Gases",
        15: "Body Fluids and Circulation",
        16: "Excretory Products and their Elimination",
        17: "Locomotion and Movement",
        18: "Neural Control and Coordination",
        19: "Chemical Coordination and Integration",
    },
    ("12", "Physics"): {
        1: "Electric Charges and Fields",
        2: "Electrostatic Potential and Capacitance",
        3: "Current Electricity",
        4: "Moving Charges and Magnetism",
        5: "Magnetism and Matter",
        6: "Electromagnetic Induction",
        7: "Alternating Current",
        8: "Electromagnetic Waves",
        9: "Ray Optics and Optical Instruments",
        10: "Wave Optics",
        11: "Dual Nature of Radiation and Matter",
        12: "Atoms",
        13: "Nuclei",
        14: "Semiconductor Electronics: Materials, Devices and Simple Circuits",
    },
    ("12", "Chemistry"): {
        1: "Solutions",
        2: "Electrochemistry",
        3: "Chemical Kinetics",
        4: "The d- and f-Block Elements",
        5: "Coordination Compounds",
        6: "Haloalkanes and Haloarenes",
        7: "Alcohols, Phenols and Ethers",
        8: "Aldehydes, Ketones and Carboxylic Acids",
        9: "Amines",
        10: "Biomolecules",
    },
    ("12", "Biology"): {
        1: "Sexual Reproduction in Flowering Plants",
        2: "Human Reproduction",
        3: "Reproductive Health",
        4: "Principles of Inheritance and Variation",
        5: "Molecular Basis of Inheritance",
        6: "Evolution",
        7: "Human Health and Disease",
        8: "Microbes in Human Welfare",
        9: "Biotechnology: Principles and Processes",
        10: "Biotechnology and its Applications",
        11: "Organisms and Populations",
        12: "Ecosystem",
        13: "Biodiversity and Conservation",
    },
}

# (class_level, subject) -> last chapter number of Part 1. Books absent here are single-volume.
PART_ONE_LAST_CHAPTER: dict[tuple[str, str], int] = {
    ("11", "Physics"): 7,
    ("11", "Chemistry"): 6,
    ("12", "Physics"): 8,
    ("12", "Chemistry"): 5,
}


def lookup_chapter(class_level: str, subject: str, chapter_number: int) -> tuple[Optional[str], str]:
    """Return (chapter_name or None, part) for a chapter of the NCERT syllabus."""
    key = (class_level, subject.strip().title())
    name = NCERT_CHAPTERS.get(key, {}).get(chapter_number)
    part = ""
    if key in PART_ONE_LAST_CHAPTER and chapter_number > 0:
        part = "Part 1" if chapter_number <= PART_ONE_LAST_CHAPTER[key] else "Part 2"
    return name, part
