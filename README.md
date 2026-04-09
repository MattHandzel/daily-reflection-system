# Daily Reflection System

Reconstructs how you spent your day from lifelog screenshots using a local VLM, pulls Google Calendar events, and populates your Obsidian daily note.

## Quick Start

```bash
# Process yesterday (default)
daily-reflect

# Process a specific date
daily-reflect 2026-04-08

# Process today so far
daily-reflect --today

# Generate reflection file without modifying daily note
daily-reflect 2026-04-08 --no-inject
```

## What It Does

1. Collects screenshots from `~/lifelog/data/screen/` for the target date (04:00-04:00 boundary)
2. Deduplicates using perceptual hashing (dHash)
3. Samples at 5-minute intervals
4. Enriches with Hyprland window title/class from `~/lifelog/data/index.db`
5. Classifies each frame via Ollama VLM (gemma3:4b-it-qat) into 12 activity categories
6. Merges into time blocks (minimum 2-minute duration)
7. Pulls Google Calendar events into daily note's "Time Plan" table
8. Populates daily note's "Time Log (actual)" with reconstructed timeline
9. Generates standalone reflection file with full detail + category summary + deep work tracking

## Output

- **Daily note** (`~/Obsidian/Main/dailies/{date}.md`): Time Plan table (calendar) + Time Log table (VLM)
- **Reflection file** (`reflections/{date}.md`): Full timeline, category summary, deep work hours vs 4h target

## Categories

deep_work_coding, deep_work_writing, deep_work_research, communication_messaging, communication_email, meetings, planning_admin, learning, social_media_browsing, entertainment, ai_interaction, break_afk

## Requirements

- NixOS with nix-shell (dependencies managed via `shell.nix`)
- Lifelog screenshots at `~/lifelog/data/screen/`
- Ollama server with gemma3:4b-it-qat at `http://100.118.206.104:11434`
- Google Calendar OAuth token at `~/Projects/universal-calendar-capture/token.json`

## Performance

- First run: ~5 minutes (96 VLM classifications)
- Cached re-run: ~17 seconds
- Cache stored at `cache/{date}.json`
