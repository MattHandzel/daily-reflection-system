#!/usr/bin/env python3
"""Fetch Google Calendar events across configured calendars.

Isolated in its own script so google-api-python-client is only imported inside
the nix-shell, not as a core dependency. All configuration comes from
environment variables (set by ``daily_reflect.calendar``):

- DAILY_REFLECT_GCAL_CREDENTIALS  client-secret path
- DAILY_REFLECT_GCAL_TOKEN        OAuth token path (shared w/ universal-calendar-capture)
- DAILY_REFLECT_GCAL_CALENDARS    comma-separated calendar ids (default: primary + Life Scheduler)
- DAILY_REFLECT_TZ                day-boundary timezone
- DAILY_REFLECT_DAY_BOUNDARY_HOUR hour the day starts (default 4)

Outputs a JSON list of {start, end, summary, calendar, all_day} to stdout.
Never prints secrets. Exits 0 with "[]" if the google libs or token are absent.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("[]")
    sys.exit(0)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

LIFE_SCHEDULER_ID = (
    "d025c2d71036a3fd4ff6f5e7b44e7e785bf55169cc6b35fbe54b14de0666483d"
    "@group.calendar.google.com"
)


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("DAILY_REFLECT_TZ", "America/Los_Angeles"))


def _credentials():
    token_path = Path(
        os.environ.get("DAILY_REFLECT_GCAL_TOKEN")
        or str(Path(os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share"))
               / "universal-calendar-capture" / "token.json")
    )
    creds_path = Path(
        os.environ.get("DAILY_REFLECT_GCAL_CREDENTIALS")
        or str(Path.home() / "secrets" / "gcal_client_secret.json")
    )

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif creds_path.exists():
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            return None
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
    return creds


def _calendar_ids() -> list[str]:
    raw = os.environ.get("DAILY_REFLECT_GCAL_CALENDARS")
    if raw:
        return [c.strip() for c in raw.split(",") if c.strip()]
    return ["primary", LIFE_SCHEDULER_ID]


def fetch_events(date_str: str) -> list[dict]:
    creds = _credentials()
    if not creds:
        return []
    service = build("calendar", "v3", credentials=creds)

    tz = _tz()
    boundary = int(os.environ.get("DAILY_REFLECT_DAY_BOUNDARY_HOUR", "4"))
    naive = datetime.strptime(date_str, "%Y-%m-%d")
    start_local = naive.replace(hour=boundary, minute=0, second=0, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    time_min = start_local.astimezone(timezone.utc).isoformat()
    time_max = end_local.astimezone(timezone.utc).isoformat()

    events: list[dict] = []
    for cal_id in _calendar_ids():
        try:
            result = (
                service.events()
                .list(calendarId=cal_id, timeMin=time_min, timeMax=time_max,
                      singleEvents=True, orderBy="startTime")
                .execute()
            )
        except Exception as e:
            sys.stderr.write(f"calendar {cal_id[:20]} error: {str(e)[:120]}\n")
            continue
        for item in result.get("items", []):
            start, end = item.get("start", {}), item.get("end", {})
            all_day = "dateTime" not in start
            events.append({
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "summary": item.get("summary", "(no title)"),
                "calendar": "primary" if cal_id == "primary" else ("life-scheduler" if cal_id == LIFE_SCHEDULER_ID else cal_id),
                "all_day": all_day,
            })
    return events


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("[]")
        sys.exit(0)
    try:
        print(json.dumps(fetch_events(sys.argv[1])))
    except Exception as e:
        sys.stderr.write(f"gcal_helper error: {str(e)[:160]}\n")
        print("[]")
