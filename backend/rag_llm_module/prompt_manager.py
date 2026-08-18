"""
Prompt Manager Module for RAG Educational Platform.

Provides dynamic loading, versioning, placeholder validation, subject selection,
automatic subject addendum injection, caching, and prompt formatting.
"""

from __future__ import annotations
import os
import re
import json
import hashlib
import difflib
import logging
import functools
import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set, Union
from pydantic import BaseModel, Field, ConfigDict, field_validator

# Configure module logger
logger = logging.getLogger("prompt_manager")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ============================================================================
# Exceptions
# ============================================================================

class PromptException(Exception):
    """Base exception for all prompt manager errors."""
    pass


class PromptNotFoundError(PromptException):
    """Raised when a requested prompt file or version is missing."""
    def __init__(self, prompt_name: str, version: str, path: str):
        self.prompt_name = prompt_name
        self.version = version
        self.path = path
        super().__init__(f"Prompt '{prompt_name}' version '{version}' not found at path: '{path}'.")


class InvalidPromptVersionError(PromptException):
    """Raised when an unsupported or malformed version string is provided."""
    def __init__(self, version: str):
        self.version = version
        super().__init__(f"Invalid prompt version format: '{version}'. Expected format 'v1', 'v2', etc.")


class PromptValidationError(PromptException):
    """Raised when template placeholders or input parameters fail validation."""
    pass


class PromptFormatError(PromptException):
    """Raised when variable substitution into template string fails."""
    pass


# ============================================================================
# Domain Models & Value Objects
# ============================================================================

class PromptVersion(BaseModel):
    """
    Value object representing prompt semantic versioning (e.g. 'v1', 'v2', 'v3').
    Supports string representation and sorting comparison.
    """
    model_config = ConfigDict(frozen=True)

    version_str: str = Field(..., description="Version string identifier (e.g. 'v1', 'v2')")

    @field_validator("version_str")
    @classmethod
    def validate_version_format(cls, v: str) -> str:
        if not re.match(r"^v\d+$", v):
            raise InvalidPromptVersionError(v)
        return v

    @property
    def number(self) -> int:
        """Numeric version index (e.g., v2 -> 2)."""
        return int(self.version_str.lstrip("v"))

    def __lt__(self, other: PromptVersion) -> bool:
        return self.number < other.number

    def __str__(self) -> str:
        return self.version_str


class Prompt(BaseModel):
    """
    Immutable Prompt object returned after template resolution, subject addendum injection,
    and placeholder substitution.
    """
    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Base prompt identifier (e.g. 'master', 'scene', 'quiz')")
    version: str = Field(..., description="Prompt version string (e.g. 'v1')")
    subject: Optional[str] = Field(default=None, description="Target subject if applied (e.g. 'Physics')")
    template_raw: str = Field(..., description="Raw template body before formatting")
    content: str = Field(..., description="Final rendered prompt text after formatting")
    placeholders: Set[str] = Field(default_factory=set, description="Extracted variable placeholders")
    applied_addendum: bool = Field(default=False, description="Whether a subject addendum was injected")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution and resolution metadata")

    def __repr__(self) -> str:
        return f"<Prompt name='{self.name}' version='{self.version}' subject='{self.subject}' len={len(self.content)}>"


# ============================================================================
# Core Components
# ============================================================================

class PromptValidator:
    """
    Validates prompt templates and placeholder variable requirements.
    """

    PLACEHOLDER_REGEX = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
    STANDARD_PLACEHOLDERS: Set[str] = {
        "subject",
        "topic",
        "chapter_name",
        "chapter_num",
        "class_num",
        "retrieved_context",
    }

    @classmethod
    def extract_placeholders(cls, template_text: str) -> Set[str]:
        """Extract all `{variable}` names from template string."""
        return set(cls.PLACEHOLDER_REGEX.findall(template_text))

    @classmethod
    def validate_placeholders(cls, template_text: str, allowed_placeholders: Optional[Set[str]] = None) -> Set[str]:
        """
        Validates placeholder syntax in template string and returns detected set.
        """
        placeholders = cls.extract_placeholders(template_text)
        if allowed_placeholders:
            unknown = placeholders - allowed_placeholders
            if unknown:
                logger.warning(f"Template contains non-standard placeholders: {unknown}")
        return placeholders

    @classmethod
    def validate_input_variables(cls, required_placeholders: Set[str], provided_vars: Dict[str, Any]) -> None:
        """
        Ensures all required placeholders are present in provided variables.
        """
        missing = required_placeholders - set(provided_vars.keys())
        if missing:
            err_msg = f"Missing required prompt variables: {sorted(list(missing))}"
            logger.error(err_msg)
            raise PromptValidationError(err_msg)


