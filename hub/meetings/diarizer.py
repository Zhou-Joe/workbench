"""Speaker diarization — segment by energy, cluster by voice, label utterances.

Pipeline: load the saved WAV → ~2 s windows with voice energy → ERes2NetV2
embedding per window → agglomerative clustering (cosine, 2–6 by silhouette)
→ label each utterance by majority overlapping-cluster duration → relabel
clusters to enrolled speaker names when voiceprints exist. Pragmatic, not
pyannote-grade; good for 2–5 person meetings, runs locally on CPU.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from hub.meetings import voiceprint
from hub.models import Utterance

logger = logging.getLogger(__name__)

_FRAME_SEC = 2.0
_HOP_SEC = 1.0
_MIN_ENERGY = 0.005
_SR = 16000
_MIN_CLUSTERS = 2
_MAX_CLUSTERS = 6


@dataclass
class Segment:
    start: float  # seconds
    end: float
    embedding: Optional[np.ndarray] = None
    cluster: int = -1


def _load_audio(path: str) -> np.ndarray:
    import librosa

    samples, _ = librosa.load(path, sr=_SR, mono=True)
    return samples.astype(np.float32)


def _segment_by_energy(samples: np.ndarray) -> list[Segment]:
    frame = int(_FRAME_SEC * _SR)
    hop = int(_HOP_SEC * _SR)
    segments: list[Segment] = []
    for i in range(0, len(samples) - frame + 1, hop):
        window = samples[i : i + frame]
        rms = float(np.sqrt(np.mean(window ** 2)))
        if rms < _MIN_ENERGY:
            continue
        segments.append(Segment(start=i / _SR, end=(i + frame) / _SR))
    return segments


def _embed_segments(segments: list[Segment], samples: np.ndarray) -> None:
    for seg in segments:
        seg_audio = samples[int(seg.start * _SR) : int(seg.end * _SR)]
        try:
            seg.embedding = voiceprint.extract_embedding(seg_audio)
        except Exception as e:
            logger.warning(
                "embedding failed for segment %.1f-%.1fs: %s", seg.start, seg.end, e
            )


def _cluster(segments: list[Segment]) -> int:
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    embs = np.stack([s.embedding for s in segments if s.embedding is not None])
    if len(embs) < 2:
        for s in segments:
            s.cluster = 0
        return 1

    best_n = _MIN_CLUSTERS
    best_score = -1.0
    max_possible = min(_MAX_CLUSTERS, len(embs))
    for n in range(_MIN_CLUSTERS, max_possible + 1):
        try:
            labels = AgglomerativeClustering(
                n_clusters=n, metric="cosine", linkage="average"
            ).fit_predict(embs)
            if len(set(labels)) < 2:
                continue
            score = silhouette_score(embs, labels, metric="cosine")
            if score > best_score:
                best_score = score
                best_n = n
        except Exception:
            continue

    final_labels = AgglomerativeClustering(
        n_clusters=best_n, metric="cosine", linkage="average"
    ).fit_predict(embs)
    idx = 0
    for s in segments:
        if s.embedding is not None:
            s.cluster = int(final_labels[idx])
            idx += 1
    return best_n


def _label_utterances(meeting_id: int, segments: list[Segment]) -> dict[int, str]:
    """{utterance_id: speaker_N} by majority overlapping-cluster duration."""
    labels: dict[int, str] = {}
    for utt in Utterance.objects.filter(meeting_id=meeting_id).order_by("seq"):
        utt_start = utt.start_ts or 0
        utt_end = utt.end_ts or utt_start
        overlaps: dict[int, int] = {}
        for seg in segments:
            if seg.cluster < 0:
                continue
            overlap = min(utt_end, seg.end) - max(utt_start, seg.start)
            if overlap > 0:
                overlaps[seg.cluster] = overlaps.get(seg.cluster, 0) + int(overlap)
        if overlaps:
            best_cluster = max(overlaps, key=overlaps.get)
            labels[utt.id] = f"speaker_{best_cluster}"
    return labels


def _relabel_with_voiceprints(
    segments: list[Segment], labels: dict[int, str]
) -> dict[int, str]:
    """Map each cluster centroid to the closest enrolled voice, if any."""
    by_cluster: dict[int, list[np.ndarray]] = {}
    for seg in segments:
        if seg.cluster >= 0 and seg.embedding is not None:
            by_cluster.setdefault(seg.cluster, []).append(seg.embedding)
    cluster_name: dict[int, str] = {}
    for cluster_id, embs in by_cluster.items():
        centroid = np.mean(embs, axis=0)
        match = voiceprint.identify(centroid)
        cluster_name[cluster_id] = match[1] if match else f"speaker_{cluster_id}"
    out: dict[int, str] = {}
    for uid, lbl in labels.items():
        if lbl.startswith("speaker_") and lbl[8:].isdigit():
            out[uid] = cluster_name.get(int(lbl[8:]), lbl)
        else:
            out[uid] = lbl
    return out


def diarize_meeting(meeting_id: int, audio_path: str) -> dict[int, str]:
    """Full pipeline; persists speaker labels; returns {utterance_id: label}."""
    logger.info("diarizing meeting %d from %s", meeting_id, audio_path)
    samples = _load_audio(audio_path)
    segments = _segment_by_energy(samples)
    if not segments:
        logger.warning("no speech segments found in %s", audio_path)
        return {}
    logger.info("found %d speech segments", len(segments))

    _embed_segments(segments, samples)
    n_clusters = _cluster(segments)
    logger.info("clustered into %d speakers", n_clusters)

    labels = _label_utterances(meeting_id, segments)

    if voiceprint.list_enrolled() and labels:
        labels = _relabel_with_voiceprints(segments, labels)

    for uid, label in labels.items():
        Utterance.objects.filter(pk=uid).update(speaker_label=label)
    return labels
