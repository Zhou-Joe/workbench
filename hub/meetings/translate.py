"""Live utterance translation — en↔zh through the hub's LM Studio endpoint.

Synchronous (requests-based) like the rest of hub.llm; the WS consumer calls
it in a worker thread. Best-effort: failures return None and never break the
live transcript.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def translate(settings, text: str, source_lang: str) -> Optional[str]:
    """Translate to the other language; None on failure or empty input."""
    if not text.strip():
        return None
    from hub import llm

    target = {"en": "中文", "zh": "English"}.get(source_lang, "the other language")
    prompt = (
        f"Translate the following to {target}. "
        "Output only the translation, no explanation, no quotes.\n\n"
        f"{text}"
    )
    try:
        out = llm.chat(settings, [{"role": "user", "content": prompt}])
    except llm.LLMError as e:
        logger.warning("translation failed: %s", e)
        return None
    return (out or "").strip() or None
