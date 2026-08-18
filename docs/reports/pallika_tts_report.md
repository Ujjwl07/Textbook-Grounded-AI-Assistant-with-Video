# TTS & Audio Module — Implementation Report

**CPG-92 · Capstone 2026 · Thapar Institute of Engineering & Technology**
**Owner:** Pallika Malhotra (102313055) — TTS & Audio Developer
**Covers:** Guide Section 5.1 and Section 11.3 deliverables

---

## 1. Module map

| # | Deliverable | File | Status |
| --- | --- | --- | --- |
| 1 | Voice configuration map | `backend/app/tts/tts_config.py` | Done |
| 2 | Edge-TTS async generator with word-boundary timestamps | `backend/app/tts/tts_generator.py` | Done |
| 3 | Subject-specific text normalisation | `backend/app/tts/text_preprocessor.py` | Done |
| 4 | Audio post-processing | `backend/app/tts/audio_processor.py` | Done |
| 5 | Listener rating collection (MOS) | `backend/app/tts/voice_eval.py` | Harness done, ratings pending |
| 6 | Engine comparison | `backend/app/tts/multi_voice_test.py` | Done (Coqui optional) |
| 7 | This report | `docs/reports/pallika_tts_report.md` | Done |

Supporting script: `backend/scripts/demo_text_preprocessor.py` regenerates the
before/after expansion table used in Section 4.

---

## 2. Voice configuration and why the rates differ

All three subjects use Indian-English neural voices, which NEET aspirants find
easier to follow than US/UK accents. The speaking-rate choices are pedagogical,
not cosmetic:

| Subject | Voice | Rate | Pitch | Reason for the rate |
| --- | --- | --- | --- | --- |
| Physics | `en-IN-NeerjaExpressiveNeural` | +0% | +0Hz | Baseline. Numerical content is short-token and reads cleanly at normal speed. |
| Biology | `en-IN-PrabhatNeural` | −5% | +2Hz | Dense multi-syllable terminology ("oxidative phosphorylation", "zona pellucida") is unintelligible at full speed. |
| Chemistry | `en-IN-NeerjaExpressiveNeural` | −3% | +0Hz | Expanded reaction equations produce long uninterrupted token runs. |

### Prosody: why there is no SSML

Edge-TTS accepts **plain text only** — it does not expose SSML, so
`<emphasis>` and `<break>` tags are unavailable. Prosody is therefore shaped
through punctuation: `inject_prosody()` inserts a comma before each subject's
`emphasis_words`, which the engine renders as a short stressed pause.

Two guards prevent this from degrading the delivery:

* **Function-word veto** — no comma after a determiner or preposition, so
  "Remember the units" never becomes "Remember the, units".
* **Formula veto** — no comma after a single letter or a spelled number, so an
  expanded formula such as "S N one mechanism" is not split mid-term.

---

## 3. Text preprocessing — the core of this module

Feeding raw NCERT-grounded script text to a speech engine fails in ways that are
invisible until you listen: `v² = u² + 2as` is voiced as "v u as", `70S` becomes
"seventy-ess" or "seventy seconds", and LaTeX braces are read aloud as words.

`text_preprocessor.py` applies a shared normalisation pass followed by a
subject-specific pass:

```
strip_markup → expand_latex → expand_subscripts → [SUBJECT PASS]
             → expand_powers → expand_greek → expand_math_symbols
             → collapse_whitespace → inject_prosody
```

**Shared passes** handle LaTeX commands (`\frac`, `\sqrt`, `\vec`), Greek
letters (24 lower + 10 upper case), 21 mathematical operators, Unicode
super/subscripts, and vulgar fractions.

**Subject passes:**

* **Physics** — SI unit expansion (20 units), and splitting of glued variable
  products so `2as` is spoken "2 a s" rather than as the English word "as".
* **Chemistry** — stoichiometric coefficient detachment, a 17-entry named
  compound table (`H2O` → "water", not "H two O"), state symbols, ionic charges,
  mechanism names (`SN1` → "S N one"), and element-by-element spelling of
  unrecognised formulas.
