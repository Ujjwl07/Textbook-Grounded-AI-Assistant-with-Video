from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.rag.retriever import RetrievalResult, retriever
from app.utils.chunk_logger import chunk_logger
from app.database.qdrant import qdrant_db
from app.llm.gemini_service import gemini_service

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500, description="Question or topic to query from textbooks")
    subject: Optional[str] = Field(default=None, max_length=80, description="Optional subject filter (e.g. Physics)")
    class_level: Optional[str] = Field(default=None, max_length=40, description="Optional class level (e.g. 10, 11)")
    chapter_number: Optional[Union[str, int]] = Field(default=None, description="Optional chapter number filter")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of matching textbook chunks to extract")
    generate_answer: bool = Field(default=True, description="Whether to generate an LLM explanation with Gemini")


@router.post("", response_model=RetrievalResult)
@router.post("/ask", response_model=RetrievalResult)
async def ask_question(request: QueryRequest) -> RetrievalResult:
    """
    Ask a question against the NCERT textbook vector database.
    
    Extracts relevant chunks, logs them directly into the dedicated
    'retrieved_chunks.log' file, and returns the grounded Gemini answer, context, and chunks.
    """
    try:
        result = retriever.retrieve(
            query=request.query,
            top_k=request.top_k,
            subject=request.subject,
            class_level=request.class_level,
            chapter_number=request.chapter_number,
            caller="API:/query/ask",
            log_to_file=True,
        )

        if request.generate_answer and result.context_text:
            if not gemini_service.is_configured:
                result.answer = "Error: GEMINI_API_KEY is not configured in .env. Cannot generate AI explanation."
            else:
                try:
                    answer = await gemini_service.answer_question(
                        query=request.query,
                        retrieved_context=result.context_text,
                        subject=request.subject,
                        class_level=request.class_level,
                    )
                    result.answer = answer
                except Exception as e:
                    logger.error(f"Gemini generation error: {e}")
                    result.answer = f"Error: Gemini answer generation failed: {str(e)}"

        return result
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database query failed: {str(exc)}",
        )


@router.get("/chunks-log")
async def get_chunks_log(max_bytes: int = Query(default=16384, ge=1024, le=1048576)) -> Dict[str, Any]:
    """Retrieve the recent contents and path of the separate retrieved_chunks.log file."""
    log_content = chunk_logger.get_recent_log_content(max_bytes=max_bytes)
    return {
        "log_file_path": str(chunk_logger.log_file_path),
        "exists": chunk_logger.log_file_path.exists(),
        "size_bytes": chunk_logger.log_file_path.stat().st_size if chunk_logger.log_file_path.exists() else 0,
        "content": log_content,
    }


@router.get("/database-status")
async def get_database_status() -> Dict[str, Any]:
    """Get Qdrant collection status and diagnostic info."""
    return qdrant_db.get_collection_info()
