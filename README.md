# Daily Reflection System

Reconstructs how you spent your day from lifelog screenshots using a local VLM. No cloud, no telemetry — your data stays on your machine.

Classifies screenshots into 12 activity categories, builds an activity timeline, pulls Google Calendar events, and populates your Obsidian daily note automatically.

![Demo](demo/demo.gif)

## Quick Start

```bash
# Clone and enter
git clone https://github.com/MattHandzel/daily-reflection-system
cd daily-reflection-system

# Process yesterday (default)
./daily-reflect

# Process a specific date
./daily-reflect 2026-04-08

# Process today so far
./daily-reflect --today

# Generate reflection file without modifying daily note
./daily-reflect 2026-04-08 --no-inject
```

## How It Works

The **hyprland window log is the backbone**; the VLM is an **enricher**.

```
Window log (10s) → segment day by task → enrich each task with VLM (focused-monitor crop) → timeline + metrics → daily note
```

1. Collects window events + screenshot frames for the day (configurable
   timezone, `HH:00` boundary). Frames prefer full PNGs, fall back to thumbnails.
2. **Segments** the day at every window focus change into minute-level task
   segments; AFK gaps become breaks.
3. For each distinct task, **enriches** one representative frame with the local
   Ollama VLM (cropped to the focused monitor for multi-monitor captures),
   labelling category + a task label; applies it to every segment of that task.
   Frameless tasks fall back to a window-class heuristic.
4. Builds the timeline + **per-task totals** and **task-switch metrics**
   (switches/hour, mean focus streak, distinct tasks).
5. Pulls Google Calendar (incl. Life Scheduler) into the note's "Time Plan".
6. Injects the "Time Log (actual)" idempotently (HTML-marker replacement) and
   writes a standalone reflection file.

Runs are incremental: classifications are cached by `(model, prompt_version,
frame)`, so a re-run only calls the VLM for tasks it hasn't classified yet.
Errors (Ollama down / GPU OOM / timeout) are never cached, so they retry on the
next run instead of poisoning the day with fake breaks.

## Output

**Daily note** — Time Plan (calendar) + Time Log (VLM reconstruction):

```markdown
### Time Log (actual)
| Time  | Activity                          | Duration | Notes            |
| ----- | --------------------------------- | -------- | ---------------- |
| 04:00 | AI Interaction: Claude conversation | 10m    | high confidence  |
| 04:10 | Deep Work: Coding: tmux session     | 5m     | high confidence  |
| 14:53 | Meetings: Cal.com Video call        | 5m     | high confidence  |
```

**Reflection file** — Full detail with category breakdown:

```markdown
## Category Summary
| Category           | Time  |
| Deep Work: Writing | 3.7h  |
| AI Interaction     | 1.8h  |
| Deep Work: Coding  | 30m   |

## Deep Work
- Total deep work: 4.5h
- Target: 4.0h
- Status: MET (4.5/4.0h)
```

## Categories

| Category | What it captures |
|----------|-----------------|
| `deep_work_coding` | Terminal, IDE, code editors |
| `deep_work_writing` | Documents, notes, prose |
| `deep_work_research` | Reading papers, documentation |
| `communication_messaging` | Chat apps (Slack, Discord, etc.) |
| `communication_email` | Email clients, webmail |
| `meetings` | Video calls, meeting apps |
| `planning_admin` | Calendar, task management |
| `learning` | Educational content, courses |
| `social_media_browsing` | Social media, Reddit, aimless browsing |
| `entertainment` | YouTube entertainment, games |
| `ai_interaction` | Claude, ChatGPT, LLM conversations |
| `break_afk` | Lock screen, screensaver, idle |

## Requirements

