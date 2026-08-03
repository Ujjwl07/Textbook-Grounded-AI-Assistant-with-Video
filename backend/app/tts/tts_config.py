# tts_config.py — Subject-voice mapping
VOICE_MAP = {
    'physics': {
        'voice': 'en-IN-NeerjaExpressiveNeural',  # Indian English — familiar to NEET students
        'rate': '+0%',  # normal speed for technical content
        'pitch': '+0Hz',
        'emphasis_words': ['NEET', 'formula', 'important', 'remember'],
    },
    'biology': {
        'voice': 'en-IN-PrabhatNeural',
        'rate': '-5%',  # slightly slower for terminology
        'pitch': '+2Hz',
    },
    'chemistry': {
        'voice': 'en-IN-NeerjaExpressiveNeural',
        'rate': '-3%',  # slower for equations
        'pitch': '+0Hz',
    }
}
