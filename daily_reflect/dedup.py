"""Perceptual-hash utilities for collapsing near-identical frames.

In the inverted pipeline the window log drives segmentation, so full-day dedup
is no longer on the critical path — but dedup is still useful for trimming
redundant representative frames within a segment. A corrupt image is skipped
rather than aborting the run (review finding #12).
"""

from pathlib import Path

import imagehash
from PIL import Image


def compute_dhash(path: Path) -> imagehash.ImageHash | None:
    """dHash for an image; None if the file is unreadable/corrupt."""
    try:
        with Image.open(path) as img:
            return imagehash.dhash(img)
    except Exception:
        return None


def dedup_paths(paths: list[Path], hamming_threshold: int = 10) -> list[Path]:
    """Drop consecutive near-duplicates (Hamming distance < threshold).

    Unreadable frames are skipped. The first frame is always kept.
    """
    if not paths:
        return []
    result: list[Path] = []
    prev_hash = None
    for p in paths:
        h = compute_dhash(p)
        if h is None:
            continue
        if prev_hash is None or abs(h - prev_hash) >= hamming_threshold:
            result.append(p)
            prev_hash = h
    return result
