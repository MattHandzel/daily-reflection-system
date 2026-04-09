"""Merge per-frame classifications into coherent time blocks."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from .classifier import Classification


@dataclass
class TimeBlock:
    start: datetime
    end: datetime
    category: str
    app: str
    detail: str
    confidence: str

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60

    def format_time_range(self) -> str:
        return f"{self.start.strftime('%H:%M')}-{self.end.strftime('%H:%M')}"


def build_timeline(
    classifications: list[Classification],
    min_block_minutes: int = 2,
    sample_interval_minutes: int = 5,
) -> list[TimeBlock]:
    """Merge per-frame classifications into time blocks.

    Consecutive frames with the same category are merged.
    Blocks shorter than min_block_minutes are absorbed into neighbors.
    """
    if not classifications:
        return []

    # Sort by timestamp
    sorted_cls = sorted(classifications, key=lambda c: c.timestamp)

    # Build raw blocks by merging consecutive same-category frames
    interval = timedelta(minutes=sample_interval_minutes)
    blocks: list[TimeBlock] = []

    for cls in sorted_cls:
        ts = _parse_ts(cls.timestamp)
        if ts is None:
            continue

        if blocks and blocks[-1].category == cls.category:
            # Extend current block
            blocks[-1].end = ts + interval
            # Keep the most detailed description
            if len(cls.detail) > len(blocks[-1].detail):
                blocks[-1].detail = cls.detail
            # Keep lowest confidence
            if _conf_rank(cls.confidence) < _conf_rank(blocks[-1].confidence):
                blocks[-1].confidence = cls.confidence
        else:
            # Start new block
            blocks.append(
                TimeBlock(
                    start=ts,
                    end=ts + interval,
                    category=cls.category,
                    app=cls.app,
                    detail=cls.detail,
                    confidence=cls.confidence,
                )
            )

    # Remove blocks shorter than minimum duration by merging into neighbors
    if min_block_minutes > 0:
        blocks = _merge_short_blocks(blocks, min_block_minutes)

    return blocks


def _merge_short_blocks(blocks: list[TimeBlock], min_minutes: int) -> list[TimeBlock]:
    """Absorb short blocks into the preceding block."""
    if len(blocks) <= 1:
        return blocks

    result = [blocks[0]]
    for block in blocks[1:]:
        if block.duration_minutes < min_minutes and result:
            # Extend previous block
            result[-1].end = block.end
        else:
            result.append(block)
    return result


def compute_category_totals(blocks: list[TimeBlock]) -> dict[str, float]:
    """Compute total minutes per category."""
    totals: dict[str, float] = {}
    for block in blocks:
        totals[block.category] = totals.get(block.category, 0) + block.duration_minutes
    return totals


def compute_deep_work_hours(blocks: list[TimeBlock]) -> float:
    """Compute total deep work hours (coding + writing + research)."""
    deep_categories = {"deep_work_coding", "deep_work_writing", "deep_work_research"}
    total_minutes = sum(
        b.duration_minutes for b in blocks if b.category in deep_categories
    )
    return total_minutes / 60


def _parse_ts(ts_str: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None


def _conf_rank(conf: str) -> int:
    return {"high": 2, "medium": 1, "low": 0}.get(conf, 0)