- **Nix** (dependencies managed via `shell.nix` — no pip needed)
- **Lifelog screenshots** at `~/lifelog/data/screen/` (ISO-timestamp PNGs + thumbnails)
- **Ollama** with a vision model (default: `gemma3:4b-it-qat`)
- **Hyprland window log** (optional) at `~/lifelog/data/index.db` for disambiguation
- **Google Calendar** OAuth credentials (optional) for Time Plan population

## Configuration

Config is layered: **environment variable > `~/.config/daily-reflect/config.toml`
> default** (override the file location with `DAILY_REFLECT_CONFIG`). Every key
below has a matching TOML key (without the `DAILY_REFLECT_` prefix, lowercased).

| Variable | Default | Description |
|----------|---------|-------------|
| `DAILY_REFLECT_TZ` | `America/Los_Angeles` | Timezone for the day boundary + displayed times (Berkeley now, `America/Chicago` at home) |
| `DAILY_REFLECT_DAY_BOUNDARY_HOUR` | `4` | Local hour the day starts (covers late-night work) |
| `DAILY_REFLECT_MODEL` | `gemma3:4b-it-qat` | Ollama vision model (also `--model`) |
| `DAILY_REFLECT_PROMPT_VERSION` | `v2` | Bump to invalidate the cache on prompt changes |
| `DAILY_REFLECT_CONCURRENCY` | `3` | Parallel VLM calls (also `--concurrency`) |
| `DAILY_REFLECT_OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama API endpoint |
| `DAILY_REFLECT_GCAL_CALENDARS` | `primary,<life-scheduler>` | Comma-separated calendar ids to pull |
| `DAILY_REFLECT_SCREEN_DIR` | `~/lifelog/data/screen` | Screenshot directory |
| `DAILY_REFLECT_DB` | `~/lifelog/data/index.db` | Hyprland window log SQLite DB |
| `DAILY_REFLECT_DAILIES_DIR` | `~/Obsidian/Main/dailies` | Obsidian daily notes directory |
| `DAILY_REFLECT_REFLECTIONS_DIR` | `~/Obsidian/Main/.../reflections` | Reflection output directory |
| `DAILY_REFLECT_GCAL_CREDENTIALS` | `~/secrets/gcal_client_secret.json` | Google Calendar OAuth client |
| `DAILY_REFLECT_GCAL_TOKEN` | `~/.local/share/universal-calendar-capture/token.json` | Google Calendar OAuth token |
| `DAILY_REFLECT_CACHE_DIR` | `~/Projects/daily-reflection-system/cache` | Classification cache |

## Performance

Measured on real data (RTX 3060, `gemma3:4b-it-qat`, concurrency 3):

| Metric | 2026-07-17 | 2026-07-03 (dual-monitor) |
|--------|-----------|---------------------------|
| Window events / frames | 4269 / 826 | 1394 / 1284 |
| Task segments (active) | 318 | 161 |
| Distinct tasks → VLM calls | 38 | 61 |
| End-to-end | 155s | 383s |
| Cached re-run | ~1s | ~1s |

Grouping segments by task means ~40–60 VLM calls cover a whole day of hundreds
of minute-level segments. Results cache to `cache/{date}.json` (keyed by model +
prompt version + frame), so during-day re-runs only classify newly-seen tasks.

## Architecture

```
daily_reflect/
  config.py      — Layered config (env > TOML > default); timezone, model, calendars
  collector.py   — Window events + PNG-preferred frames; real-datetime matching
  segmenter.py   — Backbone: cut the day into minute-level task segments
  monitors.py    — Multi-monitor detect / crop / focused-pane selection
  dedup.py       — Perceptual-hash utilities (robust to corrupt frames)
  classifier.py  — Task-grouped parallel VLM enrichment + cache
  timeline.py    — Display blocks, per-task totals, task-switch metrics
  calendar.py    — Google Calendar (incl. Life Scheduler) via gcal_helper
  reporter.py    — Reflection file + idempotent daily-note injection
  main.py        — CLI orchestration + GPU preflight + failure-rate guard
```

## License

MIT
