"""Subject-to-voice mapping for the narration pipeline (Pallika, Section 11.3 #1).

Each subject gets its own voice, speaking rate and pitch. The rate choices are
pedagogical, not cosmetic: Biology narration is slowed because it carries dense
terminology ("zona pellucida", "oxidative phosphorylation"), and Chemistry is
slowed slightly because expanded reaction equations produce long token runs.

``emphasis_words`` feed text_preprocessor.inject_prosody(), which inserts comma
pauses before those words. Edge-TTS accepts plain text only — SSML is not
supported — so punctuation is the available prosody control.
"""

# Fallback used when a subject is missing or unknown.
DEFAULT_SUBJECT = "physics"

VOICE_MAP = {
    "physics": {
        "voice": "en-IN-NeerjaExpressiveNeural",  # Indian English — familiar to NEET students
        "rate": "+0%",   # normal speed for technical content
        "pitch": "+0Hz",
        "emphasis_words": ["NEET", "formula", "important", "remember", "units"],
    },
    "biology": {
        "voice": "en-IN-PrabhatNeural",
        "rate": "-5%",   # slightly slower for terminology
        "pitch": "+2Hz",
        "emphasis_words": ["NEET", "remember", "exception", "important", "NOT"],
    },
    "chemistry": {
        "voice": "en-IN-NeerjaExpressiveNeural",
        "rate": "-3%",   # slower for equations
        "pitch": "+0Hz",
        "emphasis_words": ["NEET", "mechanism", "remember", "important", "trend"],
    },
}

# Alternative voices kept for the multi-voice listening comparison (voice_eval.py).
CANDIDATE_VOICES = [
    "en-IN-NeerjaExpressiveNeural",
    "en-IN-NeerjaNeural",
    "en-IN-PrabhatNeural",
    "en-US-AriaNeural",
    "en-GB-SoniaNeural",
]


def get_voice_config(subject: str) -> dict:
    """Return the voice config for ``subject``, falling back to the default."""
    key = (subject or DEFAULT_SUBJECT).lower()
    config = VOICE_MAP.get(key, VOICE_MAP[DEFAULT_SUBJECT])
    # Copy so callers cannot mutate the shared map, and guarantee the key exists.
    config = dict(config)
    config.setdefault("emphasis_words", [])
    return config
