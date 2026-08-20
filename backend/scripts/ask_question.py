#!/usr/bin/env python3
"""
Interactive & CLI tool for querying NCERT Textbook vector database.

Extracts matching chunks from Qdrant, displays them in the console,
and automatically appends full chunk contents and metadata to the dedicated
retrieved_chunks.log file.

Usage:
  # Single query:
  python backend/scripts/ask_question.py --query "What is Newton's third law?" --subject "Physics" --class-level "11"

  # Interactive mode:
  python backend/scripts/ask_question.py
"""

import os
import sys
from pathlib import Path

# Auto-activate project virtual environment if invoked with system python
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = WORKSPACE_ROOT / "venv" / "bin" / "python"
if VENV_PYTHON.exists() and sys.executable != str(VENV_PYTHON):
    current_prefix = Path(sys.prefix).resolve() if sys.prefix else None
    venv_prefix = (WORKSPACE_ROOT / "venv").resolve()
    if current_prefix != venv_prefix:
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

import argparse

# Add backend directory to sys.path if not present
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

from app.rag.retriever import retriever
from app.utils.chunk_logger import chunk_logger
from app.database.qdrant import qdrant_db
from app.llm.gemini_service import gemini_service
import asyncio


def print_banner():
    print("\n" + "=" * 80)
    print("  TEXTBOOK-GROUNDED AI ASSISTANT - DATABASE CHUNK INSPECTOR")
    print(f"  Log File Destination: {chunk_logger.log_file_path}")
    print(f"  LLM Provider        : Google Gemini ({gemini_service.model if gemini_service.is_configured else 'Not Configured'})")
    print("=" * 80 + "\n")


def execute_query(query: str, subject: str = None, class_level: str = None, chapter: str = None, top_k: int = 5, ask_llm: bool = True):
    print(f"\nSearching database for: \"{query}\"")
    filters = []
    if subject:
        filters.append(f"Subject={subject}")
    if class_level:
        filters.append(f"Class={class_level}")
    if chapter:
        filters.append(f"Chapter={chapter}")
    print(f"Filters: {', '.join(filters) if filters else 'None'} | Top K: {top_k}\n")

    try:
        result = retriever.retrieve(
            query=query,
            top_k=top_k,
            subject=subject,
            class_level=class_level,
            chapter_number=chapter,
            caller="CLI:ask_question.py",
            log_to_file=True,
        )
    except ConnectionError as conn_err:
        print("=" * 80)
        print("  [!] DATABASE CONNECTION ERROR:")
        print(f"      {conn_err}")
        print("      Check QDRANT_URL and QDRANT_API_KEY in backend/.env.")
        print("=" * 80 + "\n")
        return None
    except Exception as exc:
        print("=" * 80)
        print(f"  [!] DATABASE RETRIEVAL FAILED: {exc}")
        print("=" * 80 + "\n")
        return None

    print(f"Extracted {result.total_chunks} chunk(s) from database (Top Score: {result.top_score:.4f}):\n")

    if not result.chunks:
        print("  [!] No matching chunks found in Qdrant collection.")
        print("      (Make sure PDFs are ingested with extract.py and collection exists)\n")
    else:
        for idx, chunk in enumerate(result.chunks, start=1):
            ch_name = f"Ch {chunk.chapter_number} ({chunk.chapter_name})" if chunk.chapter_name else f"Ch {chunk.chapter_number or 'N/A'}"
            src = f"Class {chunk.class_level or 'N/A'} {chunk.subject or 'N/A'} - {ch_name}"
            
            print(f"  [{idx}] Score: {chunk.score:.4f} | {src}")
            print(f"      Section: {chunk.section or 'N/A'} | PDF: {chunk.pdf_name or 'N/A'} | Type: {chunk.chunk_type}")
            if chunk.previous_text:
                prev = chunk.previous_text.strip().replace("\n", " ")
                if len(prev) > 120:
                    prev = "..." + prev[-120:]
                print(f"      Pre-Context: {prev}")
            preview = chunk.content.strip().replace("\n", " ")
            if len(preview) > 200:
                preview = preview[:200] + "..."
            print(f"      Content: {preview}")
            print()

    print(f"--> Full chunk text and metadata logged to: {result.log_file_path}\n")

    if ask_llm:
        if not gemini_service.is_configured:
            print("=" * 80)
            print("  [!] LLM CONFIGURATION ERROR:")
            print("      GEMINI_API_KEY is not configured in backend/.env.")
            print("      Add GEMINI_API_KEY=<your_key> to backend/.env to generate AI explanations.")
            print("=" * 80 + "\n")
        elif result.context_text:
            print("=" * 80)
            print("  GEMINI AI GROUNDED EXPLANATION:")
            print("=" * 80)
            try:
                answer = asyncio.run(gemini_service.answer_question(
                    query=query,
                    retrieved_context=result.context_text,
                    subject=subject,
                    class_level=class_level,
                ))
                print(answer)
                print("=" * 80 + "\n")
            except Exception as err:
                print(f"  [!] Gemini Generation Failed: {err}\n")

    return result


def interactive_mode():
    print_banner()
    print("Interactive Mode. Type your question (or 'exit' / 'quit' to stop).\n")
    
    default_subject = None
    default_class = None

    while True:
        try:
            query = input("Ask a question > ").strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break
            if query.startswith(":subject "):
                default_subject = query.split(" ", 1)[1].strip() or None
                print(f"Default subject set to: {default_subject}")
                continue
            if query.startswith(":class "):
                default_class = query.split(" ", 1)[1].strip() or None
                print(f"Default class set to: {default_class}")
                continue
            if query.startswith(":status"):
                status = qdrant_db.get_collection_info()
                print(f"Qdrant status: {status}")
                continue

            execute_query(
                query=query,
                subject=default_subject,
                class_level=default_class,
            )
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break


def main():
    parser = argparse.ArgumentParser(description="Ask questions and extract chunks from NCERT textbook database.")
    parser.add_argument("--query", "-q", type=str, help="Question or topic to search")
    parser.add_argument("--subject", "-s", type=str, default=None, help="Filter by subject (e.g. Physics, Chemistry)")
    parser.add_argument("--class-level", "-c", type=str, default=None, help="Filter by class level (e.g. 10, 11)")
    parser.add_argument("--chapter", type=str, default=None, help="Filter by chapter number")
    parser.add_argument("--top-k", "-k", type=int, default=5, help="Number of chunks to retrieve (default: 5)")
    parser.add_argument("--status", action="store_true", help="Check Qdrant database status")

    args = parser.parse_args()

    if args.status:
        print_banner()
        status = qdrant_db.get_collection_info()
        print(f"Qdrant collection status: {status}\n")
        return

    if args.query:
        print_banner()
        execute_query(
            query=args.query,
            subject=args.subject,
            class_level=args.class_level,
            chapter=args.chapter,
            top_k=args.top_k,
        )
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
