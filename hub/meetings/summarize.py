"""Meeting and series summaries via the hub's LM Studio endpoint.

The full transcript is sent unchunked — the endpoint applies its own context
limit, and cutting content ourselves would silently hide most of the meeting
from the model.
"""

from __future__ import annotations

import logging
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


def _summary_prompt(transcript: str) -> str:
    return (
        "You are a meeting assistant. Summarize the following meeting transcript "
        "in 3-5 bullet points. Write in the same language(s) as the transcript "
        "(if bilingual, key points in both English and Chinese). "
        "Be concise and factual.\n\n"
        f"Transcript:\n{transcript}"
    )


def _series_prompt(blocks: list[str]) -> str:
    return (
        "You are a meeting assistant. Below are the contents from a series of "
        "recurring meetings, listed in chronological order. Produce a progress "
        "overview with these sections:\n\n"
        "## ✅ Achieved\nWhat has been completed or resolved.\n"
        "## 🔄 In Progress\nWhat's actively being worked on.\n"
        "## ⏭ What's Next\nAction items and topics for the next meeting.\n"
        "## 📌 Key Decisions\nImportant decisions made across meetings.\n\n"
        "Write in the same language(s) as the content (bilingual if mixed). "
        "Be concise.\n\n"
        + "\n\n".join(blocks)
    )


def summarize(settings, transcript: str) -> Optional[str]:
    """3–5 bullet summary of the full transcript, or None if LLM fails."""
    from hub import llm

    if not transcript.strip():
        return None
    try:
        out = llm.chat(settings, [{"role": "user", "content": _summary_prompt(transcript)}])
    except llm.LLMError as e:
        logger.warning("summary failed: %s", e)
        return None
    return (out or "").strip() or None


def summarize_stream(settings, transcript: str) -> Iterator[str]:
    """Streaming variant — yields summary deltas; silent on LLM failure."""
    from hub import llm

    if not transcript.strip():
        return
    try:
        yield from llm.chat_stream(
            settings, [{"role": "user", "content": _summary_prompt(transcript)}]
        )
    except llm.LLMError as e:
        logger.warning("summary stream failed: %s", e)


def series_blocks(meetings_data: list[dict]) -> list[str]:
    blocks: list[str] = []
    for m in meetings_data:
        content = (m.get("summary_or_transcript") or "").strip()
        if not content:
            continue
        blocks.append(f"### {m['title']} ({m['date']})\n{content}")
    return blocks


def summarize_series(settings, meetings_data: list[dict]) -> Optional[str]:
    from hub import llm

    blocks = series_blocks(meetings_data)
    if not blocks:
        return None
    try:
        out = llm.chat(settings, [{"role": "user", "content": _series_prompt(blocks)}])
    except llm.LLMError as e:
        logger.warning("series summary failed: %s", e)
        return None
    return (out or "").strip() or None


def summarize_series_stream(settings, meetings_data: list[dict]) -> Iterator[str]:
    from hub import llm

    blocks = series_blocks(meetings_data)
    if not blocks:
        return
    try:
        yield from llm.chat_stream(
            settings, [{"role": "user", "content": _series_prompt(blocks)}]
        )
    except llm.LLMError as e:
        logger.warning("series summary stream failed: %s", e)
