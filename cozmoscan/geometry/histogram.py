"""1D histogram peak-finding used for both horizontal (floor/ceiling) and vertical (wall) planes.

Exploiting the Manhattan-world + gravity-aligned-up assumption (disclosed in
docs/03_algorithms.md) turns "find the dominant planes in a noisy 3D point cloud" into
repeated 1D peak-finding, which is fast, debuggable, and has no hidden hyperparameters
beyond a bin size and a minimum-support threshold.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Peak:
    center: float
    support: int
    spread: float  # std-dev of the points that voted for this peak, meters


def find_peaks(values: np.ndarray, bin_size: float, min_support: int, merge_radius: float) -> list[Peak]:
    """Histogram ``values`` and return local-maxima bins as calibrated :class:`Peak` objects.

    A peak is a bin whose count is >= both neighbors and >= ``min_support``. Peaks within
    ``merge_radius`` of each other are merged (keeps a single wall/floor plane from splitting
    across a bin boundary).
    """
    if len(values) == 0:
        return []
    lo, hi = values.min(), values.max()
    n_bins = max(1, int(np.ceil((hi - lo) / bin_size)) + 1)
    counts, edges = np.histogram(values, bins=n_bins, range=(lo, lo + n_bins * bin_size))
    centers = (edges[:-1] + edges[1:]) / 2

    peaks: list[Peak] = []
    for i in range(len(counts)):
        if counts[i] < min_support:
            continue
        left_ok = i == 0 or counts[i] >= counts[i - 1]
        right_ok = i == len(counts) - 1 or counts[i] >= counts[i + 1]
        if left_ok and right_ok:
            mask = np.abs(values - centers[i]) <= bin_size
            spread = float(values[mask].std()) if mask.sum() > 1 else bin_size / 2
            peaks.append(Peak(center=float(centers[i]), support=int(counts[i]), spread=spread))

    # merge near-duplicate peaks, keep the one with higher support
    peaks.sort(key=lambda p: p.center)
    merged: list[Peak] = []
    for p in peaks:
        if merged and abs(p.center - merged[-1].center) <= merge_radius:
            if p.support > merged[-1].support:
                merged[-1] = p
        else:
            merged.append(p)
    merged.sort(key=lambda p: p.support, reverse=True)
    return merged
