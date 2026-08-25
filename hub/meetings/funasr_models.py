"""Lazy process-global funasr model singletons.

Loading FSMN-VAD + SenseVoice-Small + ERes2NetV2 costs ~1.5 GB of RAM, so
every consumer of these models shares one instance per process. funasr's
AutoModel is thread-safe for sequential generate() calls; callers run their
inference in worker threads (never on the event loop).
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_MODELS: dict[str, object] = {}

_VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
_ASR_MODEL = "iic/SenseVoiceSmall"
_EMBED_MODEL = "iic/speech_eres2netv2_sv_zh-cn_16k-common"


def _ensure(key: str, model_id: str):
    model = _MODELS.get(key)
    if model is not None:
        return model
    with _LOCK:
        model = _MODELS.get(key)
        if model is not None:
            return model
        from funasr import AutoModel

        from hub.meetings.device import pick_device

        logger.info("loading %s from ModelScope (device=%s)…", model_id, pick_device())
        model = AutoModel(model=model_id, disable_update=True, device=pick_device())
        _MODELS[key] = model
        logger.info("%s loaded.", model_id)
        return model


def ensure_vad():
    """FSMN-VAD — speech-segment boundary detection."""
    return _ensure("vad", _VAD_MODEL)


def ensure_asr():
    """SenseVoice-Small — whole-utterance transcription with language ID."""
    return _ensure("asr", _ASR_MODEL)


def ensure_embed():
    """ERes2NetV2 — 192-dim speaker embeddings."""
    return _ensure("embed", _EMBED_MODEL)


def loaded_keys() -> list[str]:
    return sorted(_MODELS)
