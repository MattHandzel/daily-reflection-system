"""Collect screenshot paths and hyprland window data for a date range."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

LIFELOG_SCREEN_DIR = Path.home() / "lifelog" / "data" / "screen"
LIFELOG_DB = Path.home() / "lifelog" / "data" / "index.db"


class WindowEvent(NamedTuple):
    timestamp: str
    window_title: str
    window_class: str


def get_date_range(date_str: str) -> tuple[datetime, datetime]:
    """Return (start, end) datetimes for a day boundary at 04:00 UTC."""
    date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = date.replace(hour=4, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def collect_screenshots(date_str: str) -> list[Path]:
    """Return sorted list of screenshot paths for the given date's range."""
    start, end = get_date_range(date_str)

    # Use date-prefix globbing to avoid scanning 250K+ files
    # Day boundary is 04:00, so we need hours 04-23 of target date
    # and hours 00-03 of the next day
    result = []
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    next_date = date_obj + timedelta(days=1)

    # Glob target date (hours 04-23)
    date_prefix = date_obj.strftime("%Y-%m-%d")
    for p in sorted(LIFELOG_SCREEN_DIR.glob(f"{date_prefix}T*.thumb.jpg")):
        ts_str = p.name.replace(".thumb.jpg", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts >= start:
                result.append(p)
        except ValueError:
            continue

    # Glob next date (hours 00-03)
    next_prefix = next_date.strftime("%Y-%m-%d")
    for p in sorted(LIFELOG_SCREEN_DIR.glob(f"{next_prefix}T0[0-3]*.thumb.jpg")):
        ts_str = p.name.replace(".thumb.jpg", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts < end:
                result.append(p)
        except ValueError:
            continue

    return result


def collect_window_events(date_str: str) -> list[WindowEvent]:
    """Return hyprland window events for the given date range."""
    start, end = get_date_range(date_str)

    if not LIFELOG_DB.exists():
        return []

    conn = sqlite3.connect(str(LIFELOG_DB))
    try:
        cursor = conn.execute(
            "SELECT timestamp, window_title, window_class FROM hyprland_log "
            "WHERE timestamp >= ? AND timestamp < ? AND window_title != '' "
            "ORDER BY timestamp",
            (start.isoformat(), end.isoformat()),
        )
        return [WindowEvent(*row) for row in cursor.fetchall()]
    finally:
        conn.close()


def find_window_context(timestamp: str, events: list[WindowEvent]) -> tuple[str, str]:
    """Find the closest window event to a screenshot timestamp.

    Returns (window_title, window_class).
    """
    if not events:
        return "", ""

    # Binary search for closest event
    target = timestamp
    lo, hi = 0, len(events) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if events[mid].timestamp < target:
            lo = mid + 1
        else:
            hi = mid

    # Check neighbors for closest
    best = events[lo]
    if lo > 0:
        prev = events[lo - 1]
        # Compare distance (string comparison works for ISO timestamps)
        if abs(ord(prev.timestamp[-1]) - ord(target[-1])) < abs(
            ord(best.timestamp[-1]) - ord(target[-1])
        ):
            best = prev

    return best.window_title, best.window_class
