"""Small shared helper for pulling specific frames out of an mp4 by index (used by both the
video and photo tiers, which each sample a different subset of frames from the same source).
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def extract_frames(video_path: Path, frame_indices: list[int]) -> dict[int, np.ndarray]:
    """Return {frame_index: BGR ndarray} for the requested indices, decoding sequentially.

    Uses ``grab()`` (cheap, skips full decode) for frames we don't need and ``retrieve()``
    (full decode) only for the ones we do -- much faster than seeking per-frame for codecs
    where random-access seeking is unreliable/imprecise.
    """
    cap = cv2.VideoCapture(str(video_path))
    wanted = set(frame_indices)
    out: dict[int, np.ndarray] = {}
    idx = 0
    max_idx = max(wanted)
    while idx <= max_idx:
        ok = cap.grab()
        if not ok:
            break
        if idx in wanted:
            ok2, frame = cap.retrieve()
            if ok2:
                out[idx] = frame
        idx += 1
    cap.release()
    return out