* **Biology** — ribosome sizes (`70S` → "seventy S"), nucleic-acid
  abbreviations, and prime notation (`5'` → "five prime").

### Two bugs worth documenting

Both were found by running the demo script and inspecting output, and both
illustrate why naive regex substitution is insufficient.

**1. Unit expansion collided with subscripts.** After `m_1 m_2` expands to
`m 1 m 2`, a rule that expands "digit + m" as metres turns the second variable
into "1 metres 2". The fix is a lookbehind that rejects a digit preceded by a
*standalone single letter*, while still allowing ordinary prose ("of 5 m"):

```python
pattern = r"(?<!\s[A-Za-z]\s\d)(?<=\d)\s*" + re.escape(symbol) + r"\b(?!\s*\d)"
```

**2. The chemical formula speller mangled ordinary capitalised words.** A regex
matching "runs of element-like groups" treats `NEET` as N + E + E + T and voices
it "N E E T". The fix validates every group against a real element-symbol set
before spelling; `NEET`, `NCERT` and `IUPAC` now pass through untouched.

### Expansion examples

Full table: `backend/outputs/benchmarks/tts_expansion_examples.md`

| Subject | Raw text | Text sent to Edge-TTS |
| --- | --- | --- |
| Physics | `v² = u² + 2as` | v squared equals u squared plus 2 a s |
| Physics | `20 N acting on 4 kg ... 5 m/s2` | 20 newtons acting on 4 kilograms ... 5 metres per second squared |
| Physics | `F = G \frac{m_1 m_2}{r^2}` | F equals G m 1 m 2 upon r squared |
| Chemistry | `CH4 burns in O2 ... CO2 and H2O` | methane burns in oxygen ... carbon dioxide and water |
| Chemistry | `NaCl(aq) + AgNO3(aq) → AgCl(s)` | sodium chloride aqueous plus Ag N O three aqueous gives Ag Cl solid |
| Chemistry | `H2SO4 dehydrates C2H5OH at 443 K` | sulphuric acid dehydrates ethanol at 443 kelvin |
| Biology | `70S ribosomes, NOT 80S` | seventy S ribosomes, NOT eighty S |
| Biology | `5' to 3' direction` | five prime to three prime direction |

---

## 4. Audio post-processing

Edge-TTS output is not directly usable in a concatenated video: loudness varies
between voices, and each clip carries a variable lead-in and lead-out silence.
`audio_processor.py` applies three passes in order:

1. **High-pass filter at 80 Hz** — removes DC offset and sub-audible rumble.
2. **Silence trimming** — leading and trailing dead air removed at a −45 dBFS
   threshold, keeping 60 ms of padding so speech onset is never clipped.
3. **Loudness normalisation** — a fixed gain brings every clip to −16 LUFS,
   the standard target for spoken-word content.

### Timestamp correction — where this module meets the video module

Edge-TTS word timestamps are relative to the **untrimmed** audio. Trimming the
lead-in without correcting them makes every karaoke subtitle fire early by the
length of the removed silence — a defect that is invisible in the audio and only
appears in the final video.

`process_audio_file()` therefore returns `leading_trim_seconds`, and
`tts_generator` shifts every boundary by that amount via
`shift_word_boundaries()`, dropping any word that ended inside the removed
region. Measured on a sample physics scene: 0.13 s of lead-in trimmed, 0.85 s of
tail trimmed, +5.26 dB gain applied, and the first word timestamp corrected from
0.13 s to 0.00 s.

### Honest note on the loudness metric

True ITU-R BS.1770 LUFS metering requires `pyloudnorm`, which is listed as an
optional dependency. When it is absent the module falls back to pydub's RMS
`dBFS`, which approximates loudness but is **not** the same measurement. The
metric actually used is recorded in every result as `loudness_method`
(`pyloudnorm_lufs` or `pydub_dbfs`), so no report figure can silently overstate
its accuracy. Measurements in this report were taken with the `pydub_dbfs`
fallback.

---

## 5. Engine comparison

Command: `python backend/app/tts/multi_voice_test.py`
Raw data: `backend/outputs/benchmarks/tts_engine_comparison.json`
Audio samples: `backend/outputs/audio/engine_comparison/`

