"""
Script Generator Module for RAG Educational Platform.

Generates structured NEET teaching scripts using LLMs with strict section validation,
word count constraints (250-320 words), context grounding, retry policies, metrics,
token usage tracking, latency calculation, cost estimation, streaming support, and DI.
"""

from __future__ import annotations
import os
import re
import time
import json
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple, AsyncGenerator, Set
from pydantic import BaseModel, Field, ConfigDict, field_validator

from prompt_manager import PromptManager, Prompt

# Configure logger
logger = logging.getLogger("script_generator")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ============================================================================
# Domain Models & DTOs
# ============================================================================

class ScriptSection(BaseModel):
    """Represents an individual section in the teaching script."""
    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Section title e.g., HOOK, CONCEPT, EXAMPLE, MEMORY, NEET ALERT")
    content: str = Field(..., description="Text content of the section")
    word_count: int = Field(..., ge=0, description="Word count for this section")


class ScriptMetrics(BaseModel):
    """Metrics tracking execution latency, token counts, and cost estimation."""
    latency_sec: float = Field(..., ge=0.0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)


class ScriptValidationResult(BaseModel):
    """Validation report detailing compliance with constraints."""
    is_valid: bool
    word_count: int
    missing_sections: List[str] = Field(default_factory=list)
    word_count_valid: bool = True
    context_grounded: bool = True
    errors: List[str] = Field(default_factory=list)


class Script(BaseModel):
    """Complete Output Script Object."""
    subject: str
    topic: str
    chapter: str
    class_num: int
    hook: str
    concept: str
    example: str
    memory: str
    neet_alert: str
    full_text: str
    sections: List[ScriptSection]
    total_word_count: int
    metrics: ScriptMetrics
    validation: ScriptValidationResult

    def to_json(self, indent: int = 2) -> str:
        """Serialize script object to pretty JSON string."""
        return self.model_dump_json(indent=indent)


# ============================================================================
# LLM Client Protocol & Implementation
# ============================================================================

class LLMResponse(BaseModel):
    """Response payload returned by LLMClient."""
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_sec: float


class LLMClient(ABC):
    """Abstract interface for LLM client providers."""

    @abstractmethod
    async def generate(self, prompt: str, temperature: float = 0.2) -> LLMResponse:
        """Generate text completion from prompt."""
        pass

    @abstractmethod
    async def generate_stream(self, prompt: str, temperature: float = 0.2) -> AsyncGenerator[str, None]:
        """Stream text completion chunks."""
        pass


