"""Classify screenshots using Ollama VLM."""

import base64
import json
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

from .config import OLLAMA_URL, DEFAULT_MODEL

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

CLASSIFY_PROMPT = """Classify this screenshot into exactly ONE of these categories:
- deep_work_coding: Writing or reading code in an editor/terminal
- deep_work_writing: Writing prose, docs, notes, journaling
- deep_work_research: Reading papers, documentation, investigating a topic
- communication_messaging: Chat apps (Slack, Discord, Beeper, etc.)
- communication_email: Email client or webmail
- meetings: Video calls, meeting apps
- planning_admin: Calendar, task management, file organization
- learning: Educational content, courses, tutorials
- social_media_browsing: Social media, Reddit, HN, aimless browsing
- entertainment: YouTube entertainment, games, music
- ai_interaction: Claude, ChatGPT, LLM conversations
- break_afk: Lock screen, screensaver, no meaningful activity

Additional context — the active window at this time was:
Window class: {window_class}
Window title: {window_title}

IMPORTANT: Read the actual content visible on screen, not just the application chrome.
If this is a terminal/editor, read file paths, buffer names, and visible text to determine the task.

Respond with ONLY a JSON object (no markdown, no backticks):
{{"category": "one_of_the_above", "app": "visible application name", "detail": "brief description of what specifically is happening", "confidence": "high/medium/low"}}"""


@dataclass
class Classification:
    timestamp: str
    category: str
    app: str
    detail: str
    confidence: str

    def to_dict(self) -> dict:
        return asdict(self)


def classify_screenshot(
    path: Path,
    window_title: str = "",
    window_class: str = "",
    model: str = DEFAULT_MODEL,
) -> Classification:
    """Classify a single screenshot via Ollama VLM."""
    with open(path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    prompt = CLASSIFY_PROMPT.format(
        window_class=window_class or "unknown",
        window_title=window_title or "unknown",
    )

    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": 0.1},
        }
    )

    ts = path.name.replace(".thumb.jpg", "").replace(".png", "")

    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "60", OLLAMA_URL, "-d", "@-"],
            capture_output=True,
            text=True,
            timeout=90,
            input=payload,
        )

        if result.returncode != 0:
            return Classification(ts, "break_afk", "unknown", f"curl error: {result.stderr[:100]}", "low")

        resp = json.loads(result.stdout)
        response_text = resp.get("response", "")

        # Parse JSON from response (may have markdown backticks)
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()

        start_idx = text.find("{")
        end_idx = text.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            parsed = json.loads(text[start_idx:end_idx])
            category = parsed.get("category", "break_afk")
            if category not in CATEGORIES:
                category = "break_afk"
            return Classification(
                timestamp=ts,
                category=category,
                app=parsed.get("app", "unknown"),
                detail=parsed.get("detail", ""),
                confidence=parsed.get("confidence", "medium"),
            )

        return Classification(ts, "break_afk", "unknown", "failed to parse VLM response", "low")

    except Exception as e:
        return Classification(ts, "break_afk", "unknown", f"error: {str(e)[:100]}", "low")


def load_cache(cache_path: Path) -> dict[str, Classification]:
    """Load cached classifications from JSON file."""
    if not cache_path.exists():
        return {}
    with open(cache_path) as f:
        data = json.load(f)
    return {k: Classification(**v) for k, v in data.items()}


def save_cache(cache_path: Path, cache: dict[str, Classification]) -> None:
    """Save classifications to JSON cache file."""
    data = {k: v.to_dict() for k, v in cache.items()}
    with open(cache_path, "w") as f:
        json.dump(data, f, indent=2)
