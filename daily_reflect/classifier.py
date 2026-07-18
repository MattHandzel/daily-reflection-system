"""Enrich task segments with a VLM label (category + freeform task).

The window log already tells us *which app/window* — the VLM's job is to read a
representative frame and say *what task* it was and which category it belongs
to. Calls run in a bounded thread pool over ``curl`` subprocesses (requests
times out over Tailscale). Errors are transport-vs-content separated:

- transport error (curl fail / non-200 / timeout / no response) -> retryable,
  NEVER cached, so a mid-run Ollama restart doesn't poison the cache.
- content fallback (unparseable / off-list category) -> ``uncertain`` (not a
  fake ``break_afk``), cached because retrying is deterministic.

Cache is keyed by ``(model, prompt_version, frame_name)``.
"""

import json
import base64
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable

from .collector import MonitorEvent, focused_monitor_at
from .config import Config
from .monitors import prepare_image
from .segmenter import Segment, representative_frames

CATEGORIES = [
    "deep_work_coding",
    "deep_work_writing",
    "deep_work_research",
    "communication_messaging",
    "communication_email",
    "meetings",
    "planning_admin",
    "learning",
    "social_media_browsing",
    "entertainment",
    "ai_interaction",
    "break_afk",
]
UNCERTAIN = "uncertain"

# Fallback category by window_class substring, used ONLY when a task has no
# frame to show the VLM. Browsers are deliberately left out — their content is
# ambiguous and needs the pixels, so a frameless browser task stays uncertain.
CLASS_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("kitty", "alacritty", "foot", "wezterm", "ghostty", "code", "nvim", "vim", "jetbrains", "pycharm"), "deep_work_coding"),
    (("obsidian", "zettlr", "logseq"), "deep_work_writing"),
    (("betterbird", "thunderbird", "evolution", "geary"), "communication_email"),
    (("slack", "discord", "vesktop", "beeper", "telegram", "whatsapp", "signal", "element"), "communication_messaging"),
    (("zoom", "meet", "teams"), "meetings"),
    (("spotify", "mpv", "vlc", "rhythmbox"), "entertainment"),
]


def _class_hint(window_class: str) -> str | None:
    wc = (window_class or "").lower()
    for keys, cat in CLASS_HINTS:
        if any(k in wc for k in keys):
            return cat
    return None

PROMPT = """You are labeling a screenshot from a personal time-tracking system.
The window manager reports the focused window at this moment:
- Window class (application): {window_class}
- Window title: {window_title}

Pick exactly ONE category:
- deep_work_coding: writing/reading code in an editor or terminal
- deep_work_writing: writing prose, docs, notes, journaling
- deep_work_research: reading papers/docs, investigating a topic
- communication_messaging: chat apps (Slack, Discord, Beeper, SMS)
- communication_email: email client or webmail
- meetings: video calls, meeting apps
- planning_admin: calendar, task management, file/system admin
- learning: courses, tutorials, educational video
- social_media_browsing: social media, Reddit, HN, aimless browsing
- entertainment: entertainment video, games, music
- ai_interaction: Claude, ChatGPT, other LLM chats
- break_afk: lock screen, screensaver, no meaningful activity

Also give a SHORT task label (<=8 words) naming the specific thing being worked
on — use the window title (file path, repo, doc name, page/topic) as the main
clue, e.g. "editing daily_reflect/classifier.py", "reading Qwen3-VL blog",
"Slack #generator". Read visible on-screen text to refine it.

Respond with ONLY a JSON object, no markdown:
{{"category": "<one_of_the_above>", "task": "<short label>", "app": "<visible app name>", "confidence": "high|medium|low"}}"""


@dataclass
class Classification:
    category: str
    task: str
    app: str
    confidence: str
    model: str
    prompt_version: str
    error: str = ""
    retryable: bool = False


def _cache_key(model: str, prompt_version: str, frame_name: str) -> str:
    return f"{model}|{prompt_version}|{frame_name}"


