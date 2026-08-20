import logging
import sys
from typing import Optional


def setup_logging(level: str = "INFO", log_format: Optional[str] = None) -> logging.Logger:
    """Setup root logger with consistent structured formatting across the module."""
    if log_format is None:
        log_format = "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    root_logger = logging.getLogger("rag_llm_module")
    root_logger.setLevel(numeric_level)

    # Clear existing handlers to prevent duplicate logs
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    formatter = logging.Formatter(log_format)
    console_handler.setFormatter(formatter)
    
    root_logger.addHandler(console_handler)
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance scoped to a specific module name."""
    return logging.getLogger(f"rag_llm_module.{name}")