class PromptLoader:
    """
    Loads raw prompt template files dynamically from disk.
    Directory structure expected: `<prompts_dir>/<version>/<prompt_name>.prompt`
    """

    def __init__(self, base_dir: str = "prompts"):
        self.base_dir = os.path.abspath(base_dir)

    def load_raw_prompt(self, prompt_name: str, version: str) -> str:
        """
        Loads raw text content of specified prompt file.
        """
        # Standardize prompt filename extension (.prompt)
        clean_name = prompt_name.lower().removesuffix(".prompt")
        filename = f"{clean_name}.prompt"
        file_path = os.path.join(self.base_dir, version, filename)

        if not os.path.isfile(file_path):
            logger.error(f"Prompt file missing: {file_path}")
            raise PromptNotFoundError(prompt_name, version, file_path)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                logger.debug(f"Loaded raw prompt '{clean_name}' (version '{version}') from {file_path}")
                return content
        except Exception as e:
            logger.error(f"Failed reading prompt file {file_path}: {e}")
            raise PromptException(f"Error reading prompt file {file_path}: {e}") from e

    def list_available_versions(self) -> List[str]:
        """
        Scans base directory for available version folders ('v1', 'v2', etc.).
        """
        if not os.path.isdir(self.base_dir):
            return []

        versions = []
        for entry in os.listdir(self.base_dir):
            full_path = os.path.join(self.base_dir, entry)
            if os.path.isdir(full_path) and re.match(r"^v\d+$", entry):
                versions.append(entry)

        versions.sort(key=lambda v: int(v.lstrip("v")))
        return versions

    def get_latest_version(self) -> str:
        """Returns the highest available version string."""
        versions = self.list_available_versions()
        if not versions:
            raise PromptException(f"No prompt versions found in directory '{self.base_dir}'.")
        return versions[-1]


class PromptRegistry:
    """
    Catalog registry tracking available prompts, versions, and subject addendums.
    """

    def __init__(self, loader: PromptLoader):
        self.loader = loader
        self._registry: Dict[str, List[str]] = {}
        self.refresh()

    def refresh(self) -> None:
        """Scans disk to populate registry index."""
        self._registry.clear()
        versions = self.loader.list_available_versions()
        for v in versions:
            version_dir = os.path.join(self.loader.base_dir, v)
            prompts = []
            for fname in os.listdir(version_dir):
                if fname.endswith(".prompt"):
                    prompts.append(fname.removesuffix(".prompt"))
            self._registry[v] = prompts
        logger.info(f"PromptRegistry index refreshed: {len(self._registry)} versions registered.")

    def has_prompt(self, prompt_name: str, version: str) -> bool:
        """Check if prompt exists in registry."""
        clean_name = prompt_name.lower().removesuffix(".prompt")
        return version in self._registry and clean_name in self._registry[version]

    def has_subject_addendum(self, subject: str, version: str) -> bool:
        """Check if subject addendum prompt exists for subject (e.g. 'physics')."""
        return self.has_prompt(subject, version)


