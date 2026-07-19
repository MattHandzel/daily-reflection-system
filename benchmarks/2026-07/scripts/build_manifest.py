#!/usr/bin/env python3
"""Build a stratified ~60-frame benchmark manifest from ~/lifelog/data/screen.

Ground truth for the *focused* window comes from hyprland_log (nearest timestamp
within 15s). Frames are stratified across apps, times of day, and single- vs
dual-monitor layout (dual only exists 2026-07-03+, height > 1800).

Output: manifest.json — list of {frame, ts, dims, layout, gt_class, gt_title, gt_delta_s}
"""
import os, sqlite3, json, bisect, random, re
from datetime import datetime, timezone
from collections import defaultdict
from PIL import Image

random.seed(1461)
SCREEN = os.path.expanduser("~/lifelog/data/screen")
DB = os.path.expanduser("~/lifelog/data/index.db")
OUT = os.path.join(os.path.dirname(__file__), "..", "manifest.json")
DUAL_ERA = "2026-07-03"
ISO_RE = re.compile(r"^20\d\d-\d\d-\d\dT.*\.png$")

def parse_dt(name):
    # 2026-07-16T23:41:15.491867+00:00.png
    stem = name[:-4]
    return datetime.fromisoformat(stem)

# --- load hyprland_log sorted ---
con = sqlite3.connect(DB)
hlog = con.execute("SELECT timestamp, window_class, window_title FROM hyprland_log ORDER BY timestamp").fetchall()
h_ts = [datetime.fromisoformat(r[0]) for r in hlog]
print(f"hyprland_log rows: {len(hlog)}")

def nearest_gt(dt):
    i = bisect.bisect_left(h_ts, dt)
    best = None
    for j in (i-1, i):
        if 0 <= j < len(h_ts):
            d = abs((h_ts[j]-dt).total_seconds())
            if best is None or d < best[0]:
                best = (d, hlog[j][1], hlog[j][2])
    return best  # (delta_s, class, title)

# --- list frames ---
names = [n for n in os.listdir(SCREEN) if ISO_RE.match(n) and "thumb" not in n]
print(f"full ISO PNGs on disk: {len(names)}")
frames = []
for n in names:
    try:
        dt = parse_dt(n)
    except ValueError:
        continue
    frames.append((n, dt))
frames.sort(key=lambda x: x[1])

# attach ground truth to all (fast bisect)
pool = []
for n, dt in frames:
    gt = nearest_gt(dt)
    if gt is None or gt[0] > 15:  # require GT within 15s
        continue
    pool.append({"frame": n, "ts": dt.isoformat(), "dt": dt,
                 "gt_delta_s": round(gt[0], 1), "gt_class": gt[1], "gt_title": gt[2]})
print(f"frames with GT within 15s: {len(pool)}")

# --- find dual-monitor frames: scan 07-03+ opening dims until we have enough ---
dual_candidates = []
recent = [p for p in pool if p["ts"] >= DUAL_ERA]
random.shuffle(recent)
scanned = 0
for p in recent:
    if len(dual_candidates) >= 40:
        break
    try:
        with Image.open(os.path.join(SCREEN, p["frame"])) as im:
            w, h = im.size
    except Exception:
        continue
    scanned += 1
    p["dims"] = [w, h]
    if h > 1800:
        p["layout"] = "dual"
        dual_candidates.append(p)
print(f"scanned {scanned} recent frames, found {len(dual_candidates)} dual")

# --- stratify helper: spread across gt_class and hour ---
def stratify(items, k):
    by_class = defaultdict(list)
    for it in items:
        by_class[it["gt_class"]].append(it)
    for v in by_class.values():
        random.shuffle(v)
    chosen = []
    classes = list(by_class.keys())
    random.shuffle(classes)
    # round-robin across classes for variety
    while len(chosen) < k and any(by_class.values()):
        for c in classes:
            if by_class[c]:
                chosen.append(by_class[c].pop())
                if len(chosen) >= k:
                    break
    return chosen

# dual sample: up to 15
dual_sample = stratify(dual_candidates, min(15, len(dual_candidates)))
for p in dual_sample:
    p["layout"] = "dual"

# single sample: 45, from frames NOT chosen as dual; dims filled at inference time
dual_frames = {p["frame"] for p in dual_sample}
single_pool = [p for p in pool if p["frame"] not in dual_frames]
single_sample = stratify(single_pool, 45)
# fill dims for single sample (open image)
for p in single_sample:
    if "dims" not in p:
        try:
            with Image.open(os.path.join(SCREEN, p["frame"])) as im:
                p["dims"] = list(im.size)
        except Exception:
            p["dims"] = None
    # a "single-era" frame could actually be dual if 07-03+; classify by height
    h = p["dims"][1] if p["dims"] else 0
    p["layout"] = "dual" if h > 1800 else "single"

manifest = dual_sample + single_sample
# clean non-serializable
for p in manifest:
    p.pop("dt", None)
manifest.sort(key=lambda x: x["ts"])

with open(OUT, "w") as f:
    json.dump(manifest, f, indent=2)

n_dual = sum(1 for p in manifest if p["layout"] == "dual")
n_single = sum(1 for p in manifest if p["layout"] == "single")
print(f"\nMANIFEST: {len(manifest)} frames -> single={n_single} dual={n_dual}")
print("class distribution:")
cd = defaultdict(int)
for p in manifest:
    cd[p["gt_class"]] += 1
for c, n in sorted(cd.items(), key=lambda x: -x[1]):
    print(f"  {n:3d}  {c}")
print(f"\nwrote {OUT}")
