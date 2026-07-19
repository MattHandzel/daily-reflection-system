"""Build the display timeline and metrics from enriched task segments.

Segments (from ``segmenter``) are already the minute-level timeline. This
module (1) coalesces adjacent segments that share the same category+task into
readable blocks, and (2) computes the aggregate metrics: category totals,
per-task totals, deep-work hours, and task-switching metrics.
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .segmenter import Segment, normalize_title

DEEP_CATEGORIES = {"deep_work_coding", "deep_work_writing", "deep_work_research"}


@dataclass
class TimeBlock:
    start: datetime
    end: datetime
    category: str
    task: str
    app: str
    confidence: str

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60

    def format_time_range(self, tz: ZoneInfo) -> str:
        s = self.start.astimezone(tz)
        e = self.end.astimezone(tz)
        return f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}"


def _task_id(seg: Segment) -> str:
    return f"{seg.category}|{normalize_title(seg.task) or seg.window_class}"


def build_blocks(segments: list[Segment]) -> list[TimeBlock]:
    """Coalesce adjacent segments with the same category+task into blocks."""
    blocks: list[TimeBlock] = []
    for seg in segments:
        tid = _task_id(seg)
        if blocks and _task_id_of_block(blocks[-1]) == tid and blocks[-1].end == seg.start:
            blocks[-1].end = seg.end
            if len(seg.task) > len(blocks[-1].task):
                blocks[-1].task = seg.task
        else:
            blocks.append(TimeBlock(seg.start, seg.end, seg.category, seg.task, seg.app, seg.confidence))
    return blocks


# block task-id mirrors _task_id but works off a TimeBlock
def _task_id_of_block(b: TimeBlock) -> str:
    return f"{b.category}|{normalize_title(b.task) or ''}"


def category_totals(segments: list[Segment]) -> dict[str, float]:
    """Minutes per category (from segment durations — full resolution)."""
    totals: dict[str, float] = {}
    for seg in segments:
        cat = seg.category or "uncertain"
        totals[cat] = totals.get(cat, 0.0) + seg.duration_minutes
    return totals


def task_totals(segments: list[Segment]) -> list[tuple[str, str, float]]:
    """(category, task, minutes) per distinct task, sorted by time desc.

    AFK segments are excluded.
    """
    agg: dict[tuple[str, str], float] = {}
    for seg in segments:
        if seg.is_afk:
            continue
        label = normalize_title(seg.task) or seg.window_class or "unknown"
        key = (seg.category or "uncertain", label)
        agg[key] = agg.get(key, 0.0) + seg.duration_minutes
    rows = [(cat, task, mins) for (cat, task), mins in agg.items()]
    rows.sort(key=lambda r: -r[2])
    return rows


def deep_work_hours(segments: list[Segment]) -> float:
    return sum(s.duration_minutes for s in segments if s.category in DEEP_CATEGORIES) / 60


def switch_metrics(segments: list[Segment]) -> dict:
    """Task-switching metrics over the active (non-AFK) part of the day.

    - switches: transitions between distinct task ids
    - switches_per_hour: switches / active hours
    - mean_focus_streak_min: mean duration of a continuous same-task run
    - distinct_tasks: number of unique task ids
    """
    active = [s for s in segments if not s.is_afk and s.category != "break_afk"]
    if not active:
        return {"switches": 0, "switches_per_hour": 0.0, "mean_focus_streak_min": 0.0,
                "distinct_tasks": 0, "active_hours": 0.0}

    # collapse consecutive same-task segments into streaks
    streaks: list[float] = []
    switches = 0
    cur_id = _task_id(active[0])
    cur_dur = active[0].duration_minutes
    distinct = {cur_id}
    for seg in active[1:]:
        tid = _task_id(seg)
        distinct.add(tid)
        if tid == cur_id:
            cur_dur += seg.duration_minutes
        else:
            streaks.append(cur_dur)
            switches += 1
            cur_id, cur_dur = tid, seg.duration_minutes
    streaks.append(cur_dur)

    active_min = sum(s.duration_minutes for s in active)
    active_hours = active_min / 60
    return {
        "switches": switches,
        "switches_per_hour": round(switches / active_hours, 1) if active_hours > 0 else 0.0,
        "mean_focus_streak_min": round(sum(streaks) / len(streaks), 1) if streaks else 0.0,
        "distinct_tasks": len(distinct),
        "active_hours": round(active_hours, 2),
    }
