"""Deduplicate screenshots using perceptual hashing and sample at intervals."""

from datetime import datetime, timedelta
from pathlib import Path

import imagehash
from PIL import Image


def compute_dhash(path: Path) -> imagehash.ImageHash:
    """Compute dHash for a thumbnail image."""
    img = Image.open(path)
    return imagehash.dhash(img)


def dedup_screenshots(
    paths: list[Path], hamming_threshold: int = 10
) -> list[Path]:
    """Remove near-duplicate screenshots using dHash.

    Two consecutive frames with Hamming distance < threshold are considered
    duplicates; only the first is kept.
    """
    if not paths:
        return []

    result = [paths[0]]
    prev_hash = compute_dhash(paths[0])

    for p in paths[1:]:
        h = compute_dhash(p)
        if abs(h - prev_hash) >= hamming_threshold:
            result.append(p)
            prev_hash = h

    return result


def sample_at_interval(
    paths: list[Path], interval_minutes: int = 5
) -> list[Path]:
    """Sample one screenshot per time interval from the deduplicated set."""
    if not paths:
        return []

    interval = timedelta(minutes=interval_minutes)
    result = [paths[0]]
    last_ts = _parse_timestamp(paths[0])

    for p in paths[1:]:
        ts = _parse_timestamp(p)
        if ts and last_ts and (ts - last_ts) >= interval:
            result.append(p)
            last_ts = ts

    return result


def _parse_timestamp(path: Path) -> datetime | None:
    """Parse ISO timestamp from thumbnail filename."""
    ts_str = path.name.replace(".thumb.jpg", "").replace(".png", "")
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None
