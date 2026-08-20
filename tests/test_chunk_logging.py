import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure backend directory is in path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.utils.chunk_logger import ChunkLogger, ExtractedChunk
from app.rag.retriever import TextbookRetriever, RetrievalResult
from app.database.qdrant import QdrantDatabase
from fastapi.testclient import TestClient
from app.main import app


class TestChunkLogging(unittest.TestCase):

    def test_chunk_logger_writes_to_separate_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file = Path(tmp_dir) / "test_retrieved_chunks.log"
            logger = ChunkLogger(log_file_path=log_file)

            sample_chunks = [
                ExtractedChunk(
                    chunk_id="chunk-001",
                    score=0.9254,
                    content="Newton's first law states that an object remains at rest unless acted upon by a force.",
                    pdf_name="laws-of-motion.pdf",
                    class_level="11",
                    subject="Physics",
                    part="Part 1",
                    chapter_number=5,
                    chapter_name="Laws of Motion",
                    section="5.2 First Law of Motion",
                    chunk_type="text",
                    previous_text="Inertia is the fundamental property of matter that opposes changes in motion.",
                ),
                ExtractedChunk(
                    chunk_id="chunk-002",
                    score=0.8710,
                    content="Momentum is defined as the product of mass and velocity: p = mv.",
                    pdf_name="laws-of-motion.pdf",
                    class_level="11",
                    subject="Physics",
                    part="Part 1",
                    chapter_number=5,
                    chapter_name="Laws of Motion",
                    section="5.3 Momentum",
                    chunk_type="text",
                ),
            ]

            query = "What is Newton's first law and momentum?"
            filters = {"subject": "Physics", "class_level": "11"}

            formatted_block = logger.log_retrieved_chunks(
                query=query,
                chunks=sample_chunks,
                filters=filters,
                caller="test_runner",
            )

            self.assertTrue(log_file.exists(), "Log file was not created")
            log_content = log_file.read_text(encoding="utf-8")

            # Verify key elements in log file
            self.assertIn("DATABASE CHUNK EXTRACTION EVENT", log_content)
            self.assertIn(query, log_content)
            self.assertIn("subject=Physics", log_content)
            self.assertIn("Class 11 Physics", log_content)
            self.assertIn("Laws of Motion", log_content)
            self.assertIn("0.9254", log_content)
            self.assertIn("0.8710", log_content)
            self.assertIn("Newton's first law states", log_content)
            self.assertIn("p = mv", log_content)
            self.assertIn("Inertia is the fundamental property", log_content)

            # Verify reading helper
            recent = logger.get_recent_log_content()
            self.assertIn(query, recent)

    def test_retriever_context_assembly(self):
        retriever = TextbookRetriever()
        sample_chunks = [
            ExtractedChunk(
                score=0.9,
                content="Cell is the basic structural and functional unit of life.",
                class_level="9",
                subject="Science",
                chapter_number=5,
                chapter_name="Fundamental Unit of Life",
                section="5.1 What are living organisms made of?",
            )
        ]
        context = retriever.assemble_context(sample_chunks)
        self.assertIn("Class 9 Science", context)
        self.assertIn("Cell is the basic structural", context)

    def test_api_query_routes(self):
        client = TestClient(app)

        # Test chunks-log endpoint
        res_log = client.get("/api/query/chunks-log")
        self.assertEqual(res_log.status_code, 200)
        data = res_log.json()
        self.assertIn("log_file_path", data)
        self.assertIn("content", data)

        # Test database-status endpoint
        res_status = client.get("/api/query/database-status")
        self.assertEqual(res_status.status_code, 200)
        status_data = res_status.json()
        self.assertIn("collection_name", status_data)

        # Test query/ask endpoint
        res_query = client.post(
            "/api/query/ask",
            json={
                "query": "What is photosynthesis?",
                "subject": "Biology",
                "class_level": "10",
                "top_k": 3,
            },
        )
        self.assertEqual(res_query.status_code, 200)
        query_data = res_query.json()
        self.assertEqual(query_data["query"], "What is photosynthesis?")
        self.assertIn("chunks", query_data)
        self.assertIn("log_file_path", query_data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
