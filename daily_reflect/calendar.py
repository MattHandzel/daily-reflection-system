"""Pull Google Calendar events and format for daily note injection."""

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class CalendarEvent:
    start: datetime
    end: datetime
    summary: str

    def format_time(self) -> str:
        return self.start.strftime("%H:%M")

    def format_duration(self) -> str:
        minutes = int((self.end - self.start).total_seconds() / 60)
        if minutes >= 60:
            hours = minutes // 60
            mins = minutes % 60
            return f"{hours}h{mins:02d}m" if mins else f"{hours}h"
        return f"{minutes}m"


def fetch_calendar_events(date_str: str) -> list[CalendarEvent]:
    """Fetch Google Calendar events for a given date.

    Uses the google-api-python-client via a helper script to avoid
    heavy dependencies in the main package.
    """
    helper = Path(__file__).parent.parent / "gcal_helper.py"
    try:
        result = subprocess.run(
            ["python3", str(helper), date_str],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"  Calendar fetch warning: {result.stderr[:200]}")
            return []

        events_data = json.loads(result.stdout)
        events = []
        for e in events_data:
            start = datetime.fromisoformat(e["start"])
            end = datetime.fromisoformat(e["end"])
            events.append(CalendarEvent(start=start, end=end, summary=e["summary"]))
        return sorted(events, key=lambda e: e.start)

    except Exception as e:
        print(f"  Calendar fetch error: {e}")
        return []


def format_calendar_table(events: list[CalendarEvent]) -> str:
    """Format calendar events as markdown table rows for daily note Time Plan."""
    if not events:
        return ""

    rows = []
    for e in events:
        time_str = e.format_time()
        rows.append(f"| {time_str} | {e.summary} | calendar |")

    return "\n".join(rows)
