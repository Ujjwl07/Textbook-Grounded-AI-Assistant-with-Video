# Textbook-Grounded AI Assistant with Video

A capstone project that answers student queries using NCERT textbook content as context, generates spoken explanations via TTS, and produces short educational videos — all grounded in curriculum material.

---

## Project Structure

```
Textbook-Grounded-AI-Assistant-with-Video/
│
├── backend/
│   ├── app/                        # FastAPI application
│   │   ├── api/
│   │   │   └── routes/             # API route handlers (one file per feature)
│   │   ├── database/               # Qdrant client setup and query helpers
│   │   ├── llm/                    # LLM integration (prompt templates, Claude/GPT calls)
│   │   ├── rag/                    # RAG logic — retrieval, context assembly, reranking
│   │   ├── tts/                    # Text-to-speech generation
│   │   ├── utils/                  # Shared helpers (logging, config, validators)
│   │   └── video/
│   │       └── templates/          # Slide/video templates
│   │
│   ├── data/
│   │   ├── textbooks/              # Raw NCERT PDF files (gitignored — add locally)
│   │   └── vector_index/           # Local vector index cache (gitignored)
│   │
│   ├── outputs/
│   │   ├── audio/                  # Generated TTS audio files (gitignored)
│   │   ├── slides/                 # Generated slide images (gitignored)
│   │   └── videos/                 # Generated final videos (gitignored)
│   │
│   ├── scripts/
│   │   └── extract.py              # PDF ingestion pipeline → Qdrant
│   │
│   ├── .env.example                # Copy this to .env and fill in your keys
│   └── requirements.txt            # Python dependencies
│
├── frontend/
│   ├── public/                     # Static assets
│   └── src/
│       ├── components/             # Reusable UI components
│       ├── pages/                  # Page-level components (routes)
│       └── services/               # API calls to the backend
│
├── scripts/                        # Top-level utility scripts (setup, migrations, etc.)
├── tests/                          # Backend unit and integration tests
└── .gitignore
```

---

## Team Roles & Where to Work

| Role | Owner | Folder(s) |
|---|---|---|
| RAG & Pipeline | Ujjwal | `backend/scripts/`, `backend/app/rag/`, `backend/app/database/` |
| LLM Integration | — | `backend/app/llm/` |
| TTS & Video | — | `backend/app/tts/`, `backend/app/video/` |
| API / Backend | — | `backend/app/api/routes/` |
| Frontend | — | `frontend/src/` |

---

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/Ujjwl07/Textbook-Grounded-AI-Assistant-with-Video.git
cd Textbook-Grounded-AI-Assistant-with-Video
```

### 2. Set up Python environment

```bash
python -m venv venv
source venv/bin/activate      # Mac/Linux
venv\Scripts\activate         # Windows

pip install -r backend/requirements.txt
```

### 3. Configure environment variables

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` and fill in:

```
QDRANT_URL=https://your-cluster-id.region.cloud.qdrant.io
QDRANT_API_KEY=your_api_key_here
QDRANT_COLLECTION=textbook_chunks
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

> Get Qdrant credentials from the team lead (Ujjwal). Use read-only keys for development.

### 4. Add textbook PDFs

Place NCERT PDFs under `backend/data/textbooks/` following this folder structure:

```
backend/data/textbooks/
└── Class 10 Science Part 1/
    ├── 1-chemical-reactions.pdf
    ├── 2-acids-bases-salts.pdf
    └── ...
└── Class 10 Science Part 2/
    └── ...
```

The ingestion script auto-reads class, subject, part, and chapter number from the folder and file names — no manual mapping needed.

### 5. Run the ingestion pipeline (RAG setup)

```bash
# Ingest a single PDF
python backend/scripts/extract.py backend/data/textbooks/Class\ 10\ Science\ Part\ 1/1-chemical-reactions.pdf

# Ingest an entire directory
python backend/scripts/extract.py backend/data/textbooks/

# Force re-ingest (skip duplicate check)
python backend/scripts/extract.py backend/data/textbooks/ --force
```

---

## Module Details

### `backend/scripts/extract.py` — PDF Ingestion Pipeline
Parses NCERT PDFs → chunks text by markdown headers → embeds with `all-MiniLM-L6-v2` → stores in Qdrant Cloud.

- Uses `pymupdf4llm` for text extraction, falls back to PaddleOCR for scanned pages
- Skips answer keys and appendix files automatically
- Chunks tables row-by-row so each row is independently searchable
- Adds last 500 chars of previous chunk as context window

### `backend/app/database/` — Qdrant Client
Put Qdrant query helpers here. The collection is `textbook_chunks`. Each point has these payload fields:

| Field | Description |
|---|---|
| `pdf_name` | Stem of the source PDF |
| `class_level` | e.g. `"10"` |
| `subject` | e.g. `"Science"` |
| `part` | e.g. `"Part 1"` |
| `chapter_number` | Integer |
| `chapter_name` | e.g. `"Chemical Reactions"` |
| `section` | Markdown `##` header the chunk falls under |
| `chunk_type` | `"text"` or `"table_row"` |
| `content` | The actual chunk text |
| `previous_text` | Last 500 chars of the previous chunk (context) |

### `backend/app/rag/` — Retrieval Logic
Put the retrieval and context-assembly code here. Query flow:
1. Embed user query with the same `all-MiniLM-L6-v2` model
2. Search Qdrant with cosine similarity
3. Optionally filter by `class_level` / `subject`
4. Assemble top-k chunks into a prompt context

### `backend/app/llm/` — LLM Integration
Put prompt templates and LLM API calls here. The LLM receives the retrieved chunks as context and generates the answer.

### `backend/app/tts/` — Text-to-Speech
Takes the LLM answer and converts it to audio. Output files go to `backend/outputs/audio/`.

### `backend/app/video/` — Video Generation
Combines slides + audio into a short educational video. Output goes to `backend/outputs/videos/`.

### `backend/app/api/routes/` — API Endpoints
FastAPI routes. Each feature gets its own file, e.g. `query.py`, `video.py`, `health.py`.

### `frontend/src/` — React Frontend
- `components/` — shared UI pieces (chat bubble, video player, loader)
- `pages/` — full page views
- `services/` — `axios` / `fetch` wrappers for backend API calls

---

## Notes

- Never commit `backend/.env` — it's gitignored. Share credentials privately.
- `backend/data/textbooks/`, `backend/outputs/`, and `backend/data/vector_index/` are gitignored — generated or large files stay local.
- Each member installs their own dependencies; add new packages to `backend/requirements.txt` and commit it.
