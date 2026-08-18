"""Subject-aware text normalisation for the TTS pipeline (Pallika, Section 11.3 #3).

Raw NCERT-grounded scripts contain notation a speech engine reads badly or not at
all: LaTeX fragments, Greek letters, chemical subscripts, unit symbols and maths
operators. Feeding "v² = u² + 2as" straight to Edge-TTS produces "v u as"; this
module turns it into "v squared equals u squared plus 2 a s".

The public entry point is ``preprocess(text, subject)``. Physics, Biology and
Chemistry each get their own rule pass on top of the shared normalisation, which
is why this is a module and not a one-line ``.replace()``.
"""

import re

# ---------------------------------------------------------------------------
# Shared vocabulary
# ---------------------------------------------------------------------------

NUMBER_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    "10": "ten", "11": "eleven", "12": "twelve",
}

GREEK_LETTERS = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa",
    "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "π": "pi",
    "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon", "φ": "phi",
    "χ": "chi", "ψ": "psi", "ω": "omega",
    "Γ": "capital gamma", "Δ": "delta", "Θ": "theta", "Λ": "lambda",
    "Ξ": "xi", "Π": "pi", "Σ": "sigma", "Φ": "phi", "Ψ": "psi", "Ω": "omega",
}

# Maths and physics symbols. Order matters: multi-character first.
MATH_SYMBOLS = [
    ("<=", " is less than or equal to "),
    (">=", " is greater than or equal to "),
    ("!=", " is not equal to "),
    ("≤", " is less than or equal to "),
    ("≥", " is greater than or equal to "),
    ("≠", " is not equal to "),
    ("≈", " is approximately "),
    ("∝", " is proportional to "),
    ("∴", " therefore "),
    ("∞", " infinity "),
    ("√", " square root of "),
    ("∑", " the sum of "),
    ("Σ", " the sum of "),
    ("∫", " the integral of "),
    ("∂", " partial "),
    ("±", " plus or minus "),
    ("→", " gives "),
    ("⇌", " is in equilibrium with "),
    ("↔", " reversible to "),
    ("×", " times "),
    ("÷", " divided by "),
    ("·", " dot "),
    ("°", " degrees "),
    ("%", " percent "),
    ("=", " equals "),
]

FRACTIONS = {
    "½": " half ", "⅓": " one third ", "¼": " one quarter ",
    "¾": " three quarters ", "⅔": " two thirds ",
}

SUPERSCRIPTS = {
    "²": " squared ", "³": " cubed ", "⁴": " to the power four ",
    "⁻": " to the power minus ", "¹": " to the power one ",
}

SUBSCRIPT_DIGITS = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
}

# SI units, expanded only when they directly follow a number so ordinary
# words ("N" in "N cases", "s" as a plural) are never mangled.
SI_UNITS = [
    ("m/s2", "metres per second squared"),
    ("m/s^2", "metres per second squared"),
    ("m/s", "metres per second"),
    ("km/h", "kilometres per hour"),
    ("kg", "kilograms"),
    ("cm", "centimetres"),
    ("mm", "millimetres"),
    ("km", "kilometres"),
    ("nm", "nanometres"),
    ("mol", "moles"),
    ("Hz", "hertz"),
    ("Pa", "pascals"),
    ("N", "newtons"),
    ("J", "joules"),
    ("W", "watts"),
    ("V", "volts"),
    ("A", "amperes"),
    ("K", "kelvin"),
    ("C", "coulombs"),
    ("g", "grams"),
    ("m", "metres"),
    ("s", "seconds"),
]

# ---------------------------------------------------------------------------
# Chemistry vocabulary
# ---------------------------------------------------------------------------

COMMON_COMPOUNDS = {
    "H2O": "water", "CO2": "carbon dioxide", "O2": "oxygen",
    "N2": "nitrogen", "H2": "hydrogen", "NH3": "ammonia",
    "CH4": "methane", "NaCl": "sodium chloride", "HCl": "hydrochloric acid",
    "H2SO4": "sulphuric acid", "HNO3": "nitric acid", "NaOH": "sodium hydroxide",
    "CaCO3": "calcium carbonate", "C6H12O6": "glucose", "C2H5OH": "ethanol",
    "KMnO4": "potassium permanganate", "CO": "carbon monoxide",
}