class PromptFormatter:
    """
    Formats template strings with input kwargs and appends subject addendums.
    """

    @classmethod
    def format_template(
        self,
        template_text: str,
        addendum_text: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Performs string format substitution and appends optional subject addendum.
        """
        combined = template_text
        if addendum_text:
            combined = f"{template_text}\n\n{addendum_text}"

        try:
            rendered = combined.format(**kwargs)
            return rendered
        except KeyError as e:
            err = f"Missing placeholder argument during formatting: {e}"
            logger.error(err)
            raise PromptFormatError(err) from e
        except Exception as e:
            err = f"Formatting template failed: {e}"
            logger.error(err)
            raise PromptFormatError(err) from e


# ============================================================================
# Prompt Version History Manager
# ============================================================================

@dataclass(frozen=True)
class PromptVersionMetadata:
    """Metadata stored for every prompt version snapshot."""
    prompt_name: str
    version: str
    author: str
    timestamp_utc: str
    content_hash: str
    performance: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    source_version: Optional[str] = None
    operation: str = "save"


@dataclass(frozen=True)
class PromptEdit:
    """A tracked edit between two prompt versions."""
    prompt_name: str
    from_version: Optional[str]
    to_version: str
    author: str
    timestamp_utc: str
    notes: str
    changed_lines: int
    added_lines: int
    removed_lines: int
    diff: List[str]


@dataclass(frozen=True)
class PromptComparison:
    """Structured prompt comparison result."""
    prompt_name: str
    from_version: str
    to_version: str
    similarity_score: float
    changed_lines: int
    added_lines: int
    removed_lines: int
    diff: List[str]
    performance_delta: Dict[str, Any]


class PromptVersionManager:
    """
    Production-ready prompt version manager.

    Responsibilities:
        - store prompt versions as `prompts/<version>/<prompt>.prompt`
        - auto-save metadata (author, timestamp, performance, notes, hash)
        - track edits with unified diffs
        - compare any two versions
        - rollback by creating a new version from a prior version
        - generate changelogs
        - export the complete registry as JSON
    """

    REGISTRY_FILENAME = ".prompt_versions.json"

    def __init__(self, prompts_dir: str = "prompts", registry_filename: str = REGISTRY_FILENAME):
        self.prompts_dir = os.path.abspath(prompts_dir)
        self.registry_path = os.path.join(self.prompts_dir, registry_filename)
        os.makedirs(self.prompts_dir, exist_ok=True)
        self._registry: Dict[str, Any] = self._load_registry()
        self.sync_from_disk()

    def list_versions(self, prompt_name: Optional[str] = None) -> List[str]:
        """Return sorted versions, optionally limited to versions containing a prompt."""
        versions: Set[str] = set()
        if prompt_name:
            clean_name = self._clean_prompt_name(prompt_name)
            for version, prompt_map in self._registry.get("prompts", {}).items():
                if clean_name in prompt_map:
                    versions.add(version)
        else:
            versions.update(self._registry.get("prompts", {}).keys())
        return sorted(versions, key=self._version_number)

    def get_metadata(self, prompt_name: str, version: str) -> PromptVersionMetadata:
        """Return metadata for one prompt version."""
        clean_name = self._clean_prompt_name(prompt_name)
        self._validate_version(version)
        try:
            return PromptVersionMetadata(**self._registry["prompts"][version][clean_name]["metadata"])
        except KeyError as exc:
            raise PromptNotFoundError(clean_name, version, self._prompt_path(clean_name, version)) from exc

    def save_version(
        self,
        prompt_name: str,
        content: str,
        version: Optional[str] = None,
        author: str = "unknown",
        performance: Optional[Dict[str, Any]] = None,
        notes: str = "",
        source_version: Optional[str] = None,
        overwrite: bool = False,
    ) -> PromptVersionMetadata:
        """
        Save a prompt version and track the edit.

        If `version` is omitted, the next numeric version (`v3`, `v4`, ...)
        is chosen. Existing versions are immutable unless `overwrite=True`.
        """
        clean_name = self._clean_prompt_name(prompt_name)
        if not content or not content.strip():
            raise PromptValidationError("Prompt content must be non-empty.")

        target_version = version or self.get_next_version()
        self._validate_version(target_version)
        prompt_path = self._prompt_path(clean_name, target_version)
        if os.path.exists(prompt_path) and not overwrite:
            raise PromptException(
                f"Prompt '{clean_name}' version '{target_version}' already exists. "
                "Pass overwrite=True to replace it."
            )

        old_content = ""
        if source_version:
            old_content = self.load_prompt(clean_name, source_version)
        elif os.path.exists(prompt_path):
            old_content = self._read_file(prompt_path)
        else:
            latest = self.get_latest_version(clean_name, default=None)
            if latest:
                old_content = self.load_prompt(clean_name, latest)
                source_version = latest

        os.makedirs(os.path.dirname(prompt_path), exist_ok=True)
        with open(prompt_path, "w", encoding="utf-8") as handle:
            handle.write(content.rstrip() + "\n")

        metadata = PromptVersionMetadata(
            prompt_name=clean_name,
            version=target_version,
            author=author,
            timestamp_utc=self._utc_now(),
            content_hash=self._hash_content(content),
            performance=performance or {},
            notes=notes,
            source_version=source_version,
            operation="overwrite" if overwrite else "save",
        )
        edit = self._build_edit(
            prompt_name=clean_name,
            from_version=source_version,
            to_version=target_version,
            old_content=old_content,
            new_content=content,
            author=author,
            notes=notes,
        )
        self._upsert_record(metadata, edit)
        self._save_registry()
        return metadata

    def rollback(
        self,
        prompt_name: str,
        target_version: str,
        new_version: Optional[str] = None,
        author: str = "unknown",
        notes: str = "",
    ) -> PromptVersionMetadata:
        """
        Roll back by copying `target_version` into a fresh version.

        This preserves history and avoids silently destroying newer prompts.
        """
        clean_name = self._clean_prompt_name(prompt_name)
        content = self.load_prompt(clean_name, target_version)
        rollback_version = new_version or self.get_next_version()
        metadata = self.save_version(
            prompt_name=clean_name,
            content=content,
            version=rollback_version,
            author=author,
            notes=notes or f"Rollback to {target_version}.",
            source_version=target_version,
            overwrite=False,
        )
        self._registry["prompts"][rollback_version][clean_name]["metadata"]["operation"] = "rollback"
        self._save_registry()
        return PromptVersionMetadata(**self._registry["prompts"][rollback_version][clean_name]["metadata"])

    def compare_prompts(self, prompt_name: str, from_version: str, to_version: str) -> PromptComparison:
        """Compare two prompt versions using line diff and token cosine similarity."""
        clean_name = self._clean_prompt_name(prompt_name)
        old_content = self.load_prompt(clean_name, from_version)
        new_content = self.load_prompt(clean_name, to_version)
        diff = self._unified_diff(old_content, new_content, from_version, to_version)
        added, removed = self._line_change_counts(diff)
        similarity = self._cosine_similarity(old_content, new_content)
        return PromptComparison(
            prompt_name=clean_name,
            from_version=from_version,
            to_version=to_version,
            similarity_score=similarity,
            changed_lines=added + removed,
            added_lines=added,
            removed_lines=removed,
            diff=diff,
            performance_delta=self._performance_delta(clean_name, from_version, to_version),
        )

    def generate_changelog(self, prompt_name: Optional[str] = None) -> str:
        """Generate a Markdown changelog for all prompts or one prompt."""
        lines = ["# Prompt Version Changelog", ""]
        versions = self.list_versions(prompt_name)
        for version in versions:
            prompt_records = self._registry.get("prompts", {}).get(version, {})
            relevant_names = [self._clean_prompt_name(prompt_name)] if prompt_name else sorted(prompt_records)
            for name in relevant_names:
                record = prompt_records.get(name)
                if not record:
                    continue
                meta = record["metadata"]
                lines.append(f"## {name} {version}")
                lines.append(f"- Author: {meta.get('author', 'unknown')}")
                lines.append(f"- Timestamp: {meta.get('timestamp_utc', '')}")
                lines.append(f"- Operation: {meta.get('operation', 'save')}")
                if meta.get("source_version"):
                    lines.append(f"- Source Version: {meta['source_version']}")
                if meta.get("performance"):
                    lines.append(f"- Performance: {json.dumps(meta['performance'], sort_keys=True)}")
                if meta.get("notes"):
                    lines.append(f"- Notes: {meta['notes']}")
                edit = record.get("edit", {})
                lines.append(
                    f"- Changes: +{edit.get('added_lines', 0)} "
                    f"/ -{edit.get('removed_lines', 0)} lines"
                )
                lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def export_json(self, prompt_name: Optional[str] = None, indent: int = 2) -> str:
        """Export complete version history as JSON."""
        data = self.to_dict(prompt_name=prompt_name)
        return json.dumps(data, indent=indent, sort_keys=True)

    def to_dict(self, prompt_name: Optional[str] = None) -> Dict[str, Any]:
        """Return the registry as a JSON-serialisable dictionary."""
        if not prompt_name:
            return self._registry
        clean_name = self._clean_prompt_name(prompt_name)
        filtered: Dict[str, Any] = {
            "schema_version": self._registry.get("schema_version", 1),
            "generated_at_utc": self._utc_now(),
            "prompts": {},
        }
        for version, prompt_map in self._registry.get("prompts", {}).items():
            if clean_name in prompt_map:
                filtered["prompts"][version] = {clean_name: prompt_map[clean_name]}
        return filtered

    def load_prompt(self, prompt_name: str, version: str) -> str:
        """Load raw prompt text from disk."""
        clean_name = self._clean_prompt_name(prompt_name)
        self._validate_version(version)
        prompt_path = self._prompt_path(clean_name, version)
        if not os.path.isfile(prompt_path):
            raise PromptNotFoundError(clean_name, version, prompt_path)
        return self._read_file(prompt_path)

    def get_latest_version(self, prompt_name: Optional[str] = None, default: Optional[str] = None) -> Optional[str]:
        """Return latest version globally or for a prompt."""
        versions = self.list_versions(prompt_name=prompt_name)
        return versions[-1] if versions else default

    def get_next_version(self) -> str:
        """Return the next global vN version."""
        versions = self.list_versions()
        if not versions:
            return "v1"
        return f"v{self._version_number(versions[-1]) + 1}"

    def sync_from_disk(self) -> None:
        """Discover prompt files on disk and backfill metadata for every version."""
        changed = False
        prompts_registry = self._registry.setdefault("prompts", {})
        for version in self._discover_versions():
            prompts_registry.setdefault(version, {})
            version_dir = os.path.join(self.prompts_dir, version)
            for filename in sorted(os.listdir(version_dir)):
                if not filename.endswith(".prompt"):
                    continue
                prompt_name = filename.removesuffix(".prompt")
                prompt_path = os.path.join(version_dir, filename)
                content = self._read_file(prompt_path)
                content_hash = self._hash_content(content)
                existing = prompts_registry[version].get(prompt_name)
                if existing and existing.get("metadata", {}).get("content_hash") == content_hash:
                    continue
                metadata = PromptVersionMetadata(
                    prompt_name=prompt_name,
                    version=version,
                    author=existing.get("metadata", {}).get("author", "system") if existing else "system",
                    timestamp_utc=existing.get("metadata", {}).get("timestamp_utc", self._utc_now()) if existing else self._utc_now(),
                    content_hash=content_hash,
                    performance=existing.get("metadata", {}).get("performance", {}) if existing else {},
                    notes=existing.get("metadata", {}).get("notes", "Discovered existing prompt file.") if existing else "Discovered existing prompt file.",
                    source_version=existing.get("metadata", {}).get("source_version") if existing else None,
                    operation=existing.get("metadata", {}).get("operation", "discover") if existing else "discover",
                )
                edit = PromptEdit(
                    prompt_name=prompt_name,
                    from_version=None,
                    to_version=version,
                    author=metadata.author,
                    timestamp_utc=metadata.timestamp_utc,
                    notes=metadata.notes,
                    changed_lines=0,
                    added_lines=0,
                    removed_lines=0,
                    diff=[],
                )
                prompts_registry[version][prompt_name] = {
                    "metadata": self._dataclass_to_dict(metadata),
                    "edit": self._dataclass_to_dict(edit),
                }
                changed = True
        if changed:
            self._save_registry()

    def _load_registry(self) -> Dict[str, Any]:
        if not os.path.isfile(self.registry_path):
            return {"schema_version": 1, "generated_at_utc": self._utc_now(), "prompts": {}}
        try:
            with open(self.registry_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            data.setdefault("schema_version", 1)
            data.setdefault("generated_at_utc", self._utc_now())
            data.setdefault("prompts", {})
            return data
        except json.JSONDecodeError as exc:
            raise PromptException(f"Invalid prompt version registry JSON: {self.registry_path}") from exc

    def _save_registry(self) -> None:
        self._registry["generated_at_utc"] = self._utc_now()
        with open(self.registry_path, "w", encoding="utf-8") as handle:
            json.dump(self._registry, handle, indent=2, sort_keys=True)
            handle.write("\n")

    def _upsert_record(self, metadata: PromptVersionMetadata, edit: PromptEdit) -> None:
        self._registry.setdefault("prompts", {}).setdefault(metadata.version, {})[metadata.prompt_name] = {
            "metadata": self._dataclass_to_dict(metadata),
            "edit": self._dataclass_to_dict(edit),
        }

    def _build_edit(
        self,
        prompt_name: str,
        from_version: Optional[str],
        to_version: str,
        old_content: str,
        new_content: str,
        author: str,
        notes: str,
    ) -> PromptEdit:
        diff = self._unified_diff(old_content, new_content, from_version or "new", to_version)
        added, removed = self._line_change_counts(diff)
        return PromptEdit(
            prompt_name=prompt_name,
            from_version=from_version,
            to_version=to_version,
            author=author,
            timestamp_utc=self._utc_now(),
            notes=notes,
            changed_lines=added + removed,
            added_lines=added,
            removed_lines=removed,
            diff=diff,
        )

    def _performance_delta(self, prompt_name: str, from_version: str, to_version: str) -> Dict[str, Any]:
        old_perf = self.get_metadata(prompt_name, from_version).performance
        new_perf = self.get_metadata(prompt_name, to_version).performance
        delta: Dict[str, Any] = {}
        for key in sorted(set(old_perf) | set(new_perf)):
            old_val = old_perf.get(key)
            new_val = new_perf.get(key)
            if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                delta[key] = round(new_val - old_val, 6)
            elif old_val != new_val:
                delta[key] = {"from": old_val, "to": new_val}
        return delta

    @staticmethod
    def _unified_diff(old_content: str, new_content: str, from_label: str, to_label: str) -> List[str]:
        return list(
            difflib.unified_diff(
                old_content.splitlines(),
                new_content.splitlines(),
                fromfile=str(from_label),
                tofile=str(to_label),
                lineterm="",
            )
        )

    @staticmethod
    def _line_change_counts(diff: List[str]) -> tuple[int, int]:
        added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
        return added, removed

    @staticmethod
    def _cosine_similarity(text1: str, text2: str) -> float:
        tokens1 = re.findall(r"[a-z0-9]+", text1.lower())
        tokens2 = re.findall(r"[a-z0-9]+", text2.lower())
        if not tokens1 or not tokens2:
            return 0.0
        counts1 = {token: tokens1.count(token) for token in set(tokens1)}
        counts2 = {token: tokens2.count(token) for token in set(tokens2)}
        vocab = set(counts1) | set(counts2)
        dot = sum(counts1.get(token, 0) * counts2.get(token, 0) for token in vocab)
        mag1 = sum(value ** 2 for value in counts1.values()) ** 0.5
        mag2 = sum(value ** 2 for value in counts2.values()) ** 0.5
        return round(dot / (mag1 * mag2), 4) if mag1 and mag2 else 0.0

    def _discover_versions(self) -> List[str]:
        if not os.path.isdir(self.prompts_dir):
            return []
        versions = [
            name for name in os.listdir(self.prompts_dir)
            if os.path.isdir(os.path.join(self.prompts_dir, name)) and re.match(r"^v\d+$", name)
        ]
        return sorted(versions, key=self._version_number)

    def _prompt_path(self, prompt_name: str, version: str) -> str:
        return os.path.join(self.prompts_dir, version, f"{prompt_name}.prompt")

    @staticmethod
    def _clean_prompt_name(prompt_name: str) -> str:
        return prompt_name.lower().removesuffix(".prompt").strip()

    @staticmethod
    def _validate_version(version: str) -> None:
        PromptVersion(version_str=version)

    @staticmethod
    def _version_number(version: str) -> int:
        return int(version.lstrip("v"))

    @staticmethod
    def _hash_content(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _utc_now() -> str:
        return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    @staticmethod
    def _read_file(path: str) -> str:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    @staticmethod
    def _dataclass_to_dict(instance: Any) -> Dict[str, Any]:
        return dict(instance.__dict__)


class PromptManager:
    """
    Faceted Prompt Manager orchestrating dynamic loading, version management,
    subject selection, automatic subject addendum injection, validation, and caching.
    """

    SUPPORTED_PROMPTS = {"master", "scene", "quiz", "physics", "biology", "chemistry"}

    def __init__(self, prompts_dir: str = "prompts", cache_enabled: bool = True):
        self.prompts_dir = prompts_dir
        self.cache_enabled = cache_enabled
        self.loader = PromptLoader(base_dir=prompts_dir)
        self.registry = PromptRegistry(loader=self.loader)
        self.validator = PromptValidator()
        self.formatter = PromptFormatter()
        self._cache: Dict[str, Prompt] = {}

    def clear_cache(self) -> None:
        """Clear cached prompt objects."""
        self._cache.clear()
        logger.info("PromptManager cache cleared.")

    def get_prompt(
        self,
        prompt_name: str,
        version: Optional[str] = None,
        subject: Optional[str] = None,
        auto_addendum: bool = True,
        **kwargs: Any,
    ) -> Prompt:
        """
        Main entrypoint to fetch, format, and return a Prompt object.

        Args:
            prompt_name: Identifier ('master', 'physics', 'scene', 'quiz', etc.)
            version: Target version string ('v1', 'v2', etc.). Defaults to latest.
            subject: Subject identifier ('Physics', 'Biology', 'Chemistry').
            auto_addendum: Automatically append subject addendum if available.
            **kwargs: Placeholder variables ({subject}, {topic}, {chapter_name}, etc.)

        Returns:
            Prompt object containing rendered content and metadata.
        """
        clean_name = prompt_name.lower().removesuffix(".prompt")

        # Resolve version
        if not version or version == "latest":
            version = self.loader.get_latest_version()

        # Validate version format
        PromptVersion(version_str=version)

        # Infer subject from kwargs if not explicitly passed
        target_subject = subject or kwargs.get("subject")
        if target_subject and "subject" not in kwargs:
            kwargs["subject"] = target_subject

        # Generate cache key
        cache_key = f"{clean_name}:{version}:{target_subject}:{auto_addendum}:{hash(frozenset(kwargs.items()))}"
        if self.cache_enabled and cache_key in self._cache:
            logger.debug(f"Cache HIT for prompt '{clean_name}:{version}'")
            return self._cache[cache_key]

        # 1. Load Raw Base Prompt
        base_raw = self.loader.load_raw_prompt(clean_name, version)

        # 2. Check for Automatic Subject Addendum
        addendum_raw: Optional[str] = None
        applied_addendum = False
        if auto_addendum and target_subject:
            subject_clean = str(target_subject).lower()
            if self.registry.has_subject_addendum(subject_clean, version):
                addendum_raw = self.loader.load_raw_prompt(subject_clean, version)
                applied_addendum = True
                logger.info(f"Automatically injecting subject addendum '{subject_clean}' for prompt '{clean_name}'")

        # 3. Combine raw templates & extract placeholders
        full_raw = f"{base_raw}\n\n{addendum_raw}" if addendum_raw else base_raw
        placeholders = self.validator.validate_placeholders(full_raw)

        # 4. Validate input kwargs against required placeholders
        if placeholders:
            self.validator.validate_input_variables(placeholders, kwargs)

        # 5. Format Prompt
        rendered_content = self.formatter.format_template(
            template_text=base_raw,
            addendum_text=addendum_raw,
            **kwargs,
        )

        # 6. Construct Prompt Object
        prompt_obj = Prompt(
            name=clean_name,
            version=version,
            subject=target_subject,
            template_raw=full_raw,
            content=rendered_content,
            placeholders=placeholders,
            applied_addendum=applied_addendum,
            metadata={
                "base_prompt": clean_name,
                "version": version,
                "subject": target_subject,
                "placeholders_count": len(placeholders),
                "kwargs_keys": list(kwargs.keys()),
            },
        )

        # Store in cache
        if self.cache_enabled:
            self._cache[cache_key] = prompt_obj

        logger.info(f"Successfully generated Prompt object for '{clean_name}' ({version})")
        return prompt_obj


def build_prompt_version_cli_parser() -> Any:
    """Build CLI parser lazily so importing prompt_manager stays lightweight."""
    import argparse

    parser = argparse.ArgumentParser(description="Manage prompt versions and history.")
    parser.add_argument("--prompts-dir", default="prompts", help="Prompt directory root.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List known prompt versions.").add_argument(
        "--prompt", help="Optional prompt name filter."
    )

    save_parser = subparsers.add_parser("save", help="Save a prompt version.")
    save_parser.add_argument("prompt_name")
    save_parser.add_argument("--content-file", required=True)
    save_parser.add_argument("--version")
    save_parser.add_argument("--author", default="unknown")
    save_parser.add_argument("--notes", default="")
    save_parser.add_argument("--performance-json", default="{}")
    save_parser.add_argument("--overwrite", action="store_true")

    rollback_parser = subparsers.add_parser("rollback", help="Rollback to a prior version as a new version.")
    rollback_parser.add_argument("prompt_name")
    rollback_parser.add_argument("target_version")
    rollback_parser.add_argument("--new-version")
    rollback_parser.add_argument("--author", default="unknown")
    rollback_parser.add_argument("--notes", default="")

    compare_parser = subparsers.add_parser("compare", help="Compare two prompt versions.")
    compare_parser.add_argument("prompt_name")
    compare_parser.add_argument("from_version")
    compare_parser.add_argument("to_version")

    changelog_parser = subparsers.add_parser("changelog", help="Generate Markdown changelog.")
    changelog_parser.add_argument("--prompt")

    export_parser = subparsers.add_parser("export", help="Export prompt history JSON.")
    export_parser.add_argument("--prompt")
    export_parser.add_argument("--output")
    return parser


def prompt_version_cli(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point for PromptVersionManager."""
    parser = build_prompt_version_cli_parser()
    args = parser.parse_args(argv)
    manager = PromptVersionManager(prompts_dir=args.prompts_dir)

    try:
        if args.command == "list":
            print(json.dumps(manager.list_versions(prompt_name=args.prompt), indent=2))
        elif args.command == "save":
            content = PromptVersionManager._read_file(args.content_file)
            performance = json.loads(args.performance_json)
            metadata = manager.save_version(
                prompt_name=args.prompt_name,
                content=content,
                version=args.version,
                author=args.author,
                performance=performance,
                notes=args.notes,
                overwrite=args.overwrite,
            )
            print(json.dumps(PromptVersionManager._dataclass_to_dict(metadata), indent=2, sort_keys=True))
        elif args.command == "rollback":
            metadata = manager.rollback(
                prompt_name=args.prompt_name,
                target_version=args.target_version,
                new_version=args.new_version,
                author=args.author,
                notes=args.notes,
            )
            print(json.dumps(PromptVersionManager._dataclass_to_dict(metadata), indent=2, sort_keys=True))
        elif args.command == "compare":
            comparison = manager.compare_prompts(args.prompt_name, args.from_version, args.to_version)
            print(json.dumps(PromptVersionManager._dataclass_to_dict(comparison), indent=2, sort_keys=True))
        elif args.command == "changelog":
            print(manager.generate_changelog(prompt_name=args.prompt), end="")
        elif args.command == "export":
            payload = manager.export_json(prompt_name=args.prompt)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.write("\n")
            else:
                print(payload)
        return 0
    except Exception as exc:
        print(f"prompt version manager error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(prompt_version_cli())
