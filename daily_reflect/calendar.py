"""Pull Google Calendar events (via gcal_helper subprocess) for the daily note.

The heavy google libs live in ``gcal_helper.py`` so the core package stays
dependency-light. Config (credential paths, calendar ids, timezone, day
boundary) is passed to the helper via environment variables.
"""

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Config


@dataclass
class CalendarEvent:
    start: datetime
    end: datetime
    summary: str
    calendar: str
    all_day: bool

    def format_time(self, tz: ZoneInfo) -> str:
        if self.all_day:
            return "all day"
        return self.start.astimezone(tz).strftime("%H:%M")


def fetch_calendar_events(date_str: str, cfg: Config) -> list[CalendarEvent]:
    """Fetch events for a date across the configured calendars."""
    helper = Path(__file__).parent.parent / "gcal_helper.py"
    env = dict(os.environ)
    env.update({
        "DAILY_REFLECT_GCAL_CREDENTIALS": str(cfg.gcal_credentials),
        "DAILY_REFLECT_GCAL_TOKEN": str(cfg.gcal_token),
        "DAILY_REFLECT_GCAL_CALENDARS": ",".join(cfg.gcal_calendar_ids),
        "DAILY_REFLECT_TZ": cfg.timezone,
        "DAILY_REFLECT_DAY_BOUNDARY_HOUR": str(cfg.day_boundary_hour),
    })
    try:
        result = subprocess.run(
            ["python3", str(helper), date_str],
            capture_output=True, text=True, timeout=45, env=env,
        )
        if result.returncode != 0:
            print(f"  Calendar fetch warning: {result.stderr[:200]}")
            return []
        events = []
        for e in json.loads(result.stdout or "[]"):
            try:
                start = datetime.fromisoformat(e["start"])
                end = datetime.fromisoformat(e["end"])
            except (ValueError, KeyError):
                continue
            events.append(CalendarEvent(
                start=start, end=end, summary=e.get("summary", "(no title)"),
                calendar=e.get("calendar", "primary"), all_day=e.get("all_day", False),
            ))
        return sorted(events, key=lambda e: e.start)
    except Exception as e:
        print(f"  Calendar fetch error: {e}")
        return []


def format_calendar_table(events: list[CalendarEvent], tz: ZoneInfo) -> str:
    """Markdown rows for the daily-note Time Plan table."""
    rows = []
    for e in events:
        rows.append(f"| {e.format_time(tz)} | {e.summary} | {e.calendar} |")
    return "\n".join(rows)
