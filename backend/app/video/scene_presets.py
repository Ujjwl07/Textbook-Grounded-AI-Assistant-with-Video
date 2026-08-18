"""Storyboard presets used when the RAG + LLM segmentation stage is unavailable.

These scenes exercise every part theme, visual type and animation_type in the
renderer, so they double as the fixture for the benchmark and pipeline tests.

They also define the contract the LLM scene segmenter must satisfy. Each scene
may carry:

    definition          exact wording to display in the quoted card
    definition_source   citation shown under the definition
    visual_type         formula | process | comparison | diagram | alert | image
    visual_data         the *content* of that visual (steps, columns, labels)
    image_path          a figure to show instead of a drawn visual
    image_caption       caption under the figure
    animation_type      fade_in | slide_left | zoom
    duration_hint_seconds

``visual_data`` is what makes the panels informative. Without it the renderer
can only draw empty scaffolding — the earlier presets produced a comparison box
labelled "Condition A" / "Condition B" with nothing inside.
"""

# Topic-specific storyboards. Anything not listed falls back to GENERIC_TOPIC,
# which stays deliberately plain rather than inventing facts.
TOPIC_PRESETS = {
    "gravitation": {
        "subject": "physics",
        "definition": (
            "Every body in the universe attracts every other body with a force "
            "which is directly proportional to the product of their masses and "
            "inversely proportional to the square of the distance between them."
        ),
        "definition_source": "NCERT Class 11 Physics, Ch. 7 — Universal Law of Gravitation",
        "formula": r"F = G \frac{m_1 m_2}{r^2}",
        "concept_bullets": [
            "Holds for every pair of bodies, everywhere in the universe.",
            "G is a universal constant — it never changes.",
        ],
        "concept_steps": [
            "Two masses m₁ and m₂ separated by distance r",
            "Force acts along the line joining their centres",
            "F doubles if either mass doubles",
            "F falls to one-fourth if r doubles",
        ],
        "example_bullets": [
            "G = 6.67 × 10⁻¹¹ N m² kg⁻²",
            "Substitute masses in kg and r in metres.",
            "Answer carries the unit newton (N).",
        ],
        "memory": {
            "left": {"title": "g", "points": ["Acceleration due to gravity",
                                              "Varies with location",
                                              "Units: m s⁻²"]},
            "right": {"title": "G", "points": ["Universal constant",
                                               "Same everywhere",
                                               "Units: N m² kg⁻²"]},
        },
        "memory_bullets": [
            "small g = ground level, changes place to place.",
            "capital G = Global constant, same everywhere.",
            "Both appear in the same formula — read the case carefully.",
        ],
        "alert_caption": "Do not confuse g with G",
        "alert_bullets": [
            "g changes with height and latitude; G never does.",
            "Distance r is measured centre to centre, not surface to surface.",
            "Inverse square: r is squared, not the force.",
        ],
    },
    "photosynthesis": {
        "subject": "biology",
        "definition": (
            "Photosynthesis is the process by which green plants synthesise "
            "carbohydrates from carbon dioxide and water using light energy "
            "trapped by chlorophyll, releasing oxygen as a by-product."
        ),
        "definition_source": "NCERT Class 11 Biology — Photosynthesis in Higher Plants",
        "formula": r"6CO_2 + 12H_2O \rightarrow C_6H_{12}O_6 + 6O_2 + 6H_2O",
        "concept_bullets": [
            "Occurs in the chloroplast of green plant cells.",
            "Oxygen released comes from water, not CO₂.",
        ],
        "concept_steps": [
            "Light absorbed by chlorophyll in thylakoids",
            "Photolysis of water releases O₂",
            "ATP and NADPH formed in light reaction",
            "Calvin cycle fixes CO₂ into sugar",
        ],
        "example_bullets": [
            "Light reaction occurs in the thylakoid membrane.",
            "Dark reaction occurs in the stroma.",
            "RuBisCO fixes CO₂ onto RuBP.",
        ],
        "memory": {
            "left": {"title": "Light reaction", "points": ["In thylakoid", "Needs light",
                                                           "Makes ATP + NADPH"]},
            "right": {"title": "Calvin cycle", "points": ["In stroma", "Light independent",
                                                          "Fixes CO₂"]},
        },
        "memory_bullets": [
            "\"Light makes the money, Calvin spends it.\"",
            "Light reaction makes ATP and NADPH; Calvin cycle consumes them.",
            "Thylakoid before stroma — outside in.",
        ],
        "alert_caption": "Dark reaction still needs light indirectly",
        "alert_bullets": [
            "The Calvin cycle runs in light too — it is light independent, not dark-only.",
            "O₂ comes from water, not from carbon dioxide.",
            "RuBisCO also binds O₂, causing photorespiration.",
        ],
    },
}

