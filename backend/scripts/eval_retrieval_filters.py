"""Before/after evidence for metadata-filtered retrieval (CPG-92, RAG module).

Runs a fixed set of NEET-style questions twice — once unfiltered (the behaviour
before this change) and once through NCERTRetriever's default NEET-scope filters
— and reports how often the top hit comes from the correct book.

Also prints corpus composition, which is the reason the filters are needed.

Run from the repo root:
    python backend/scripts/eval_retrieval_filters.py
    python backend/scripts/eval_retrieval_filters.py --create-indexes
"""

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.rag.retriever import NCERTRetriever  # noqa: E402

# Each case names the subject a NEET student is asking about and the class the
# correct answer must come from. `expect_chapter` is a substring match.
CASES = [
    {"query": "State Newton's universal law of gravitation",
     "subject": "Physics", "class_level": "11", "expect_chapter": "GRAVITATION"},
    {"query": "What is the SN1 mechanism in haloalkanes?",
     "subject": "Chemistry", "class_level": "12", "expect_chapter": "Haloalkanes"},
    {"query": "Explain the structure and function of DNA",
     "subject": "Biology", "class_level": "12", "expect_chapter": None},
    {"query": "What is the work energy theorem?",
     "subject": "Physics", "class_level": "11", "expect_chapter": "WORK ENERGY"},
    {"query": "Explain electrochemical cells and the Nernst equation",
     "subject": "Chemistry", "class_level": "12", "expect_chapter": "Electrochemistry"},
    {"query": "Describe Mendel's law of independent assortment",
     "subject": "Biology", "class_level": "12", "expect_chapter": "INHERITANCE"},
    {"query": "What is the photoelectric effect?",
     "subject": "Physics", "class_level": "12", "expect_chapter": "DUAL NATURE"},
    {"query": "Explain the kinetic theory of gases",
     "subject": "Physics", "class_level": "11", "expect_chapter": "KINETIC THEORY"},
]


def judge(chunk, case) -> tuple:
    """Return (ok, reason) for the top hit against the case's expectations."""
    if chunk is None:
        return False, "no results"
    if chunk.class_level not in ("11", "12"):
        return False, f"off-syllabus (Class {chunk.class_level})"
    if case["subject"] and chunk.subject.lower() != case["subject"].lower():
        return False, f"wrong subject ({chunk.subject})"
    if case["expect_chapter"] and case["expect_chapter"].lower() not in chunk.chapter_name.lower():
        return False, f"wrong chapter ({chunk.chapter_name[:28]})"
    return True, "correct book"


def run(retriever, case, filtered: bool):
    if filtered:
        result = retriever.search(
            case["query"], subject=case["subject"], class_level=case["class_level"], top_k=3
        )
    else:
        # Reproduces the old behaviour: no filters, all chunk types, all classes.
        result = retriever.search(
            case["query"], top_k=3, chunk_types=None, include_out_of_scope=True
        )
    return result.chunks[0] if result.chunks else None


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--create-indexes", action="store_true",
                        help="Create Qdrant payload indexes on the filtered fields")
    args = parser.parse_args()

    retriever = NCERTRetriever()

    print("=" * 78)
    print("RETRIEVAL FILTER EVALUATION — CPG-92")
    print("=" * 78)

    stats = retriever.corpus_stats()
    print(f"\nCorpus: {stats['total_points']} points")
    print(f"  by class      : {stats['by_class']}")
    print(f"  by subject    : {stats['by_subject']}")
    print(f"  by chunk_type : {stats['by_chunk_type']}")
    off_syllabus = stats["total_points"] - sum(
        v for k, v in stats["by_class"].items() if k in ("11", "12")
    )
    print(f"  off-syllabus (Class 9/10) : {off_syllabus} "
          f"({100 * off_syllabus / max(stats['total_points'], 1):.0f}%)")
    print(f"  retrievable by default    : {stats['retrievable_default']} "
          f"(Class 11-12 prose only)")

    if args.create_indexes:
        print("\nCreating payload indexes...")
        for field_name, status in retriever.ensure_payload_indexes().items():
            print(f"  {field_name:<14} {status}")

    rows = []
    unfiltered_ok = filtered_ok = 0

    for case in CASES:
        before = run(retriever, case, filtered=False)
        after = run(retriever, case, filtered=True)
        ok_before, why_before = judge(before, case)
        ok_after, why_after = judge(after, case)
        unfiltered_ok += ok_before
        filtered_ok += ok_after

        print(f"\n--- {case['query']}")
        print(f"  expect      : Class {case['class_level']} {case['subject']}"
              + (f", Ch. containing '{case['expect_chapter']}'" if case["expect_chapter"] else ""))
        mark = "PASS" if ok_before else "FAIL"
        print(f"  unfiltered  : [{mark}] {before.citation if before else '-'} "
              f"({before.score:.3f})" if before else f"  unfiltered  : [{mark}] no results")
        if not ok_before:
            print(f"                -> {why_before}")
        mark = "PASS" if ok_after else "FAIL"
        print(f"  filtered    : [{mark}] {after.citation if after else '-'} "
              f"({after.score:.3f})" if after else f"  filtered    : [{mark}] no results")
        if not ok_after:
            print(f"                -> {why_after}")

        rows.append({
            "query": case["query"],
            "expected_subject": case["subject"],
            "expected_class": case["class_level"],
            "unfiltered": {
                "citation": before.citation if before else None,
                "score": round(before.score, 3) if before else None,
                "correct": ok_before, "reason": why_before,
            },
            "filtered": {
                "citation": after.citation if after else None,
                "score": round(after.score, 3) if after else None,
                "correct": ok_after, "reason": why_after,
            },
        })

    total = len(CASES)
    print("\n" + "=" * 78)
    print(f"Top-1 correct book — unfiltered: {unfiltered_ok}/{total} "
          f"({100 * unfiltered_ok / total:.0f}%)")
    print(f"Top-1 correct book — filtered  : {filtered_ok}/{total} "
          f"({100 * filtered_ok / total:.0f}%)")
    print("=" * 78)

    out_path = BACKEND_DIR / "outputs" / "benchmarks" / "retrieval_filter_eval.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "corpus": stats,
        "hit_at_1_unfiltered": round(unfiltered_ok / total, 3),
        "hit_at_1_filtered": round(filtered_ok / total, 3),
        "cases": rows,
    }, indent=2), encoding="utf-8")
    print(f"JSON written to {out_path}")


if __name__ == "__main__":
    main()