STATE_SYMBOLS = {
    "(aq)": " aqueous ", "(s)": " solid ", "(l)": " liquid ", "(g)": " gaseous ",
}

MECHANISM_NAMES = {
    "SN1": "S N one", "SN2": "S N two", "E1": "E one", "E2": "E two",
}

# Real element symbols. Without this check, the formula speller treats any
# run of capitals as a compound and turns "NEET" into "N E E T".
ELEMENT_SYMBOLS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "In", "Sn", "Sb", "Te", "I", "Xe",
    "Cs", "Ba", "La", "Ce", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn",
    "Fr", "Ra", "Ac", "Th", "U", "Np", "Pu",
    "W", "Re", "Os", "Ir", "Ta", "Hf",
}


def _is_chemical_formula(token: str) -> bool:
    """True when every element group in ``token`` is a real element symbol."""
    groups = re.findall(r"([A-Z][a-z]?)(\d*)", token)
    if not groups:
        return False
    consumed = "".join(sym + num for sym, num in groups)
    if consumed != token:
        return False
    return all(symbol in ELEMENT_SYMBOLS for symbol, _ in groups)

# ---------------------------------------------------------------------------
# Biology vocabulary — only terms Edge-TTS reliably gets wrong
# ---------------------------------------------------------------------------

BIOLOGY_TERMS = {
    "70S": "seventy S", "80S": "eighty S", "50S": "fifty S",
    "30S": "thirty S", "60S": "sixty S", "40S": "forty S",
    "5'": "five prime", "3'": "three prime",
    "mRNA": "messenger R N A", "tRNA": "transfer R N A", "rRNA": "ribosomal R N A",
    "NADPH": "N A D P H", "NADP": "N A D P", "ATP": "A T P", "ADP": "A D P",
    "DNA": "D N A", "RNA": "R N A",
    "F1": "F one", "F2": "F two",
}

# ---------------------------------------------------------------------------
# Shared passes
# ---------------------------------------------------------------------------