GENERIC_TOPIC = {
    "subject": "physics",
    "definition": "",
    "definition_source": "",
    "formula": r"F = ma",
    "concept_steps": [],
    "example_bullets": [
        "Identify the given quantities and the unknown.",
        "Choose the equation that links them.",
        "Substitute in SI units and check the final unit.",
    ],
    "memory": {},
    "alert_caption": "Common NEET traps",
    "alert_bullets": [
        "Watch sign conventions and unit conversions.",
        "Note the exceptions to the general trend.",
        "Distinguish between similar-sounding definitions.",
    ],
}

SUBJECT_FORMULA_FALLBACK = {
    "physics": r"F = G \frac{m_1 m_2}{r^2}",
    "chemistry": r"PV = nRT",
    "biology": r"C_6H_{12}O_6 + 6O_2 \rightarrow 6CO_2 + 6H_2O",
}


def _preset_for(topic: str, subject: str) -> dict:
    key = (topic or "").strip().lower()
    for name, preset in TOPIC_PRESETS.items():
        if name in key:
            return preset
    preset = dict(GENERIC_TOPIC)
    preset["formula"] = SUBJECT_FORMULA_FALLBACK.get(
        (subject or "physics").lower(), GENERIC_TOPIC["formula"]
    )
    return preset


def get_fallback_scenes(topic: str, subject: str, class_level: str) -> list:
    preset = _preset_for(topic, subject)
    steps = preset.get("concept_steps") or []
    comparison = preset.get("memory") or {}

    return [
        {
            "part": "HOOK",
            "slide_title": f"The Mystery of {topic}",
            "slide_bullets": [
                "High-yield NEET exam concept.",
                "Appears almost every year in the paper.",
                "Connects basic ideas to complex systems.",
            ],
            "narration_text": (
                f"Welcome back, students! Today we are decoding {topic}. "
                "This is a crucial topic for NEET, appearing almost every year. "
                "Let's master it quickly."
            ),
            "visual_type": "alert",
            "visual_data": {"caption": "High-weightage topic"},
            "animation_type": "fade_in",
            "duration_hint_seconds": 12,
        },
        {
            "part": "CONCEPT",
            "slide_title": f"What is {topic}?",
            "definition": preset.get("definition", ""),
            "definition_source": preset.get("definition_source", ""),
            # Supporting points sit under the definition card rather than
            # replacing it, so the left column is not half empty.
            "slide_bullets": preset.get("concept_bullets") or ([] if preset.get("definition") else [
                f"NCERT definition of {topic}.",
                "Fundamental properties and behaviour.",
            ]),
            "narration_text": (
                f"Let's look at the core concept. According to NCERT, {topic} is defined "
                "by specific physical properties. Remember these exact terms, as questions "
                "test your vocabulary directly."
            ),
            "visual_type": "process" if steps else "diagram",
            "visual_data": {"steps": steps} if steps else {"title": topic, "labels": []},
            "animation_type": "slide_left",
            "duration_hint_seconds": 16,
        },
        {
            "part": "EXAMPLE",
            "slide_title": "Solving NCERT Examples",
            "slide_bullets": preset.get("example_bullets", []),
            "narration_text": (
                "Let's practice a sample problem. Using the core formula, we plug in the "
                "values and solve for the unknown. Always double-check your SI units in "
                "the final answer."
            ),
            "visual_type": "formula",
            "formula_latex": preset.get("formula"),
            "animation_type": "zoom",
            "duration_hint_seconds": 16,
        },
        {
            "part": "MEMORY",
            "slide_title": "Mnemonic & Recall Trick",
            "slide_bullets": preset.get("memory_bullets") or ([] if comparison else [
                "Easy phrase to memorise key sequences.",
                "Mental map to avoid confusing similar terms.",
            ]),
            "narration_text": (
                "To remember this easily during the high-pressure NEET exam, compare the "
                "two side by side. Anchoring the difference visually stops you mixing them up."
            ),
            "visual_type": "comparison" if comparison else "diagram",
            "visual_data": comparison if comparison else {"title": topic, "labels": []},
            "animation_type": "slide_left",
            "duration_hint_seconds": 14,
        },
        {
            "part": "NEET_ALERT",
            "slide_title": "Common Pitfalls & Traps!",
            "slide_bullets": preset.get("alert_bullets", []),
            "narration_text": (
                "Watch out for this classic trap! Students often get confused here. "
                "Slow down and read these questions carefully in the exam."
            ),
            "visual_type": "alert",
            "visual_data": {"caption": preset.get("alert_caption", "CRITICAL NEET TRAP")},
            "animation_type": "zoom",
            "duration_hint_seconds": 14,
        },
    ]
