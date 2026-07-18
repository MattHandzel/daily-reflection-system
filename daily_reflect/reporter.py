"""Generate the reflection file and inject into the daily note.

Injection is idempotent via HTML-comment markers: the generated block is
wrapped in ``<!-- daily-reflect:{id}:start -->`` / ``:end`` and re-runs replace
everything between the markers (full-section replacement), so changed cells
never accrete a second table.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .calendar import CalendarEvent, format_calendar_table
from .config import Config
from .segmenter import Segment
from .timeline import (
    TimeBlock,
    build_blocks,
    category_totals,
    deep_work_hours,
    switch_metrics,
    task_totals,
)

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
    "uncertain": "Uncertain",
}

DEEP_TARGET_HOURS = 4.0


def _label(cat: str) -> str:
    return CATEGORY_LABELS.get(cat, cat)


def _fmt_minutes(mins: float) -> str:
    return f"{mins / 60:.1f}h" if mins >= 60 else f"{mins:.0f}m"


def generate_reflection_file(
    date_str: str, segments: list[Segment], cfg: Config,
    target_deep_hours: float = DEEP_TARGET_HOURS,
) -> Path:
    """Write the standalone reflection markdown file. Returns its path."""
    cfg.reflections_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.reflections_dir / f"{date_str}.md"
    tz = cfg.tz

    blocks = build_blocks(segments)
    totals = category_totals(segments)
    tasks = task_totals(segments)
    deep = deep_work_hours(segments)
    metrics = switch_metrics(segments)

    lines = [
        "---", "tags:", "  - ai-generated", "  - reflection",
        f'created_date: "{date_str}"', "---", "",
        f"# Daily Reflection — {date_str}", "",
        f"**Active time:** {metrics['active_hours']}h · "
        f"**Deep work:** {deep:.1f}h / {target_deep_hours:.0f}h "
        f"{'MET' if deep >= target_deep_hours else 'NOT MET'} · "
        f"**Task switches:** {metrics['switches']} "
        f"({metrics['switches_per_hour']}/h) · "
        f"**Mean focus streak:** {metrics['mean_focus_streak_min']} min · "
        f"**Distinct tasks:** {metrics['distinct_tasks']}",
        "",
        "## Activity Timeline",
        f"*{len(segments)} minute-level segments merged into {len(blocks)} blocks.*",
        "",
        "| Time | Category | Task | App | Conf |",
        "| ---- | -------- | ---- | --- | ---- |",
    ]
    for b in blocks:
        lines.append(
            f"| {b.format_time_range(tz)} ({b.duration_minutes:.0f}m) | "
            f"{_label(b.category)} | {b.task or '—'} | {b.app or '—'} | {b.confidence} |"
        )

    lines += ["", "## Time by Task", "", "| Task | Category | Time |", "| ---- | -------- | ---- |"]
    for cat, task, mins in tasks[:25]:
        lines.append(f"| {task} | {_label(cat)} | {_fmt_minutes(mins)} |")

    lines += ["", "## Category Summary", "", "| Category | Time |", "| -------- | ---- |"]
    for cat, mins in sorted(totals.items(), key=lambda x: -x[1]):
        lines.append(f"| {_label(cat)} | {_fmt_minutes(mins)} |")
    lines.append(f"| **Total tracked** | **{sum(totals.values()) / 60:.1f}h** |")

    lines += [
        "", "## Focus & Switching", "",
        f"- **Distinct tasks:** {metrics['distinct_tasks']}",
        f"- **Task switches:** {metrics['switches']} ({metrics['switches_per_hour']} per active hour)",
        f"- **Mean focus streak:** {metrics['mean_focus_streak_min']} minutes",
        "", "## Deep Work", "",
        f"- **Total:** {deep:.1f}h",
        f"- **Target:** {target_deep_hours:.0f}h",
        f"- **Status:** {'MET' if deep >= target_deep_hours else 'NOT MET'} ({deep:.1f}/{target_deep_hours:.0f}h)",
        "",
    ]
    path.write_text("\n".join(lines))
    return path


def _time_log_rows(blocks: list[TimeBlock], tz: ZoneInfo) -> str:
    rows = []
    for b in blocks:
        detail = f"{_label(b.category)}: {b.task}" if b.task else _label(b.category)
        rows.append(
            f"| {b.start.astimezone(tz).strftime('%H:%M')} | {detail} | "
            f"{_fmt_minutes(b.duration_minutes)} | {b.confidence} |"
        )
    return "\n".join(rows)


def inject_into_daily_note(
    date_str: str, segments: list[Segment], events: list[CalendarEvent], cfg: Config,
) -> bool:
    """Inject Time Plan + Time Log into the daily note idempotently.

    Returns True on write, False if the note is missing.
    """
    note_path = cfg.dailies_dir / f"{date_str}.md"
    if not note_path.exists():
        print(f"  Daily note not found: {note_path}")
        return False

    content = note_path.read_text()
    tz = cfg.tz
    blocks = build_blocks(segments)
    metrics = switch_metrics(segments)
    deep = deep_work_hours(segments)

    if events:
        plan = ("| Time | Planned Activity | Calendar |\n"
                "| ---- | ---------------- | -------- |\n"
                + format_calendar_table(events, tz))
        content = _inject_marked(content, "## Time Plan", "time-plan", plan)

    log_header = "| Time | Activity | Duration | Conf |\n| ---- | -------- | -------- | ---- |\n"
    summary = (
        f"*Deep work {deep:.1f}h · {metrics['switches']} switches "
        f"({metrics['switches_per_hour']}/h) · mean focus {metrics['mean_focus_streak_min']}min*\n\n"
    )
    log_body = summary + log_header + _time_log_rows(blocks, tz)
    content = _inject_marked(content, "### Time Log (actual)", "time-log", log_body)

    note_path.write_text(content)
    return True


def _inject_marked(content: str, section_header: str, marker_id: str, body: str) -> str:
    """Replace (or insert) a marker-delimited block.

    If the markers already exist, replace what's between them. Otherwise insert
    right after ``section_header``; if that header is absent, append a new
    section at the end of the file.
    """
    start_m = f"<!-- daily-reflect:{marker_id}:start -->"
    end_m = f"<!-- daily-reflect:{marker_id}:end -->"
    block = f"{start_m}\n{body}\n{end_m}"

    s = content.find(start_m)
    if s != -1:
        e = content.find(end_m, s)
        if e != -1:
            return content[:s] + block + content[e + len(end_m):]

    hdr = content.find(section_header)
    if hdr != -1:
        line_end = content.find("\n", hdr)
        insert_at = line_end + 1 if line_end != -1 else len(content)
        return content[:insert_at] + "\n" + block + "\n" + content[insert_at:]

    sep = "" if content.endswith("\n") else "\n"
    return f"{content}{sep}\n{section_header}\n\n{block}\n"
