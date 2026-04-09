# Daily Reflection System — Implementation Plan

## Tasks

1. [ ] **Project setup** — done when: git repo initialized, pyproject.toml with dependencies, directory structure created — depends on: none — verify: L1
2. [ ] **Pull gemma4:e2b model** — done when: `ollama pull gemma4:e2b` succeeds on server — depends on: none — verify: L1
3. [ ] **collector.py** — done when: given a date, returns list of screenshot paths + hyprland window data for that date range (04:00-04:00) — depends on: #1 — verify: L1,L3
4. [ ] **dedup.py** — done when: given screenshot paths, returns deduplicated + sampled subset at 5-min intervals using dHash — depends on: #1 — verify: L1,L3
5. [ ] **classifier.py** — done when: given a screenshot path + window context, returns structured JSON classification via Ollama — depends on: #1, #2 — verify: L1,L3
6. [ ] **timeline.py** — done when: given per-frame classifications, merges into time blocks with min 2-min duration — depends on: #1 — verify: L1,L3
7. [ ] **calendar.py** — done when: pulls Google Calendar events for a date and formats as markdown table rows — depends on: #1 — verify: L1,L3
8. [ ] **reporter.py** — done when: generates standalone reflection file + injects Time Plan and Time Log into daily note — depends on: #1 — verify: L1,L3
9. [ ] **main.py (CLI)** — done when: `daily-reflect [date]` orchestrates full pipeline end-to-end — depends on: #3,#4,#5,#6,#7,#8 — verify: L1,L4
10. [ ] **Classification caching** — done when: results saved to JSON, re-runs skip already-classified frames — depends on: #5 — verify: L1,L3
11. [ ] **End-to-end test on real data** — done when: full pipeline runs on a real day's data and produces correct output — depends on: #9 — verify: L4,L6

## Risks

| Risk | Likelihood | Mitigation | Abandon trigger |
|------|-----------|------------|-----------------|
| gemma4:e2b not available on Ollama | Medium | Fall back to gemma3:4b-it-qat (proven) | N/A — fallback exists |
| gemma4:e2b output format differs from expected JSON | Medium | Test with 5 screenshots first, adjust prompt | 3 prompt iterations fail |
| Google Calendar MCP tools not accessible from Python | Low | Use gcal client_secret.json directly with google-api-python-client | Direct API always works |
| Daily note injection corrupts existing content | Medium | Parse markdown carefully, only modify target sections, backup before write | Corruption detected in test |
| Tailscale connectivity to Ollama intermittent | Medium | Use curl subprocess (proven), 30s timeout, retry once | 3 consecutive failures |

## Verification Plan

- L1 (syntax): Python parses without errors
- L3 (tests): Unit tests for dedup, timeline merging, daily note parsing/injection
- L4 (spec replay): Map each acceptance criterion to specific code behavior
- L6 (usefulness proof): Run on a real day's data, verify output is accurate and useful

## Decision Log

| Decision | Rationale | Alternatives considered |
|----------|-----------|----------------------|
| Use thumbnails (.thumb.jpg) for VLM | Faster transfer, sufficient quality for classification | Full PNGs — slower, unnecessary detail |
| curl subprocess for Ollama | Proven reliable over Tailscale (lessons.md) | requests library — known to timeout |
| 5-min sampling interval | ~200 frames/day, ~10 min processing, good granularity | 1-min (too slow), 10-min (misses short activities) |
| Min 2-min block duration | Smooths brief app switches, reduces noise | 1-min (too noisy), 5-min (loses detail) |
| No database for v1 | Simplicity — JSON cache + in-memory pipeline | SQLite — premature for single-user CLI |
| gemma4:e2b model | User preference, newer architecture | gemma3:4b-it-qat (proven fallback) |
