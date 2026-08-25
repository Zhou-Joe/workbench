"""Speaker voiceprints — ERes2NetV2 embeddings + cosine matching.

Enrollment embeds a known speaker's clip; identification matches diarized
cluster centroids against enrolled vectors. Same-speaker cosine scores run
0.8+, different speakers <0.3 — 0.5 is a safe middle ground.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from hub.models import Speaker, Voiceprint

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 0.5


def extract_embedding(samples: np.ndarray) -> np.ndarray:
    """192-dim float32 embedding from a float32 16 kHz mono array."""
    from hub.meetings import funasr_models

    res = funasr_models.ensure_embed().generate(input=samples, cache={})
    emb = np.asarray(res[0]["spk_embedding"]).flatten()
    return emb.astype(np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def enroll_speaker(speaker_id: int, samples: np.ndarray, sample_path: str = "") -> None:
    """Compute and store an embedding for an existing Speaker."""
    emb = extract_embedding(samples)
    Voiceprint.objects.create(
        speaker_id=speaker_id, embedding=emb.tobytes(), sample_path=sample_path
    )


def list_enrolled() -> list[tuple[int, str, str, np.ndarray]]:
    """All enrolled voiceprints: (speaker_id, name, color, embedding)."""
    return [
        (vp.speaker_id, vp.speaker.name, vp.speaker.color,
         np.frombuffer(vp.embedding, dtype=np.float32))
        for vp in Voiceprint.objects.select_related("speaker")
    ]


def identify(embedding: np.ndarray) -> Optional[tuple[int, str, str, float]]:
    """Best enrolled match above MATCH_THRESHOLD, else None.

    Returns (speaker_id, name, color, score).
    """
    enrolled = list_enrolled()
    if not enrolled:
        return None
    best: Optional[tuple[int, str, str, float]] = None
    for speaker_id, name, color, emb in enrolled:
        score = cosine_similarity(embedding, emb)
        if best is None or score > best[3]:
            best = (speaker_id, name, color, score)
    if best is not None and best[3] >= MATCH_THRESHOLD:
        return best
    return None
