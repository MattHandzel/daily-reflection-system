# Mistakes

Newest first. Each entry: what happened + the fix, so the next agent doesn't repeat it.

## 2026-07-19 — Merged the eval-winner model without exercising it: qwen3.5 think-mode emptied `response`

**Mistake:** Set the default model to `qwen3.5:4b` (MAT-1461 eval winner) and
merged, but the first from-main verification produced 4.1h "Uncertain" and an
empty cache. Cause: `qwen3.5` is a hybrid **reasoning** model — in think-mode it
emits the JSON into the `thinking` field and leaves `response` empty, so every
frame parsed as uncertain. The eval harness had set `"think": False` (and read
`thinking` as a fallback); the classifier request omitted it. I caught it only
because I inspected the category distribution, not just the exit code (the run
exited 0 — the 26 empty-response frames were content-uncertain, below the 20%
infra-failure banner).

**Fix:** Add `"think": False` to the classify payload and fall back to the
`thinking` field when `response` is empty. Lesson: swapping a model default is a
behavior change — exercise it on real input and check the *output distribution*,
not just that it runs. Mirror the request params the eval that picked it used.

## 2026-07-19 — Ollama error envelope silently swallowed as "uncertain"

**Mistake:** `classifier._parse_response` json-decoded the Ollama reply and read
`resp["response"]`, but on a model-load failure / GPU OOM Ollama returns HTTP 500
with a valid JSON body `{"error": "..."}` (and `curl -s` exits 0). That parsed
fine, `response` was empty, and the frame fell through to a non-retryable
`uncertain` — so a whole run under GPU contention came back 30/30 "Uncertain"
with **zero signal that classification had failed**, and those results were
cacheable/counted as real.

**Fix:** Detect `resp.get("error")` explicitly → retryable infra failure (never
cached). `enrich_segments` now returns an `infra_failures` count; `main.py` prints
a LOUD banner + exits non-zero + writes a `> [!warning]` block into the reflection
header when the failure rate exceeds 20% (a quiet NOTE below that). Added a
`/api/ps` GPU preflight that backs off when a co-resident model leaves <4GB free
on the shared 12GB card. Lesson: an HTTP client that doesn't use `-f` must
inspect the response body for an error envelope — a 2xx-shaped parse is not
success. Verify failure paths by *inducing* a failure (bogus model), not just the
happy path.

## 2026-07-18 — monitor_log crop half-wired: signature threaded, call site not

**Mistake:** The `monitor_log` exact-pane crop was added by threading a
`focused_name`/`focused_monitor` parameter through `monitors.prepare_image`,
`classifier.classify_frame`, and adding `collect_monitor_events` /
`focused_monitor_at` in `collector.py` — but the *call site* in
`classifier.enrich_segments` still invoked `classify_frame` without it, and
`main.py` never called `collect_monitor_events`. So the feature was dead: on a
day with `monitor_log` rows (2026-07-18) the pipeline silently fell back to the
content heuristic, which on 5/6 dual-monitor frames picked the WRONG (unfocused
but content-heavy eDP-1) pane over the focused-but-sparse DP-1.

**Fix:** Loaded `collect_monitor_events` in `main.py`, passed it into
`enrich_segments`, and called `focused_monitor_at(frame.dt, monitor_events)` at
the `classify_frame` submit. Verified the ground-truth crop now selects DP-1
where the heuristic chose eDP-1. Lesson: threading a parameter through
signatures is not "wired" until the outermost caller supplies a real value —
grep the call graph from the entry point, and verify the feature fires on data
that should trigger it, not just that it compiles.

## 2026-07-18 — Multi-monitor fallback assumed vertical-only stacking

**Mistake:** The generic multi-monitor fallback in `monitors._panes_for` only
handled *vertical* stacks (`height > width`). Verifying dimension distribution
against real frames surfaced a `7680×1800` **horizontal** dual-monitor layout
that fell through to "single image" and was sent to the VLM uncropped.

**Fix:** Added a horizontal-split branch (`width > height*1.8`) and confirmed
against the real frame that the blank pane is correctly skipped and the active
pane chosen. Lesson: derive layout cases from the *actual* dimension histogram
of the data, not from the assumed setup.

## 2026-07-18 — Segments outnumber frames; per-frame classification left gaps

**Mistake:** First cut classified one representative frame per *segment*. On real
data the window log had ~5x more events than screenshots (4269 events vs 826
frames on 2026-07-17), so most short segments had no frame and would have been
labelled `uncertain`.

**Fix:** Group segments by `task_key`, classify one representative frame per
*distinct task*, and apply the label to every segment of that task (framed or
not); frameless tasks fall back to a window-class heuristic. This both fixed the
coverage gap and cut VLM calls ~8x (318 segments → 38 calls).

## 2026-07-18 — `pkill -f run_bench.py` self-killed the wrapping shell (MAT-1461)

**What:** To stop the background benchmark I ran `pkill -f run_bench.py`. The `-f` pattern also matched the zsh command that *contained* the string `run_bench.py`, so pkill signalled its own wrapping shell and the whole command aborted (exit 144) before it swapped the manifest — leaving the run alive and no backup made.
**Fix:** Never use a `pkill -f` pattern broad enough to match the invoking shell (global CLAUDE.md says exactly this). Stop background jobs by numeric PID (`pgrep` → `kill <pid>`), or scope the pattern to a fragment the wrapper can't contain. Verify death with `test -d /proc/<pid>`.
