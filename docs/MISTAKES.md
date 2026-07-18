# Mistakes

Newest first. Each entry: what happened + the fix, so the next agent doesn't repeat it.

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
