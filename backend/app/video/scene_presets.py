"""Storyboard presets used when the RAG + LLM segmentation stage is unavailable.

These scenes exercise every part theme, visual type and animation_type in the
renderer, so they double as the fixture for the benchmark and pipeline tests.
Once scene_segmenter.py is wired in, real scenes replace these.
"""

def get_fallback_scenes(topic: str, subject: str, class_level: str) -> list:
    sub = (subject or "physics").lower()
    
    # Subject-specific formulas
    formula = r"F = G \frac{m_1 m_2}{r^2}"
    if sub == "chemistry":
        formula = r"PV = nRT"
    elif sub == "biology":
        formula = r"C_6H_{12}O_6 + 6O_2 \rightarrow 6CO_2 + 6H_2O"

    return [
        {
            "part": "HOOK",
            "slide_title": f"The Mystery of {topic}",
            "slide_bullets": [
                "High-yield NEET exam concept.",
                "Direct application in multiple choice questions.",
                "Connects basic concepts to complex systems."
            ],
            "narration_text": f"Welcome back, students! Today we are decoding {topic}. This is a crucial topic for NEET, appearing almost every year. Let's master it quickly.",
            "visual_type": "alert",
            "animation_type": "fade_in",
            "duration_hint_seconds": 12
        },
        {
            "part": "CONCEPT",
            "slide_title": f"What is {topic}?",
            "slide_bullets": [
                f"NCERT definition of {topic}.",
                "Fundamental properties and behaviors.",
                "Theoretical baseline for NEET questions."
            ],
            "narration_text": f"Let's look at the core concept. According to NCERT, {topic} is defined by specific physical and chemical properties. Remember these exact terms, as questions test your vocabulary directly.",
            "visual_type": "process",
            "animation_type": "slide_left",
            "duration_hint_seconds": 14
        },
        {
            "part": "EXAMPLE",
            "slide_title": "Solving NCERT Examples",
            "slide_bullets": [
                "Step-by-step formula derivation.",
                "Solving numerical equations.",
                "Highlighting key unit conversions."
            ],
            "narration_text": f"Let's practice a sample problem. Using the core formulas, we plug in the values and solve for the unknown variables. Always double-check your SI units in the final answer.",
            "visual_type": "formula",
            "formula_latex": formula,
            "animation_type": "zoom",
            "duration_hint_seconds": 16
        },
        {
            "part": "MEMORY",
            "slide_title": "Mnemonic & Recall Trick",
            "slide_bullets": [
                "Easy phrase to memorize key sequences.",
                "Mental map to avoid confusing similar terms.",
                "Quick recall technique for the exam."
            ],
            "narration_text": "To remember this order easily during the high-pressure NEET exam, use this simple mnemonic. Visually associate the letters to anchor the sequence in your memory.",
            "visual_type": "comparison",
            "animation_type": "slide_left",
            "duration_hint_seconds": 12
        },
        {
            "part": "NEET_ALERT",
            "slide_title": "Common Pitfalls & Traps!",
            "slide_bullets": [
                "Sign convention and unit mistakes.",
                "Important exception to general group trends.",
                "Spot the difference between similar definitions."
            ],
            "narration_text": "Watch out for this classic trap! Students often get confused with exception-to-trend questions and sign conventions. Make sure to slow down and read these questions carefully.",
            "visual_type": "alert",
            "animation_type": "zoom",
            "duration_hint_seconds": 14
        }
    ]
