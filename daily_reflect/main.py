#!/usr/bin/env python3
"""Daily Reflection System — reconstruct your day from lifelog screenshots."""

import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .classifier import classify_screenshot, load_cache, save_cache, DEFAULT_MODEL
from .collector import collect_screenshots, collect_window_events, find_window_context
from .dedup import dedup_screenshots, sample_at_interval
from .timeline import build_timeline, compute_deep_work_hours
from .calendar import fetch_calendar_events
from .reporter import generate_reflection_file, inject_into_daily_note

CACHE_DIR = Path.home() / "Projects" / "daily-reflection-system" / "cache"


def main():
    parser = argparse.ArgumentParser(description="Reconstruct your day from lifelog screenshots")
    parser.add_argument("date", nargs="?", help="Date to process (YYYY-MM-DD). Default: yesterday")
    parser.add_argument("--today", action="store_true", help="Process today (so far)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--interval", type=int, default=5, help="Sampling interval in minutes (default: 5)")
    parser.add_argument("--no-inject", action="store_true", help="Don't modify the daily note")
    args = parser.parse_args()

    # Determine target date
    if args.today:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    elif args.date:
        date_str = args.date
    else:
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")

    print(f"Daily Reflection System — processing {date_str}")
    print(f"Model: {args.model}")
    start_time = time.time()

    # Step 1: Collect screenshots
    print("\n[1/7] Collecting screenshots...")
    screenshots = collect_screenshots(date_str)
    if not screenshots:
        print(f"  No screenshots found for {date_str}. Nothing to do.")
        return
    print(f"  Found {len(screenshots)} screenshots")

    # Step 2: Collect window events
    print("\n[2/7] Collecting window events...")
    window_events = collect_window_events(date_str)
    print(f"  Found {len(window_events)} window events")

    # Step 3: Deduplicate
    print("\n[3/7] Deduplicating screenshots...")
    deduped = dedup_screenshots(screenshots)
    print(f"  After dedup: {len(deduped)} unique frames ({len(screenshots) - len(deduped)} duplicates removed)")

    # Step 4: Sample at intervals
    print("\n[4/7] Sampling at {}-minute intervals...".format(args.interval))
    sampled = sample_at_interval(deduped, args.interval)
    print(f"  Sampled {len(sampled)} frames")

    # Step 5: Classify
    print(f"\n[5/7] Classifying {len(sampled)} screenshots via {args.model}...")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{date_str}.json"
    cache = load_cache(cache_path)

    classifications = []
    new_count = 0
    for i, path in enumerate(sampled):
        ts = path.name.replace(".thumb.jpg", "").replace(".png", "")

        if ts in cache:
            classifications.append(cache[ts])
            continue

        window_title, window_class = find_window_context(ts, window_events)
        cls = classify_screenshot(path, window_title, window_class, model=args.model)
        classifications.append(cls)
        cache[ts] = cls
        new_count += 1

        if (i + 1) % 10 == 0 or i == len(sampled) - 1:
            pct = (i + 1) / len(sampled) * 100
            print(f"  [{i + 1}/{len(sampled)}] {pct:.0f}% — {cls.category} ({cls.confidence})")
            save_cache(cache_path, cache)

    save_cache(cache_path, cache)
    print(f"  Classified {new_count} new frames ({len(classifications) - new_count} from cache)")

    # Step 6: Build timeline
    print("\n[6/7] Building activity timeline...")
    blocks = build_timeline(classifications, min_block_minutes=2, sample_interval_minutes=args.interval)
    print(f"  Built {len(blocks)} time blocks")

    deep_hours = compute_deep_work_hours(blocks)
    print(f"  Deep work: {deep_hours:.1f}h / 4.0h target {'✓' if deep_hours >= 4 else '✗'}")

    # Step 7: Generate output
    print("\n[7/7] Generating output...")

    # Fetch calendar events
    calendar_events = fetch_calendar_events(date_str)
    print(f"  Calendar: {len(calendar_events)} events")

    # Generate standalone reflection file
    reflection_path = generate_reflection_file(date_str, blocks)
    print(f"  Reflection file: {reflection_path}")

    # Inject into daily note
    if not args.no_inject:
        success = inject_into_daily_note(date_str, blocks, calendar_events)
        if success:
            print(f"  Daily note updated: ~/Obsidian/Main/dailies/{date_str}.md")
        else:
            print(f"  Daily note injection skipped (note not found or error)")

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