def strip_markup(text: str) -> str:
    """Remove markdown emphasis and stray label prefixes that reached the script."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"[*#`]", " ", text)
    # Leading part label such as "HOOK:" or "NEET ALERT:"
    text = re.sub(r"^\s*(HOOK|CONCEPT|EXAMPLE|MEMORY|NEET[ _]?ALERT)\s*:\s*", "", text, flags=re.I)
    return text


def expand_latex(text: str) -> str:
    """Turn common LaTeX fragments into spoken English."""
    text = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r" \1 upon \2 ", text)
    text = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r" square root of \1 ", text)
    text = re.sub(r"\\vec\s*\{([^{}]+)\}", r" vector \1 ", text)
    text = re.sub(r"\\(rightarrow|to)\b", " gives ", text)
    text = re.sub(r"\\(leftrightarrow|rightleftharpoons)\b", " is in equilibrium with ", text)
    text = re.sub(r"\\times\b", " times ", text)
    text = re.sub(r"\\div\b", " divided by ", text)
    text = re.sub(r"\\pm\b", " plus or minus ", text)
    text = re.sub(r"\\(alpha|beta|gamma|delta|theta|lambda|mu|pi|sigma|omega|phi)\b", r" \1 ", text)
    text = re.sub(r"\\[a-zA-Z]+", " ", text)      # any remaining command
    text = text.replace("$", " ")
    text = re.sub(r"[{}]", " ", text)
    return text


def expand_powers(text: str) -> str:
    """Expand caret powers and Unicode superscripts: x^2 -> x squared."""
    text = re.sub(r"\^\s*\{?\s*2\s*\}?", " squared ", text)
    text = re.sub(r"\^\s*\{?\s*3\s*\}?", " cubed ", text)
    text = re.sub(r"\^\s*\{?\s*-\s*(\d+)\s*\}?", r" to the power minus \1 ", text)
    text = re.sub(r"\^\s*\{?\s*(\d+)\s*\}?", r" to the power \1 ", text)
    for symbol, spoken in SUPERSCRIPTS.items():
        text = text.replace(symbol, spoken)
    for symbol, spoken in FRACTIONS.items():
        text = text.replace(symbol, spoken)
    return text


def expand_subscripts(text: str) -> str:
    """Convert Unicode subscripts to plain digits so later passes can see them."""
    for symbol, digit in SUBSCRIPT_DIGITS.items():
        text = text.replace(symbol, digit)
    # LaTeX-style underscore subscripts: m_1 -> m 1
    text = re.sub(r"_\s*\{?\s*([A-Za-z0-9]+)\s*\}?", r" \1 ", text)
    return text


def expand_greek(text: str) -> str:
    for symbol, spoken in GREEK_LETTERS.items():
        text = text.replace(symbol, f" {spoken} ")
    return text


def expand_math_symbols(text: str) -> str:
    for symbol, spoken in MATH_SYMBOLS:
        text = text.replace(symbol, spoken)
    # '+' and '-' only between operands, so hyphenated words survive
    text = re.sub(r"(?<=[\w\)])\s*\+\s*(?=[\w\(])", " plus ", text)
    text = re.sub(r"(?<=[\w\)])\s+-\s+(?=[\w\(])", " minus ", text)
    text = re.sub(r"(?<=\d)\s*/\s*(?=\d)", " over ", text)
    return text


def expand_units(text: str) -> str:
    """Expand SI unit symbols that directly follow a numeric value.

    Two guards keep subscripted variables safe. Expanded subscripts leave
    sequences like "m 1 m 2" (from m_1 m_2), where the trailing "m" is a
    variable, not metres:
      * the lookbehind rejects a digit preceded by a *standalone* single letter
        (" m 1"), while leaving ordinary prose ("of 5 m") alone
      * the lookahead rejects a unit that is followed by another number
    """
    for symbol, spoken in SI_UNITS:
        pattern = r"(?<!\s[A-Za-z]\s\d)(?<=\d)\s*" + re.escape(symbol) + r"\b(?!\s*\d)"
        text = re.sub(pattern, f" {spoken}", text)
    return text


def collapse_whitespace(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Subject-specific passes
# ---------------------------------------------------------------------------


def physics_pass(text: str) -> str:
    """Physics: units matter, and single-letter variables must not be glued."""
    text = expand_units(text)

    # Split glued variable products so "2as" is spoken "2 a s" rather than as
    # the English word "as". Runs after unit expansion so "20 N" is already gone.
    def split_variables(match):
        return match.group(1) + " " + " ".join(match.group(2))

    text = re.sub(r"\b(\d)([a-z]{1,3})\b", split_variables, text)
    return text


def _spell_element_group(match) -> str:
    """Render one 'element + optional subscript' pair, e.g. O3 -> 'O three'."""
    element, count = match.group(1), match.group(2)
    if not count:
        return element + " "
    return f"{element} {NUMBER_WORDS.get(count, count)} "


def chemistry_pass(text: str) -> str:
    """Chemistry: coefficients, compounds, state symbols, charges, mechanisms."""
    # 1. Detach stoichiometric coefficients so "3H2" becomes "3 H2" and the
    #    compound lookup below can see a clean formula token.
    text = re.sub(r"(?<![A-Za-z0-9])(\d+)(?=[A-Z])", r"\1 ", text)

    # 2. Named compounds win over letter-by-letter spelling.
    for formula, spoken in sorted(COMMON_COMPOUNDS.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(r"\b" + re.escape(formula) + r"\b", f" {spoken} ", text)

    for symbol, spoken in STATE_SYMBOLS.items():
        text = text.replace(symbol, spoken)

    for name, spoken in MECHANISM_NAMES.items():
        text = re.sub(r"\b" + re.escape(name) + r"\b", spoken, text)

    # 3. Ionic charges: Na+ -> Na ion
    text = re.sub(r"\b([A-Z][a-z]?)\s*\+\s*(?![\w])", r"\1 ion ", text)

    # 4. Unknown multi-element formulas (AgNO3, NaNO3, AgCl) are spelled out
    #    group by group. A plain \b...\d regex cannot do this because there is
    #    no word boundary between the element symbols inside a formula.
    def spell_unknown_formula(match):
        token = match.group(0)
        if not _is_chemical_formula(token):
            return token
        return re.sub(r"([A-Z][a-z]?)(\d*)", _spell_element_group, token).strip() + " "

    text = re.sub(r"\b(?:[A-Z][a-z]?\d*){2,}\b", spell_unknown_formula, text)

    # 5. Any remaining single element followed by a subscript count.
    def spell_single_element(match):
        if match.group(1) not in ELEMENT_SYMBOLS:
            return match.group(0)
        return _spell_element_group(match)

    text = re.sub(r"\b([A-Z][a-z]?)(\d+)", spell_single_element, text)

    # 6. Units last, so formula subscripts are already consumed (K, mol, Pa, g).
    text = expand_units(text)
    return text


def biology_pass(text: str) -> str:
    """Biology: ribosome sizes, nucleic-acid abbreviations, prime notation."""
    for term, spoken in sorted(BIOLOGY_TERMS.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(re.escape(term) + r"(?![A-Za-z])", spoken, text)
    text = expand_units(text)
    return text


SUBJECT_PASSES = {
    "physics": physics_pass,
    "chemistry": chemistry_pass,
    "biology": biology_pass,
}


# ---------------------------------------------------------------------------
# Prosody
# ---------------------------------------------------------------------------


# Function words that must never be separated from the noun they introduce.
# "Remember the units" must not become "Remember the, units".
PROSODY_STOP_WORDS = {
    "the", "a", "an", "of", "in", "on", "at", "for", "to", "and", "or", "but",
    "is", "are", "was", "were", "be", "with", "by", "as", "this", "that",
    "these", "those", "your", "our", "its", "their", "his", "her", "no", "not",
}


def inject_prosody(text: str, emphasis_words=None) -> str:
    """Insert comma pauses so the engine stresses key terms and breathes.

    Edge-TTS accepts plain text only (no SSML), so prosody is shaped through
    punctuation: a comma before an emphasis word buys a short pause that reads
    as stress, and a sentence-final full stop prevents run-on delivery.
    """
    if emphasis_words:
        emphasis_set = {w.lower() for w in emphasis_words}
        for word in emphasis_words:
            # Capture the preceding word so a determiner/preposition can veto
            # the comma; without this "the units" becomes "the, units".
            pattern = r"\b(\w+)\s+(" + re.escape(word) + r")\b"

            def add_pause(match):
                previous, target = match.group(1), match.group(2)
                # Veto after function words, and after the tail of an expanded
                # formula ("S N one mechanism") where a comma splits the term.
                if previous.lower() in PROSODY_STOP_WORDS:
                    return match.group(0)
                if len(previous) == 1 or previous.lower() in NUMBER_WORDS.values():
                    return match.group(0)
                # Two adjacent emphasis words need one pause, not two.
                if previous.lower() in emphasis_set:
                    return match.group(0)
                return f"{previous}, {target}"

            text = re.sub(pattern, add_pause, text, flags=re.IGNORECASE)

    text = re.sub(r"\s*:\s*", ", ", text)
    text = re.sub(r",\s*,+", ", ", text)
    text = collapse_whitespace(text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def preprocess(text: str, subject: str = "physics", emphasis_words=None) -> str:
    """Normalise ``text`` for speech synthesis using ``subject``'s rule set."""
    if not text:
        return ""

    subject_key = (subject or "physics").lower()
    if subject_key not in SUBJECT_PASSES:
        subject_key = "physics"

    text = strip_markup(text)
    text = expand_latex(text)
    text = expand_subscripts(text)
    text = SUBJECT_PASSES[subject_key](text)
    text = expand_powers(text)
    text = expand_greek(text)
    text = expand_math_symbols(text)
    text = collapse_whitespace(text)
    text = inject_prosody(text, emphasis_words)
    return text