def _parse_response(stdout: str, model: str, prompt_version: str) -> Classification:
    """Turn a raw Ollama response into a Classification (never raises)."""
    try:
        resp = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return Classification(UNCERTAIN, "", "unknown", "low", model, prompt_version,
                              error="ollama envelope unparseable", retryable=True)
    text = (resp.get("response") or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    start, end = text.find("{"), text.rfind("}") + 1
    if start < 0 or end <= start:
        return Classification(UNCERTAIN, "", "unknown", "low", model, prompt_version,
                              error="no json object in response")
    try:
        parsed = json.loads(text[start:end])
    except (json.JSONDecodeError, ValueError):
        return Classification(UNCERTAIN, "", "unknown", "low", model, prompt_version,
                              error="malformed json in response")
    category = parsed.get("category", UNCERTAIN)
    if category not in CATEGORIES:
        category = UNCERTAIN
    return Classification(
        category=category,
        task=str(parsed.get("task", ""))[:120],
        app=str(parsed.get("app", "unknown"))[:60],
        confidence=parsed.get("confidence", "medium") if parsed.get("confidence") in ("high", "medium", "low") else "medium",
        model=model,
        prompt_version=prompt_version,
    )


def classify_frame(
    path: Path,
    window_title: str,
    window_class: str,
    cfg: Config,
    focused_monitor: str | None = None,
) -> Classification:
    """Classify one frame. Crops to the focused monitor for multi-monitor frames."""
    try:
        prepared = prepare_image(path, focused_name=focused_monitor)
    except Exception as e:  # unreadable/corrupt image is content, not transport
        return Classification(UNCERTAIN, "", "unknown", "low", cfg.model, cfg.prompt_version,
                              error=f"image error: {str(e)[:80]}")

    img_b64 = base64.b64encode(prepared.data).decode()
    prompt = PROMPT.format(
        window_class=window_class or "unknown",
        window_title=window_title or "unknown",
    )
    payload = json.dumps({
        "model": cfg.model,
        "prompt": prompt,
        "images": [img_b64],
        "stream": False,
        "format": "json",
        "keep_alive": cfg.keep_alive,
        "options": {"temperature": 0.1},
    })

    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", str(cfg.request_timeout), cfg.ollama_url, "-d", "@-"],
            capture_output=True, text=True, timeout=cfg.request_timeout + 15, input=payload,
        )
    except subprocess.TimeoutExpired:
        return Classification(UNCERTAIN, "", "unknown", "low", cfg.model, cfg.prompt_version,
                              error="curl timeout", retryable=True)
    except Exception as e:
        return Classification(UNCERTAIN, "", "unknown", "low", cfg.model, cfg.prompt_version,
                              error=f"curl error: {str(e)[:80]}", retryable=True)

    if result.returncode != 0 or not result.stdout.strip():
        return Classification(UNCERTAIN, "", "unknown", "low", cfg.model, cfg.prompt_version,
                              error=f"curl rc={result.returncode}: {result.stderr[:80]}", retryable=True)
    return _parse_response(result.stdout, cfg.model, cfg.prompt_version)


# ---------------------------------------------------------------- cache I/O

def load_cache(cache_path: Path, cfg: Config) -> dict[str, Classification]:
    """Load cached classifications, keeping only entries for the current
    model+prompt_version and dropping any error/retryable rows."""
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, ValueError):
        return {}
    out: dict[str, Classification] = {}
    for k, v in data.items():
        try:
            c = Classification(**v)
        except TypeError:
            continue
        if c.model == cfg.model and c.prompt_version == cfg.prompt_version and not c.error and not c.retryable:
            out[k] = c
    return out


