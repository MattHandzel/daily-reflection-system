"""Multi-monitor frame handling.

``grim`` captures the whole compositor space as one image, so a dual-monitor
frame is two screens stacked into a single PNG. Empirically (capture-infra
audit): laptop-only frames are 2880x1800; dual frames are 3840x3960 (DP-1 4K
stacked above the laptop) and a couple of scaled variants.

We detect multi-monitor frames by dimensions, crop each monitor's pane, and —
when the focused monitor is unknown (``monitor_log`` table not yet populated) —
pick the pane with the most on-screen content as the likely-focused one. When
that table lands, pass ``focused_box`` to skip the heuristic.
"""

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

MAX_DIM = 1600  # downscale longest side before sending to the VLM

# Known compositor-space layouts -> list of (monitor_name, (left, top, right, bottom)).
# Panes are cropped to each monitor's real resolution inside the bounding box;
# the empty corner of a stacked capture is simply never cropped.
KNOWN_LAYOUTS: dict[tuple[int, int], list[tuple[str, tuple[int, int, int, int]]]] = {
    (2880, 1800): [("eDP-1", (0, 0, 2880, 1800))],
    # DP-1 4K (3840x2160) on top, laptop (2880x1800) bottom-left.
    (3840, 3960): [("DP-1", (0, 0, 3840, 2160)), ("eDP-1", (0, 2160, 2880, 3960))],
    (5120, 4680): [("DP-1", (0, 0, 5120, 2880)), ("eDP-1", (0, 2880, 2880, 4680))],
    (4800, 4500): [("DP-1", (0, 0, 4800, 2700)), ("eDP-1", (0, 2700, 2880, 4500))],
}


@dataclass
class PreparedImage:
    data: bytes  # PNG bytes ready to base64-encode for Ollama
    width: int
    height: int
    is_multi: bool
    pane: str  # monitor name of the pane sent, or "full"


def _panes_for(width: int, height: int) -> list[tuple[str, tuple[int, int, int, int]]]:
    if (width, height) in KNOWN_LAYOUTS:
        return KNOWN_LAYOUTS[(width, height)]
    # Generic fallbacks for unknown multi-monitor captures. Vertical stack: a
    # capture much taller than a single monitor. Horizontal: much wider than a
    # single monitor. Otherwise treat as one image (let the VLM's dynamic
    # resolution cope).
    if height > width * 1.15 and height > 2400:
        top = min(2160, height // 2)
        return [("top", (0, 0, width, top)), ("bottom", (0, top, min(2880, width), height))]
    if width > height * 1.8 and width > 3840:
        mid = width // 2
        return [("left", (0, 0, mid, height)), ("right", (mid, 0, width, height))]
    return []


def _content_score(img: Image.Image) -> float:
    """Higher = more visual content (proxy for the active/focused monitor)."""
    small = img.convert("L").resize((64, 64))
    px = list(small.getdata())
    n = len(px)
    mean = sum(px) / n
    var = sum((p - mean) ** 2 for p in px) / n
    non_black = sum(1 for p in px if p > 12) / n
    return var * non_black


def _encode(img: Image.Image) -> bytes:
    if max(img.size) > MAX_DIM:
        scale = MAX_DIM / max(img.size)
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def prepare_image(path: Path, focused_box: tuple[int, int, int, int] | None = None) -> PreparedImage:
    """Load a frame, crop to the focused monitor if multi, downscale, encode.

    ``focused_box`` (from ``monitor_log`` when available) forces the pane; else
    the pane with the most content is chosen for dual-monitor frames.
    """
    img = Image.open(path)
    img.load()
    w, h = img.size
    panes = _panes_for(w, h)
    is_multi = len(panes) > 1

    if focused_box is not None:
        crop = img.crop(focused_box)
        return PreparedImage(_encode(crop), w, h, is_multi, "focused")

    if not is_multi:
        return PreparedImage(_encode(img), w, h, False, "full")

    best_name, best_img, best_score = "full", img, -1.0
    for name, box in panes:
        try:
            pane_img = img.crop(box)
        except Exception:
            continue
        score = _content_score(pane_img)
        if score > best_score:
            best_name, best_img, best_score = name, pane_img, score
    return PreparedImage(_encode(best_img), w, h, True, best_name)