class OpenAIClient(LLMClient):
    """Production OpenAI LLM client supporting async generation, retries, and streaming."""

    MODEL_PRICING_PER_1K = {
        "gpt-4o": {"input": 0.0025, "output": 0.0100},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-4-turbo": {"input": 0.0100, "output": 0.0300},
    }

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o", max_retries: int = 3, backoff_factor: float = 1.5):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key)
            except ImportError:
                logger.warning("OpenAI package not installed. OpenAILLMClient requires 'pip install openai'.")
                self._client = None
        return self._client

    async def generate(self, prompt: str, temperature: float = 0.2) -> LLMResponse:
        client = self._get_client()
        if not client or not self.api_key:
            # Fallback to mock behavior if key or package unavailable
            logger.info("OpenAI API key missing or package unavailable. Executing Mock completion.")
            return await MockLLMClient().generate(prompt, temperature)

        start_time = time.time()
        attempt = 0
        last_exception = None

        while attempt < self.max_retries:
            try:
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                )
                latency = time.time() - start_time
                usage = response.usage
                p_tokens = usage.prompt_tokens if usage else len(prompt) // 4
                c_tokens = usage.completion_tokens if usage else len(response.choices[0].message.content or "") // 4

                return LLMResponse(
                    text=response.choices[0].message.content or "",
                    prompt_tokens=p_tokens,
                    completion_tokens=c_tokens,
                    total_tokens=p_tokens + c_tokens,
                    latency_sec=round(latency, 3),
                )
            except Exception as e:
                attempt += 1
                last_exception = e
                wait_time = self.backoff_factor ** attempt
                logger.warning(f"OpenAI API attempt {attempt}/{self.max_retries} failed: {e}. Retrying in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)

        raise RuntimeError(f"OpenAI generation failed after {self.max_retries} retries: {last_exception}")

    async def generate_stream(self, prompt: str, temperature: float = 0.2) -> AsyncGenerator[str, None]:
        client = self._get_client()
        if not client or not self.api_key:
            async for chunk in MockLLMClient().generate_stream(prompt, temperature):
                yield chunk
            return

        response = await client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            stream=True,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class MockLLMClient(LLMClient):
    """Deterministic Mock LLM Client for testing and offline execution."""

    async def generate(self, prompt: str, temperature: float = 0.2) -> LLMResponse:
        start_time = time.time()
        await asyncio.sleep(0.1)  # Simulate network latency

        mock_text = (
            "HOOK:\n"
            "Imagine a spacecraft floating in deep interstellar space with its engines turned off. Why does it keep moving indefinitely without slowing down? "
            "It is not engine power keeping it in motion, but the fundamental property of inertia defined in NCERT Physics!\n\n"
            "CONCEPT:\n"
            "Newton's First Law of Motion states that every body continues in its state of rest or of uniform motion in a straight line unless compelled by a net external force to change that state. "
            "Inertia is the inherent physical property of a body by virtue of which it actively resists any alteration in its state of rest or uniform velocity. "
            "Crucially, mass is the quantitative measure of inertia. A body with greater mass possesses proportionally greater inertia, requiring a larger external net force to produce the same change in motion.\n\n"
            "EXAMPLE:\n"
            "Consider a 10 kg bowling ball and a 0.1 kg tennis ball resting on a frictionless table. To accelerate both at 5 m/s², the 10 kg ball requires 50 N of net force while the tennis ball requires only 0.5 N, "
            "directly demonstrating that higher mass equals greater inertia.\n\n"
            "MEMORY:\n"
            "Inertia resists state change; Net Force causes state change. Remember: Mass is the quantitative measure of Inertia—higher mass means higher resistance to velocity changes!\n\n"
            "NEET ALERT:\n"
            "In NEET statement-based questions, NTA often tricks students by stating velocity quantifies inertia. Remember: Mass, NOT velocity or momentum, is the sole quantitative measure of inertia according to NCERT!"
        )

        latency = time.time() - start_time
        return LLMResponse(
            text=mock_text,
            prompt_tokens=350,
            completion_tokens=280,
            total_tokens=630,
            latency_sec=round(latency, 3),
        )

    async def generate_stream(self, prompt: str, temperature: float = 0.2) -> AsyncGenerator[str, None]:
        res = await self.generate(prompt, temperature)
        words = res.text.split(" ")
        for i in range(0, len(words), 5):
            chunk = " ".join(words[i:i+5]) + " "
            await asyncio.sleep(0.02)
            yield chunk


# ============================================================================
# Script Parser
# ============================================================================

class ScriptParser:
    """Parses raw text LLM output into structured script sections."""

    REQUIRED_SECTIONS = ["HOOK", "CONCEPT", "EXAMPLE", "MEMORY", "NEET ALERT"]

    @classmethod
    def parse(cls, raw_text: str) -> Tuple[Dict[str, str], List[ScriptSection]]:
        """
        Parses HOOK, CONCEPT, EXAMPLE, MEMORY, NEET ALERT sections from raw output string.
        """
        parsed_dict: Dict[str, str] = {}
        sections_list: List[ScriptSection] = []

        # Regular expression matching section headers e.g. "HOOK:" or "[HOOK]" at the start of a line or block
        pattern = r"(?:^|\n)(?:\[?)(HOOK|CONCEPT|EXAMPLE|MEMORY|NEET ALERT)(?:\]?):?"
        splits = re.split(pattern, raw_text, flags=re.IGNORECASE)

        if len(splits) >= 3:
            # First element before first header (usually empty)
            for i in range(1, len(splits), 2):
                section_name = splits[i].strip().upper()
                section_content = splits[i+1].strip() if i+1 < len(splits) else ""
                
                parsed_dict[section_name] = section_content
                words = len(section_content.split()) if section_content else 0
                sections_list.append(ScriptSection(name=section_name, content=section_content, word_count=words))
        else:
            # Fallback if text format lacked explicit headers
            parsed_dict["CONCEPT"] = raw_text.strip()
            words = len(raw_text.split())
            sections_list.append(ScriptSection(name="CONCEPT", content=raw_text.strip(), word_count=words))

        return parsed_dict, sections_list


# ============================================================================
# Script Validator
# ============================================================================

class ScriptValidator:
    """Validates word count (250-320 words), section presence, and context grounding."""

    MIN_WORDS = 250
    MAX_WORDS = 320
    REQUIRED_SECTIONS = ["HOOK", "CONCEPT", "EXAMPLE", "MEMORY", "NEET ALERT"]

    @classmethod
    def validate(
        cls,
        parsed_sections: Dict[str, str],
        full_text: str,
        retrieved_context: str,
    ) -> ScriptValidationResult:
        errors = []
        
        # 1. Missing Section Detection
        missing = [sec for sec in cls.REQUIRED_SECTIONS if sec not in parsed_sections or not parsed_sections[sec].strip()]
        if missing:
            errors.append(f"Missing required sections: {missing}")

        # 2. Word Count Validation
        total_words = len(full_text.split())
        word_count_valid = cls.MIN_WORDS <= total_words <= cls.MAX_WORDS
        if not word_count_valid:
            errors.append(f"Word count {total_words} is outside valid range ({cls.MIN_WORDS}-{cls.MAX_WORDS} words).")

        # 3. Context Grounding / Hallucination Check (Heuristic Token Overlap)
        context_words = set(re.findall(r"\w+", retrieved_context.lower()))
        script_words = set(re.findall(r"\w+", full_text.lower())) - {"hook", "concept", "example", "memory", "neet", "alert"}
        
        overlap = len(script_words.intersection(context_words)) / max(len(script_words), 1)
        context_grounded = overlap >= 0.35  # Overlap threshold
        if not context_grounded:
            errors.append(f"Low context overlap ({overlap:.2f}). Possible hallucination detected.")

        is_valid = (len(missing) == 0) and word_count_valid and context_grounded

        return ScriptValidationResult(
            is_valid=is_valid,
            word_count=total_words,
            missing_sections=missing,
            word_count_valid=word_count_valid,
            context_grounded=context_grounded,
            errors=errors,
        )


# ============================================================================
# Response Formatter
# ============================================================================

class ResponseFormatter:
    """Handles JSON serialization and output formatting for Script objects."""

    @staticmethod
    def format_to_dict(script: Script) -> Dict[str, Any]:
        """Convert Script model to standard dictionary."""
        return script.model_dump()

    @staticmethod
    def format_to_json(script: Script, indent: int = 2) -> str:
        """Convert Script model to JSON string."""
        return script.to_json(indent=indent)


# ============================================================================
# Script Generator Orchestrator
# ============================================================================

class ScriptGenerator:
    """
    Main orchestrator for educational script generation.
    Integrates PromptManager, LLMClient, ScriptParser, ScriptValidator, and ResponseFormatter.
    """

    def __init__(
        self,
        prompt_manager: Optional[PromptManager] = None,
        llm_client: Optional[LLMClient] = None,
        parser: Optional[ScriptParser] = None,
        validator: Optional[ScriptValidator] = None,
    ):
        self.prompt_manager = prompt_manager or PromptManager(prompts_dir="prompts")
        self.llm_client = llm_client or OpenAIClient()
        self.parser = parser or ScriptParser()
        self.validator = validator or ScriptValidator()

    @staticmethod
    def _calculate_cost(prompt_tokens: int, completion_tokens: int, model: str = "gpt-4o") -> float:
        """Calculate estimated cost in USD based on model pricing."""
        pricing = OpenAIClient.MODEL_PRICING_PER_1K.get(model, {"input": 0.0025, "output": 0.0100})
        input_cost = (prompt_tokens / 1000.0) * pricing["input"]
        output_cost = (completion_tokens / 1000.0) * pricing["output"]
        return round(input_cost + output_cost, 6)

    async def generate_script(
        self,
        subject: str,
        topic: str,
        chapter: str,
        class_num: int,
        retrieved_context: str,
        prompt_version: str = "v1",
        temperature: float = 0.2,
    ) -> Script:
        """
        Generates a complete, validated NEET teaching script.

        Args:
            subject: Academic subject (e.g., 'Physics', 'Biology', 'Chemistry')
            topic: Specific topic title
            chapter: Chapter title or name
            class_num: Target grade (1-12)
            retrieved_context: Retrieved NCERT context string
            prompt_version: Prompt version ('v1', 'v2', etc.)
            temperature: LLM temperature parameter

        Returns:
            Validated Script domain model.
        """
        logger.info(f"Generating script for Subject: {subject}, Topic: {topic}, Grade: Class {class_num}")

        # 1. Fetch & Render Prompt
        prompt_obj: Prompt = self.prompt_manager.get_prompt(
            prompt_name="master",
            version=prompt_version,
            subject=subject,
            topic=topic,
            chapter_name=chapter,
            chapter_num=1,
            class_num=class_num,
            retrieved_context=retrieved_context,
        )

        # 2. Invoke LLM Client with Retry Policy
        llm_response: LLMResponse = await self.llm_client.generate(
            prompt=prompt_obj.content,
            temperature=temperature,
        )

        # 3. Parse Output Sections
        parsed_dict, sections_list = self.parser.parse(llm_response.text)

        # 4. Extract individual sections
        hook = parsed_dict.get("HOOK", "")
        concept = parsed_dict.get("CONCEPT", "")
        example = parsed_dict.get("EXAMPLE", "")
        memory = parsed_dict.get("MEMORY", "")
        neet_alert = parsed_dict.get("NEET ALERT", "")

        # 5. Validate Constraints (Word count, missing sections, grounding)
        validation_res = self.validator.validate(
            parsed_sections=parsed_dict,
            full_text=llm_response.text,
            retrieved_context=retrieved_context,
        )

        # 6. Compute Metrics & Cost
        cost = self._calculate_cost(llm_response.prompt_tokens, llm_response.completion_tokens)
        metrics = ScriptMetrics(
            latency_sec=llm_response.latency_sec,
            prompt_tokens=llm_response.prompt_tokens,
            completion_tokens=llm_response.completion_tokens,
            total_tokens=llm_response.total_tokens,
            estimated_cost_usd=cost,
        )

        # 7. Construct Final Script Object
        script_obj = Script(
            subject=subject,
            topic=topic,
            chapter=chapter,
            class_num=class_num,
            hook=hook,
            concept=concept,
            example=example,
            memory=memory,
            neet_alert=neet_alert,
            full_text=llm_response.text,
            sections=sections_list,
            total_word_count=validation_res.word_count,
            metrics=metrics,
            validation=validation_res,
        )

        logger.info(f"Script generated successfully. Total Words: {validation_res.word_count}, Valid: {validation_res.is_valid}")
        return script_obj

    async def generate_script_stream(
        self,
        subject: str,
        topic: str,
        chapter: str,
        class_num: int,
        retrieved_context: str,
        prompt_version: str = "v1",
        temperature: float = 0.2,
    ) -> AsyncGenerator[str, None]:
        """
        Streams generated script content chunks in real time.
        """
        prompt_obj: Prompt = self.prompt_manager.get_prompt(
            prompt_name="master",
            version=prompt_version,
            subject=subject,
            topic=topic,
            chapter_name=chapter,
            chapter_num=1,
            class_num=class_num,
            retrieved_context=retrieved_context,
        )

        async for chunk in self.llm_client.generate_stream(prompt=prompt_obj.content, temperature=temperature):
            yield chunk
