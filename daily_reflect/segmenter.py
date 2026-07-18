"""Segment the day into task segments from the hyprland window log.

This is the inverted design's backbone: instead of sampling frames at a fixed
5-minute interval, we cut the day at every window focus change (10s log
resolution) into candidate *task segments*, then let the VLM enrich each
segment. A segment can be as short as one window-log tick, giving
minute-or-better granularity.
"""

import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .collector import Frame, WindowEvent

AFK_KEY = "__afk__"

# volatile title prefixes: unread-count "(3) ", modified-buffer markers
_PREFIX_RE = re.compile(r"^(?:\(\d+\)\s*|[●*•]\s*)+")


def normalize_title(title: str) -> str:
    """Strip volatile prefixes (unread counts, modified markers) for grouping."""
    return _PREFIX_RE.sub("", title or "").strip()


def _task_key(ev: WindowEvent) -> str:
    return f"{ev.window_class}␟{normalize_title(ev.window_title)}"


@dataclass
class Segment:
    start: datetime
    end: datetime
    window_class: str
    window_title: str
    task_key: str
    is_afk: bool = False
    frames: list[Frame] = field(default_factory=list)
    # --- enrichment (filled by the classifier) ---
    category: str = ""
    task: str = ""
    app: str = ""
    confidence: str = ""

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60


def _median_interval(events: list[WindowEvent]) -> timedelta:
    gaps = [
        (events[i + 1].dt - events[i].dt).total_seconds()
        for i in range(len(events) - 1)
    ]
    gaps = [g for g in gaps if 0 < g <= 120]
    secs = statistics.median(gaps) if gaps else 10.0
    return timedelta(seconds=max(5.0, secs))


def segment_day(
    events: list[WindowEvent],
    day_end: datetime,
    afk_gap_seconds: int = 300,
    min_segment_seconds: int = 20,
) -> list[Segment]:
    """Build task segments from window events.

    A run of consecutive events sharing ``(window_class, normalized_title)``
    becomes one segment. A gap larger than ``afk_gap_seconds`` between events
    becomes an AFK segment. Segments shorter than ``min_segment_seconds`` are
    absorbed into a neighbor to suppress sub-window flicker.
    """
    if not events:
        return []

    interval = _median_interval(events)
    n = len(events)

    # 1. Expand each event into a tick spanning [dt, next_dt], splitting off AFK.
    ticks: list[Segment] = []
    for i, ev in enumerate(events):
        raw_end = events[i + 1].dt if i + 1 < n else min(day_end, ev.dt + interval)
        if raw_end <= ev.dt:
            continue
        gap = (raw_end - ev.dt).total_seconds()
        if gap > afk_gap_seconds:
            active_end = ev.dt + interval
            ticks.append(Segment(ev.dt, active_end, ev.window_class, ev.window_title, _task_key(ev)))
            ticks.append(Segment(active_end, raw_end, "", "", AFK_KEY, is_afk=True))
        else:
            ticks.append(Segment(ev.dt, raw_end, ev.window_class, ev.window_title, _task_key(ev)))

    # 2. Merge consecutive ticks with the same task_key.
    merged: list[Segment] = []
    for t in ticks:
        if merged and merged[-1].task_key == t.task_key:
            merged[-1].end = t.end
        else:
            merged.append(t)

    # 3. Absorb sub-threshold segments into a neighbor (prefer the longer one).
    return _absorb_short(merged, min_segment_seconds)


def _absorb_short(segments: list[Segment], min_seconds: int) -> list[Segment]:
    if len(segments) <= 1 or min_seconds <= 0:
        return segments
    result: list[Segment] = [segments[0]]
    for seg in segments[1:]:
        if seg.duration_seconds < min_seconds:
            result[-1].end = seg.end  # extend previous, keeping its label
        else:
            result.append(seg)
    # re-merge any now-adjacent same-key segments produced by absorption
    remerged: list[Segment] = []
    for seg in result:
        if remerged and remerged[-1].task_key == seg.task_key:
            remerged[-1].end = seg.end
        else:
            remerged.append(seg)
    return remerged


def assign_frames(segments: list[Segment], frames: list[Frame]) -> None:
    """Attach each frame to the segment whose [start, end) contains it."""
    if not segments or not frames:
        return
    starts = [s.start for s in segments]
    from bisect import bisect_right
    for fr in frames:
        idx = bisect_right(starts, fr.dt) - 1
        if 0 <= idx < len(segments) and segments[idx].start <= fr.dt < segments[idx].end:
            segments[idx].frames.append(fr)


def representative_frames(segment: Segment, k: int = 1) -> list[Frame]:
    """Pick up to ``k`` frames for a segment: midpoint first, then spread.

    PNG frames are preferred (legible for the VLM). Returns [] for AFK segments
    or segments with no frames.
    """
    if segment.is_afk or not segment.frames:
        return []
    frames = segment.frames
    pngs = [f for f in frames if f.is_png]
    pool = pngs if pngs else frames
    if k <= 1 or len(pool) <= k:
        mid = segment.start + (segment.end - segment.start) / 2
        pool_sorted = sorted(pool, key=lambda f: abs((f.dt - mid).total_seconds()))
        return pool_sorted[:k] if k > 1 else pool_sorted[:1]
    # spread k picks evenly across the segment
    step = (len(pool) - 1) / (k - 1)
    return [pool[round(i * step)] for i in range(k)]