All engines receive **identically preprocessed text**, so the comparison
measures the engine rather than the normalisation.

| Engine | Mean latency | Mean RTF | Sample rate | Word timestamps | Offline | Indian-English voice |
| --- | --- | --- | --- | --- | --- | --- |
| **Edge-TTS** | **5.26 s** | **0.449** | 24 kHz | **Yes** | No | Yes |
| gTTS | 5.91 s | 0.503 | 24 kHz | No | No | Accent only (`tld=co.in`) |
| Coqui-TTS | not installed | — | — | No | Yes | No |

Per-subject latency (seconds):

| Engine | Physics | Biology | Chemistry |
| --- | --- | --- | --- |
| Edge-TTS | 12.31 | 1.95 | 1.53 |
| gTTS | 7.06 | 5.04 | 5.63 |

The Physics figure for Edge-TTS is a cold-start artefact — it is the first
request of the run and includes connection setup. Warm requests settle at
~1.5–2 s, roughly 3x faster than gTTS.

**Decision: Edge-TTS.** The deciding factor is not latency but
**word-boundary timestamps**, which neither gTTS nor Coqui provides. Without
them the karaoke subtitle engine (Section 11.4 #4) would have to estimate word
timings from character counts, and the highlight would drift over a 60-second
scene. Edge-TTS also offers genuine Indian-English neural voices, and separate
voices per subject.

Coqui-TTS is left as an optional dependency: it is the only offline engine and
would remove the network dependency, but it pulls in PyTorch (~2 GB), produces
US-accented output, and still provides no timestamps. The adapter is implemented
in `multi_voice_test.py`, so installing the package is sufficient to include it
in the comparison.

---

## 6. MOS listening test

`voice_eval.py` implements the three parts of the evaluation that need code, and
leaves the listening to humans:

```
python backend/app/tts/voice_eval.py build     # synthesise + write rating sheet
python backend/app/tts/voice_eval.py report    # MOS, SD, 95% CI, markdown table
```

**Built:** 15 samples (5 per subject) in `backend/outputs/audio/voice_eval/`.
The five scripts per subject deliberately span the notation the preprocessor
must handle — plain prose, a formula, a unit-heavy line, a term-dense line, and
a NEET-alert line.

**Blinding:** samples are given opaque IDs (`PHY01`, `BIO03`, …) and the rating
sheet presents them in a seeded shuffle, so a listener cannot tell which subject
or voice they are scoring, and cannot rate all Physics samples consecutively.

**Scale:** 1–5 on naturalness, clarity and pacing, for 10 listeners × 15 samples
= 450 ratings. `report` computes mean, standard deviation and a 95% confidence
interval per subject and per criterion, and writes
`backend/outputs/benchmarks/tts_mos_scores.md`.

> **Status: ratings not yet collected.** The harness is verified end-to-end
> against synthetic ratings, but the MOS table in the final report must be
> generated from real listener data. No MOS figures are quoted here.

---

## 7. Known limitations

1. **`pyloudnorm` not installed**, so loudness is measured as RMS dBFS rather
   than true LUFS. Installing the optional dependency upgrades this with no
   code change.
2. **Coqui-TTS not evaluated** — adapter written, package not installed.
3. **Ambiguous ASCII exponents.** `v2` is not expanded to "v squared" because it
   is indistinguishable from a variable named v2. Scripts should use `v²` or
   `v^2`, both of which are handled.
4. **Unknown chemical formulas are spelled, not named.** `AgNO3` becomes
   "Ag N O three" rather than "silver nitrate". Extending `COMMON_COMPOUNDS`
   covers any specific compound that matters for NEET.
5. **Network dependency.** Edge-TTS requires connectivity; there is no offline
   fallback until Coqui is installed.

---

## 8. Reproducing every figure in this report

```bash
python backend/scripts/demo_text_preprocessor.py     # Section 4 expansion table
python backend/app/tts/multi_voice_test.py           # Section 5 engine comparison
python backend/app/tts/voice_eval.py build           # Section 6 listening test
python backend/app/tts/voice_eval.py report          # Section 6 MOS table
```