def save_cache(cache_path: Path, cache: dict[str, Classification]) -> None:
    """Persist only good (non-error, non-retryable) classifications."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: asdict(v) for k, v in cache.items() if not v.error and not v.retryable}
    cache_path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------- enrichment

def enrich_segments(
    segments: list[Segment],
    cfg: Config,
    cache_path: Path,
    progress: Callable[[int, int, str], None] | None = None,
    monitor_events: list[MonitorEvent] | None = None,
) -> tuple[int, int]:
    """Label segments, grouping by task so each distinct task is classified once.

    Because the window log has far more events than there are screenshots, many
    short segments share a ``task_key`` with a frame-bearing one. We classify a
    single representative frame per distinct task and apply the label to every
    segment with that key (framed or not). Tasks with no frame anywhere fall
    back to a window-class heuristic (or ``uncertain`` for browsers).

    ``monitor_events`` (from ``monitor_log``, when present) lets a multi-monitor
    frame be cropped to the exact focused pane; absent, cropping falls back to
    the dimension-inference content heuristic in ``prepare_image``.

    Returns ``(new_calls, cache_hits)``. Runs the VLM calls in a bounded pool.
    """
    monitor_events = monitor_events or []
    cache = load_cache(cache_path, cfg)

    # 1. group active segments by task_key
    groups: dict[str, list[Segment]] = {}
    for seg in segments:
        if seg.is_afk:
            seg.category, seg.task, seg.confidence = "break_afk", "away from keyboard", "high"
            continue
        groups.setdefault(seg.task_key, []).append(seg)

    # 2. pick a representative frame per group (best frame across its segments)
    reps: dict[str, object] = {}
    for key, segs in groups.items():
        best = None
        for seg in sorted(segs, key=lambda s: -s.duration_seconds):
            f = representative_frames(seg, k=1)
            if f:
                best = f[0]
                if best.is_png:
                    break
        if best is not None:
            reps[key] = best

    # 3. resolve: cache hit, else queue VLM work; frameless groups -> heuristic
    work: list[tuple[str, object]] = []
    hits = 0
    for key, segs in groups.items():
        frame = reps.get(key)
        if frame is None:
            hint = _class_hint(segs[0].window_class)
            for seg in segs:
                seg.category = hint or UNCERTAIN
                seg.task = _title_task(seg)
                seg.app = seg.window_class
                seg.confidence = "low"
            continue
        ck = _cache_key(cfg.model, cfg.prompt_version, frame.path.name)
        if ck in cache:
            for seg in segs:
                _apply(seg, cache[ck])
            hits += 1
        else:
            work.append((key, frame))

    # 4. classify queued groups in parallel
    new_calls = 0
    if work:
        with ThreadPoolExecutor(max_workers=max(1, cfg.concurrency)) as pool:
            futures = {}
            for key, frame in work:
                seg0 = groups[key][0]
                focused = focused_monitor_at(frame.dt, monitor_events)
                futures[pool.submit(classify_frame, frame.path, seg0.window_title, seg0.window_class, cfg, focused)] = (key, frame)
            done = 0
            for fut in as_completed(futures):
                key, frame = futures[fut]
                cls = fut.result()
                for seg in groups[key]:
                    _apply(seg, cls)
                if not cls.error and not cls.retryable:
                    cache[_cache_key(cfg.model, cfg.prompt_version, frame.path.name)] = cls
                new_calls += 1
                done += 1
                if progress and (done % 5 == 0 or done == len(work)):
                    progress(done, len(work), f"{cls.category}/{cls.confidence}")
                if done % 25 == 0:
                    save_cache(cache_path, cache)

    save_cache(cache_path, cache)
    return new_calls, hits


def _title_task(seg: Segment) -> str:
    from .segmenter import normalize_title
    return normalize_title(seg.window_title) or seg.window_class or "unknown"


def _apply(seg: Segment, cls: Classification) -> None:
    seg.category = cls.category or UNCERTAIN
    # prefer the VLM's task label; fall back to the window title
    seg.task = cls.task or _title_task(seg)
    seg.app = cls.app
    seg.confidence = cls.confidence
