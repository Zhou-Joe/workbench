"""ML device selection — funasr supports CUDA or CPU only (no MPS)."""

import logging

logger = logging.getLogger(__name__)


def pick_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            logger.info("using CUDA device: %s", name)
            return "cuda"
    except Exception as e:  # pragma: no cover — torch optional at import time
        logger.warning("device probe failed (%s); defaulting to cpu", e)
    return "cpu"
