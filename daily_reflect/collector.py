"""Collect screenshot frames and hyprland window events for a date range.

The hyprland window log is the timeline *backbone* (see ``segmenter``); this
module just loads the raw signals. All timestamps are parsed to tz-aware
``datetime`` so downstream code never does string-ordinal comparisons.
"""

import sqlite3
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config


@dataclass(frozen=True)
class WindowEvent:
    dt: datetime
    window_title: str
    window_class: str


@dataclass(frozen=True)
class Frame:
    dt: datetime
    path: Path
    is_png: bool


@dataclass(frozen=True)
class MonitorEvent:
    dt: datetime
    focused_name: str  # name of the focused monitor at this timestamp


def day_bounds(date_str: str, cfg: Config) -> tuple[datetime, datetime]:
    """(start, end) UTC-aware datetimes for the local day boundary.

    A "day" runs from ``day_boundary_hour`` local time to the same hour the next
    day, in ``cfg.timezone``. Returned as UTC so they compare directly with the
    UTC-stamped filenames and DB rows.
    """
    naive = datetime.strptime(date_str, "%Y-%m-%d")
    start_local = naive.replace(
        hour=cfg.day_boundary_hour, minute=0, second=0, microsecond=0, tzinfo=cfg.tz
    )
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _parse_ts_from_name(name: str) -> datetime | None:
    ts_str = name.replace(".thumb.jpg", "").replace(".png", "")
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None


def collect_frames(date_str: str, cfg: Config) -> list[Frame]:
    """Return frames within the day, one per timestamp, PNG-preferred.

    Full PNGs (2880x1800+) are legible where 720x450 thumbnails are not, but
    older PNGs get pruned — so we fall back to the thumbnail when the PNG is
    absent. Globs the target and next UTC date (the local day spans both).
    """
    start, end = day_bounds(date_str, cfg)
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    prefixes = [
        date_obj.strftime("%Y-%m-%d"),
        (date_obj + timedelta(days=1)).strftime("%Y-%m-%d"),
    ]

    # ts_str -> {"png": Path|None, "thumb": Path|None, "dt": datetime}
    by_ts: dict[str, dict] = {}
    for prefix in prefixes:
        for p in cfg.screen_dir.glob(f"{prefix}T*"):
            name = p.name
            if name.endswith(".thumb.jpg"):
                kind, ts_str = "thumb", name[: -len(".thumb.jpg")]
            elif name.endswith(".png"):
                kind, ts_str = "png", name[: -len(".png")]
            else:
                continue
            dt = _parse_ts_from_name(name)
            if dt is None or not (start <= dt < end):
                continue
            slot = by_ts.setdefault(ts_str, {"png": None, "thumb": None, "dt": dt})
            slot[kind] = p

    frames: list[Frame] = []
    for slot in by_ts.values():
        if cfg.prefer_png and slot["png"] is not None:
            frames.append(Frame(slot["dt"], slot["png"], True))
        elif slot["thumb"] is not None:
            frames.append(Frame(slot["dt"], slot["thumb"], False))
        elif slot["png"] is not None:
            frames.append(Frame(slot["dt"], slot["png"], True))
    frames.sort(key=lambda f: f.dt)
    return frames


def collect_window_events(date_str: str, cfg: Config) -> list[WindowEvent]:
    """Return hyprland window events for the day, sorted by time.

    Keeps rows with an empty title (they still mark a focused window_class);
    only rows whose timestamp cannot be parsed are dropped.
    """
    start, end = day_bounds(date_str, cfg)
    if not cfg.db_path.exists():
        return []

    conn = sqlite3.connect(str(cfg.db_path))
    try:
        cursor = conn.execute(
            "SELECT timestamp, window_title, window_class FROM hyprland_log "
            "WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp",
            (start.isoformat(), end.isoformat()),
        )
        events = []
        for ts, title, klass in cursor.fetchall():
            try:
                dt = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                continue
            events.append(WindowEvent(dt, title or "", klass or ""))
        return events
    finally:
        conn.close()


def collect_monitor_events(date_str: str, cfg: Config) -> list[MonitorEvent]:
    """Return the focused monitor over time from ``monitor_log``, sorted by time.

    Each logged timestamp records every monitor's geometry with a ``focused``
    flag; we keep one ``MonitorEvent`` per timestamp naming the focused monitor.
    Absent table (older data) -> empty list, and cropping falls back to
    dimension inference. Rows may have zero or multiple focused monitors at a
    tick (transient); we take the first focused one.
    """
    start, end = day_bounds(date_str, cfg)
    if not cfg.db_path.exists():
        return []
    conn = sqlite3.connect(str(cfg.db_path))
    try:
        conn.execute("SELECT 1 FROM monitor_log LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return []
    try:
        cursor = conn.execute(
            "SELECT timestamp, name FROM monitor_log "
            "WHERE timestamp >= ? AND timestamp < ? AND focused = 1 ORDER BY timestamp",
            (start.isoformat(), end.isoformat()),
        )
        by_ts: dict[str, MonitorEvent] = {}
        for ts, name in cursor.fetchall():
            if ts in by_ts:
                continue
            try:
                dt = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                continue
            by_ts[ts] = MonitorEvent(dt, name or "")
        return sorted(by_ts.values(), key=lambda m: m.dt)
    finally:
        conn.close()


def focused_monitor_at(
    dt: datetime, monitors: list[MonitorEvent], max_skew_seconds: float = 30.0
) -> str | None:
    """Focused monitor name nearest ``dt``, or None if no row is close enough.

    A frame is only cropped by ground truth when a monitor_log row is within
    ``max_skew_seconds`` (both log ~10s); otherwise the caller falls back to the
    dimension-inference content heuristic.
    """
    if not monitors:
        return None
    times = [m.dt for m in monitors]
    i = bisect_left(times, dt)
    candidates = []
    if i < len(monitors):
        candidates.append(monitors[i])
    if i > 0:
        candidates.append(monitors[i - 1])
    best = min(candidates, key=lambda m: abs((m.dt - dt).total_seconds()))
    if abs((best.dt - dt).total_seconds()) > max_skew_seconds:
        return None
    return best.focused_name or None


def find_window_context(dt: datetime, events: list[WindowEvent]) -> tuple[str, str]:
    """Nearest window event to ``dt`` by real datetime distance.

    Replaces the old last-character ordinal hack (every ISO string ends in the
    same digit, so that comparison was meaningless and mis-attached titles at
    app-switch boundaries).
    """
    if not events:
        return "", ""
    times = [e.dt for e in events]
    i = bisect_left(times, dt)
    candidates = []
    if i < len(events):
        candidates.append(events[i])
    if i > 0:
        candidates.append(events[i - 1])
    best = min(candidates, key=lambda e: abs((e.dt - dt).total_seconds()))
    return best.window_title, best.window_class
