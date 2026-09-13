"""
Memory Export Service

Generates a structured memory.md file with all 13 memory types
organized into sections, ready for agent consumption.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from memanto.app.config import get_data_dir
from memanto.app.models.session import AgentAvatar
from memanto.app.utils.validation import validate_output_path, validate_safe_id

# First line of an export when the agent has an avatar (see persona_line()).
PERSONA_PREFIX = "Du sprichst als "

# Memory type metadata: (label, emoji, description)
MEMORY_TYPE_META = {
    "fact": (
        "Facts",
        "Verified information, project status, and established truths.",
    ),
    "preference": (
        "Preferences",
        "User and entity preferences for personalization.",
    ),
    "instruction": (
        "Instructions",
        "Standing rules, constraints, and guidelines to always follow.",
    ),
    "decision": (
        "Decisions",
        "Architectural choices, approach selections, and their rationale.",
    ),
    "event": (
        "Events",
        "Important conversations, milestones, and temporal occurrences.",
    ),
    "goal": (
        "Goals",
        "Objectives, targets, and milestones to track progress.",
    ),
    "commitment": (
        "Commitments",
        "Promises, obligations, and TODOs that need follow-through.",
    ),
    "observation": (
        "Observations",
        "Patterns noticed, behavioral notes, and recurring themes.",
    ),
    "learning": (
        "Learnings",
        "Knowledge acquired from experience, corrections, and insights.",
    ),
    "relationship": (
        "Relationships",
        "Entity connections, team context, and collaboration patterns.",
    ),
    "context": (
        "Context",
        "Session summaries, status updates, and conversation state.",
    ),
    "artifact": (
        "Artifacts",
        "Tool outputs, files, reports, and external references.",
    ),
    "error": (
        "Errors",
        "Failure records, bugs, and lessons learned from mistakes.",
    ),
}

# Canonical ordering
MEMORY_TYPE_ORDER = [
    "instruction",
    "fact",
    "decision",
    "goal",
    "commitment",
    "preference",
    "relationship",
    "context",
    "event",
    "learning",
    "observation",
    "artifact",
    "error",
]


def _one_line(value: Any, default: str = "") -> str:
    """Collapse untrusted Markdown metadata into a single display line."""
    text = " ".join(str(value or "").split())
    return text or default


def _quote_markdown_block(value: Any) -> list[str]:
    """Render stored memory content as quoted data, not document structure."""
    lines = str(value or "").splitlines()
    return [f"> {line}" if line else ">" for line in lines]


def _inline_code(value: Any) -> str:
    text = _one_line(value)
    max_run = 0
    run = 0
    for ch in text:
        if ch == "`":
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    fence = "`" * (max_run + 1)
    if text.startswith("`") or text.endswith("`"):
        text = f" {text} "
    return f"{fence}{text}{fence}"


class MemoryExportService:
    """Formats and writes a structured memory.md for an agent."""

    def __init__(self, exports_dir: Path | None = None):
        self.exports_dir = exports_dir or (get_data_dir() / "exports")

    # Public API
    @staticmethod
    def persona_line(avatar: dict[str, Any] | None) -> str | None:
        """First line of an export: the persona the agent speaks as, or None."""
        if not avatar:
            return None
        persona = AgentAvatar.model_validate(avatar)
        provider = {"claude": "Claude", "openai": "OpenAI", "other": "other"}[
            persona.provider.value
        ]
        glyph = _one_line(persona.emoji or persona.initials)
        return f"{PERSONA_PREFIX}{glyph} {_one_line(persona.name)} ({provider})"

    def apply_persona(self, content: str, avatar: dict[str, Any] | None) -> str:
        """Replace, add or drop the persona header of an existing export.

        The persona is local agent metadata, not part of the memory snapshot,
        so a cached export must never carry a renamed or removed avatar.
        """
        lines = content.split("\n")
        if lines and lines[0].startswith(PERSONA_PREFIX):
            del lines[0]
            if lines and lines[0] == "":
                del lines[0]
        persona_line = self.persona_line(avatar)
        if persona_line:
            lines[:0] = [persona_line, ""]
        return "\n".join(lines)

    def format_memory_md(
        self,
        agent_id: str,
        memories_by_type: dict[str, list[dict[str, Any]]],
        generated_at: str | None = None,
        avatar: dict[str, Any] | None = None,
    ) -> str:
        """
        Build the full Markdown string.

        Args:
            agent_id: Agent identifier.
            memories_by_type: Dict mapping memory type -> list of memory dicts.
            generated_at: Timestamp for the header (defaults to now).
            avatar: Optional persona belonging to the exported agent.

        Returns:
            Formatted Markdown string.
        """
        generated_at = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        total = sum(len(mems) for mems in memories_by_type.values())
        type_counts = {t: len(mems) for t, mems in memories_by_type.items() if mems}

        lines: list[str] = []

        # Header
        persona_line = self.persona_line(avatar)
        if persona_line:
            lines.append(persona_line)
            lines.append("")
        lines.append(f"# Memory — {agent_id}")
        lines.append("")
        lines.append(f"> Generated: {generated_at}  ")
        lines.append(f"> Total memories: **{total}**  ")

        if type_counts:
            summary_parts = [f"{t}: {c}" for t, c in type_counts.items()]
            lines.append(f"> Breakdown: {', '.join(summary_parts)}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Sections in canonical order
        for mem_type in MEMORY_TYPE_ORDER:
            label, description = MEMORY_TYPE_META[mem_type]
            memories = memories_by_type.get(mem_type, [])

            lines.append(f"## {label}")
            lines.append("")
            lines.append(f"*{description}*")
            lines.append("")

            if not memories:
                lines.append("*No memories of this type.*")
                lines.append("")
                lines.append("---")
                lines.append("")
                continue

            for mem in memories:
                title = _one_line(mem.get("title"), "Untitled")
                content = (mem.get("content") or "").strip()
                confidence = mem.get("confidence")
                tags = mem.get("tags", [])
                created_at = _one_line(mem.get("created_at", ""))
                status = _one_line(mem.get("status", ""))

                lines.append(f"### {title}")
                lines.append("")
                if content:
                    lines.extend(_quote_markdown_block(content))
                    lines.append("")

                # Metadata line
                meta_parts: list[str] = []
                if confidence is not None:
                    meta_parts.append(f"Confidence: {confidence}")
                if status:
                    meta_parts.append(f"Status: {status}")
                if created_at:
                    meta_parts.append(f"Created: {str(created_at)[:19]}")
                if tags:
                    tag_str = (
                        ", ".join(_inline_code(t) for t in tags)
                        if isinstance(tags, list)
                        else _inline_code(_one_line(tags))
                    )
                    meta_parts.append(f"Tags: {tag_str}")

                if meta_parts:
                    lines.append(f"*{' | '.join(meta_parts)}*")
                    lines.append("")

            lines.append("---")
            lines.append("")

        # Footer
        lines.append("*End of memory export.*")
        lines.append("")

        return "\n".join(lines)

    def write_memory_md(
        self,
        agent_id: str,
        memories_by_type: dict[str, list[dict[str, Any]]],
        output_path: Path | None = None,
        avatar: dict[str, Any] | None = None,
    ) -> Path:
        """
        Generate and write memory.md to disk.

        Args:
            agent_id: Agent identifier.
            memories_by_type: Dict mapping memory type -> list of memory dicts.
            output_path: Custom output path. Defaults to the active backend's
                export directory with filename ``{agent_id}_memory.md``.
            avatar: Optional persona belonging to the exported agent.

        Returns:
            Absolute Path to the written file.
        """
        validate_safe_id(agent_id, "agent_id")

        if output_path is None:
            self.exports_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.exports_dir / f"{agent_id}_memory.md"
        else:
            validated_path = validate_output_path(
                str(output_path),
                base_dir=self.exports_dir.parent,
            )
            assert validated_path is not None
            output_path = validated_path
            output_path.parent.mkdir(parents=True, exist_ok=True)

        content = self.format_memory_md(agent_id, memories_by_type, avatar=avatar)
        output_path.write_text(content, encoding="utf-8", newline="\n")
        return output_path.resolve()
