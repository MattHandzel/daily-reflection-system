"""Generate reflection reports and inject into daily notes."""

import re
from datetime import datetime  # noqa: F401 - used in type hints
from pathlib import Path

from .calendar import CalendarEvent, format_calendar_table
from .timeline import TimeBlock, compute_category_totals, compute_deep_work_hours

VAULT_DAILIES = Path.home() / "Obsidian" / "Main" / "dailies"
REFLECTIONS_DIR = Path.home() / "Obsidian" / "Main" / "projects" / "daily-reflection-system" / "reflections"

CATEGORY_LABELS = {
    "deep_work_coding": "Deep Work: Coding",
    "deep_work_writing": "Deep Work: Writing",
    "deep_work_research": "Deep Work: Research",
    "communication_messaging": "Communication: Messaging",
    "communication_email": "Communication: Email",
    "meetings": "Meetings",
    "planning_admin": "Planning/Admin",
    "learning": "Learning",
    "social_media_browsing": "Social Media/Browsing",
    "entertainment": "Entertainment",
    "ai_interaction": "AI Interaction",
    "break_afk": "Break/AFK",
}


def generate_reflection_file(
    date_str: str,
    blocks: list[TimeBlock],
) -> Path:
    """Generate a standalone reflection markdown file."""
    REFLECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = REFLECTIONS_DIR / f"{date_str}.md"

    totals = compute_category_totals(blocks)
    deep_hours = compute_deep_work_hours(blocks)

    lines = [
        "---",
        "tags:",
        "  - ai-generated",
        "  - reflection",
        f'created_date: "{date_str}"',
        "---",
        "",
        f"# Daily Reflection — {date_str}",
        "",
        "## Activity Timeline",
        "",
        "| Time | Category | App | Detail | Confidence |",
        "| ---- | -------- | --- | ------ | ---------- |",
    ]

    for b in blocks:
        label = CATEGORY_LABELS.get(b.category, b.category)
        time_range = b.format_time_range()
        dur = f" ({b.duration_minutes:.0f}m)"
        lines.append(f"| {time_range} | {label}{dur} | {b.app} | {b.detail} | {b.confidence} |")

    lines.extend([
        "",
        "## Category Summary",
        "",
        "| Category | Time |",
        "| -------- | ---- |",
    ])

    for cat, minutes in sorted(totals.items(), key=lambda x: -x[1]):
        label = CATEGORY_LABELS.get(cat, cat)
        hours = minutes / 60
        if hours >= 1:
            lines.append(f"| {label} | {hours:.1f}h |")
        else:
            lines.append(f"| {label} | {minutes:.0f}m |")

    total_tracked = sum(totals.values())
    lines.extend([
        f"| **Total tracked** | **{total_tracked / 60:.1f}h** |",
        "",
        "## Deep Work",
        "",
        f"- **Total deep work**: {deep_hours:.1f}h",
        f"- **Target**: 4.0h",
        f"- **Status**: {'MET' if deep_hours >= 4.0 else 'NOT MET'} ({deep_hours:.1f}/4.0h)",
        "",
    ])

    path.write_text("\n".join(lines))
    return path


def generate_time_log_table(blocks: list[TimeBlock]) -> str:
    """Generate markdown table rows for the daily note Time Log (actual)."""
    rows = []
    for b in blocks:
        label = CATEGORY_LABELS.get(b.category, b.category)
        dur_min = b.duration_minutes
        if dur_min >= 60:
            dur_str = f"{dur_min / 60:.1f}h"
        else:
            dur_str = f"{dur_min:.0f}m"
        rows.append(f"| {b.start.strftime('%H:%M')} | {label}: {b.detail} | {dur_str} | {b.confidence} confidence |")
    return "\n".join(rows)


def inject_into_daily_note(
    date_str: str,
    blocks: list[TimeBlock],
    calendar_events: list[CalendarEvent],
) -> bool:
    """Inject Time Plan (from calendar) and Time Log (actual) into the daily note.

    Returns True if successful, False otherwise.
    """
    note_path = VAULT_DAILIES / f"{date_str}.md"
    if not note_path.exists():
        print(f"  Daily note not found: {note_path}")
        return False

    content = note_path.read_text()

    # Inject calendar events into Time Plan table
    if calendar_events:
        cal_table = format_calendar_table(calendar_events)
        content = _inject_table_rows(
            content,
            section_header="## Time Plan",
            table_header="| Time | Planned Activity | Category |",
            new_rows=cal_table,
        )

    # Inject activity timeline into Time Log (actual) table
    if blocks:
        time_log = generate_time_log_table(blocks)
        content = _inject_table_rows(
            content,
            section_header="### Time Log (actual)",
            table_header="| Time | Activity | Duration | Notes |",
            new_rows=time_log,
        )

    note_path.write_text(content)
    return True


def _inject_table_rows(
    content: str,
    section_header: str,
    table_header: str,
    new_rows: str,
) -> str:
    """Inject rows into a markdown table within a section.

    Finds the section, then the first markdown table (header + separator),
    then either replaces empty rows or appends after existing data rows.
    table_header is used as a fallback identifier but matching is flexible.
    """
    # Find the section
    header_idx = content.find(section_header)
    if header_idx < 0:
        return content

    # Split content after section header into lines
    section_start = content.find("\n", header_idx) + 1
    before = content[:section_start]
    after_lines = content[section_start:].split("\n")

    # Find the table: look for a separator row (| --- | --- |)
    sep_idx = None
    for i, line in enumerate(after_lines):
        stripped = line.strip()
        if re.match(r"\|[\s-]+\|", stripped) and "---" in stripped:
            sep_idx = i
            break

    if sep_idx is None:
        return content

    # The header row is the line before the separator
    header_line_idx = sep_idx - 1

    # Find all data rows after separator
    last_table_row = sep_idx
    empty_start = None
    empty_end = None

    for i in range(sep_idx + 1, len(after_lines)):
        line = after_lines[i].strip()
        if not line.startswith("|"):
            break
        last_table_row = i
        cell_content = re.sub(r"[|\s\-—]", "", line)
        if not cell_content:
            if empty_start is None:
                empty_start = i
            empty_end = i

    if empty_start is not None:
        # Replace empty rows
        after_lines[empty_start:empty_end + 1] = [new_rows]
    else:
        # Append after last data row
        after_lines.insert(last_table_row + 1, new_rows)

    return before + "\n".join(after_lines)
