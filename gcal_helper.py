#!/usr/bin/env python3
"""Helper script to fetch Google Calendar events.

Isolated to avoid google-api-python-client as a core dependency.
Outputs JSON to stdout.

Usage: python3 gcal_helper.py 2026-04-09
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("[]")
    sys.exit(0)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CREDENTIALS_PATH = Path.home() / "secrets" / "gcal_client_secret.json"
TOKEN_PATH = Path.home() / "Projects" / "universal-calendar-capture" / "token.json"


def get_credentials() -> Credentials | None:
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif CREDENTIALS_PATH.exists():
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            return None
        TOKEN_PATH.write_text(creds.to_json())

    return creds


def fetch_events(date_str: str) -> list[dict]:
    creds = get_credentials()
    if not creds:
        return []

    service = build("calendar", "v3", credentials=creds)

    # Day boundary at 04:00 UTC
    date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    time_min = date.replace(hour=4, minute=0, second=0).isoformat()
    time_max = (date + timedelta(days=1)).replace(hour=4, minute=0, second=0).isoformat()

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for item in result.get("items", []):
        start = item.get("start", {})
        end = item.get("end", {})

        # Handle all-day events vs timed events
        start_dt = start.get("dateTime", start.get("date", ""))
        end_dt = end.get("dateTime", end.get("date", ""))

        # Skip all-day events for time tracking
        if "dateTime" not in start:
            continue

        events.append(
            {
                "start": start_dt,
                "end": end_dt,
                "summary": item.get("summary", "(no title)"),
            }
        )

    return events


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 gcal_helper.py YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    events = fetch_events(sys.argv[1])
    print(json.dumps(events))
