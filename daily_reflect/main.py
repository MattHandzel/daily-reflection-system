#!/usr/bin/env python3
"""Daily Reflection System — reconstruct your day from lifelog screenshots.

Inverted pipeline: the hyprland window log is the backbone (segments the day at
minute-or-better granularity); the VLM enriches each segment.
"""

import argparse
import dataclasses
import json
import time
from datetime import datetime, timedelta

from .calendar import fetch_calendar_events
from .classifier import enrich_segments
from .collector import collect_frames, collect_monitor_events, collect_window_events, day_bounds
from .config import load_config, Config
from .reporter import generate_reflection_file, inject_into_daily_note
from .segmenter import assign_frames, segment_day


def _effective_today(cfg: Config) -> datetime:
    now = datetime.now(cfg.tz)
    return now if now.hour >= cfg.day_boundary_hour else now - timedelta(days=1)


def _read_watermark(cfg: Config, date_str: str) -> str | None:
    p = cfg.watermark_dir / f"{date_str}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("last_frame")
    except Exception:
        return None


def _write_watermark(cfg: Config, date_str: str, last_frame: str, frame_count: int) -> None:
    cfg.watermark_dir.mkdir(parents=True, exist_ok=True)
    (cfg.watermark_dir / f"{date_str}.json").write_text(
        json.dumps({"last_frame": last_frame, "frame_count": frame_count,
                    "updated": datetime.now(cfg.tz).isoformat()}, indent=2)
    )


def run(date_str: str, cfg: Config, inject: bool, deep_target: float) -> int:
    print(f"Daily Reflection System — {date_str}  (tz={cfg.timezone}, model={cfg.model})")
    t0 = time.time()

    print("\n[1/6] Collecting frames + window events...")
    frames = collect_frames(date_str, cfg)
    events = collect_window_events(date_str, cfg)
    if not frames and not events:
        print(f"  No lifelog data for {date_str}. Nothing to do.")
        return 1
    png_n = sum(1 for f in frames if f.is_png)
    print(f"  {len(frames)} frames ({png_n} full PNG, {len(frames) - png_n} thumb) · {len(events)} window events")

    watermark = _read_watermark(cfg, date_str)
    if watermark:
        new_frames = [f for f in frames if f.dt.isoformat() > watermark]
        print(f"  Watermark {watermark} → {len(new_frames)} new frames since last run")

    print("\n[2/6] Segmenting day by window focus...")
    _, day_end = day_bounds(date_str, cfg)
    segments = segment_day(events, day_end,
                           afk_gap_seconds=cfg.afk_gap_seconds,
                           min_segment_seconds=cfg.min_segment_seconds)
    assign_frames(segments, frames)
    active = [s for s in segments if not s.is_afk]
    print(f"  {len(segments)} segments ({len(active)} active, {len(segments) - len(active)} AFK)")
    if active:
        shortest = min(s.duration_seconds for s in active)
        print(f"  Finest active segment: {shortest:.0f}s (minute-level: {'yes' if shortest < 60 else 'no'})")

    print(f"\n[3/6] Enriching segments via {cfg.model} (concurrency={cfg.concurrency})...")
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cfg.cache_dir / f"{date_str}.json"

    monitor_events = collect_monitor_events(date_str, cfg)
    if monitor_events:
        print(f"  monitor_log: {len(monitor_events)} focus rows → exact-pane cropping enabled")
    else:
        print("  monitor_log: none for this day → dimension-inference crop fallback")

    def progress(done, total, note):
        print(f"  [{done}/{total}] {done / total * 100:.0f}% — {note}")

    new_calls, hits = enrich_segments(segments, cfg, cache_path, progress=progress,
                                      monitor_events=monitor_events)
    print(f"  {new_calls} new classifications, {hits} from cache")

    print("\n[4/6] Fetching calendar...")
    cal_events = fetch_calendar_events(date_str, cfg)
    print(f"  {len(cal_events)} calendar events across {len(cfg.gcal_calendar_ids)} calendars")

    print("\n[5/6] Writing reflection...")
    reflection_path = generate_reflection_file(date_str, segments, cfg, target_deep_hours=deep_target)
    print(f"  {reflection_path}")

    print("\n[6/6] Daily note...")
    if inject:
        ok = inject_into_daily_note(date_str, segments, cal_events, cfg)
        print(f"  {'updated' if ok else 'skipped (note missing)'}: {cfg.dailies_dir / f'{date_str}.md'}")
    else:
        print("  skipped (--no-inject)")

    if frames:
        _write_watermark(cfg, date_str, frames[-1].dt.isoformat(), len(frames))

    print(f"\nDone in {time.time() - t0:.0f}s")
    return 0


def main():
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Reconstruct your day from lifelog screenshots")
    parser.add_argument("date", nargs="?", help="Date YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--today", action="store_true", help="Process today so far")
    parser.add_argument("--model", default=None, help=f"Ollama model (default: {cfg.model})")
    parser.add_argument("--tz", default=None, help=f"Timezone (default: {cfg.timezone})")
    parser.add_argument("--concurrency", type=int, default=None, help=f"Parallel VLM calls (default: {cfg.concurrency})")
    parser.add_argument("--deep-target", type=float, default=4.0, help="Deep-work target hours (default: 4)")
    parser.add_argument("--no-inject", action="store_true", help="Don't modify the daily note")
    args = parser.parse_args()

    overrides = {}
    if args.model:
        overrides["model"] = args.model
    if args.tz:
        overrides["timezone"] = args.tz
    if args.concurrency:
        overrides["concurrency"] = args.concurrency
    if overrides:
        cfg = dataclasses.replace(cfg, **overrides)

    today = _effective_today(cfg).date()
    if args.today:
        date_str = today.strftime("%Y-%m-%d")
    elif args.date:
        date_str = args.date
    else:
        date_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    raise SystemExit(run(date_str, cfg, inject=not args.no_inject, deep_target=args.deep_target))


if __name__ == "__main__":
    main()
