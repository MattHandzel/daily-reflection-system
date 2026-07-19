#!/usr/bin/env python3
"""VLM screenshot-classification benchmark harness (MAT-1461).

For each model, classify every manifest frame (whole image); for dual-monitor
frames also classify each per-monitor crop (DP-1 top, eDP-1 bottom-left).
Ollama is called via `curl` (python requests times out over Tailscale).
Resumable: skips (model, frame, view) rows already present in the JSONL.
GPU-polite: keep_alive 60s during a run, explicit unload (keep_alive 0) after
each model.

Outputs: outputs/<model_slug>.jsonl — one row per inference.
"""
import os, sys, json, base64, subprocess, time, tempfile
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
MANIFEST = os.path.join(BENCH, "manifest.json")
OUTDIR = os.path.join(BENCH, "outputs")
CROPDIR = os.path.join(BENCH, "crops")
SCREEN = os.path.expanduser("~/lifelog/data/screen")
HOST = "http://100.118.206.104:11434"
os.makedirs(OUTDIR, exist_ok=True)
os.makedirs(CROPDIR, exist_ok=True)

MODELS = [
    "qwen3-vl:8b",
    "qwen3.5:4b",
    "gemma3:12b-it-qat",   # substitute for gemma4:12b-it-qat (server Ollama 0.20.7 can't pull gemma4:12b, HTTP 412)
    "gemma4:e4b",          # bonus: Gemma-4 generation, resident on server
]

PROMPT = (
    "You are analyzing a screenshot of a Linux desktop. "
    "Respond with ONLY a compact JSON object, no markdown fences, with exactly these keys:\n"
    '{"primary_app": "name of the main/focused application or website in use", '
    '"activity": "one short phrase for what the user is doing", '
    '"window_title": "the exact text of the focused window title bar or browser tab, read verbatim"}'
)

LAPTOP_H, LAPTOP_W = 1800, 2880

def slug(m):
    return m.replace(":", "_").replace("/", "_").replace(".", "-")

def b64_file(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def ensure_crops(frame):
    """Generate DP-1 / eDP-1 crop files for a dual frame; return {view: path}."""
    base = frame[:-4]
    src = os.path.join(SCREEN, frame)
    out = {}
    for view, box_fn in (("DP-1", lambda W, H: (0, 0, W, H - LAPTOP_H)),
                          ("eDP-1", lambda W, H: (0, H - LAPTOP_H, min(LAPTOP_W, W), H))):
        p = os.path.join(CROPDIR, f"{base}__{view}.png")
        if not os.path.exists(p):
            im = Image.open(src)
            im.crop(box_fn(*im.size)).save(p)
        out[view] = p
    return out

def call(model, image_path):
    b64 = b64_file(image_path)
    payload = {"model": model, "prompt": PROMPT, "images": [b64], "stream": False,
               "think": False, "keep_alive": "60s", "options": {"temperature": 0, "num_predict": 1024}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(payload, tf)
        pf = tf.name
    try:
        t0 = time.time()
        r = subprocess.run(["curl", "-s", "--max-time", "300", "-X", "POST",
                            f"{HOST}/api/generate", "-d", f"@{pf}"],
                           capture_output=True, text=True)
        wall = time.time() - t0
    finally:
        os.unlink(pf)
    if r.returncode != 0 or not r.stdout:
        return {"error": f"curl rc={r.returncode} stderr={r.stderr[:200]}", "wall_s": wall}
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": "bad json from ollama", "raw": r.stdout[:300], "wall_s": wall}
    if "error" in d:
        return {"error": d["error"], "wall_s": wall}
    return {
        "response": d.get("response", ""),
        "thinking": d.get("thinking", "") or "",  # qwen3-vl misroutes JSON here at times
        "wall_s": round(wall, 2),
        "total_duration_s": round(d.get("total_duration", 0) / 1e9, 3),
        "load_duration_s": round(d.get("load_duration", 0) / 1e9, 3),
        "prompt_eval_count": d.get("prompt_eval_count"),
        "eval_count": d.get("eval_count"),
        "eval_duration_s": round(d.get("eval_duration", 0) / 1e9, 3),
    }

def vram(model):
    r = subprocess.run(["curl", "-s", "--max-time", "15", f"{HOST}/api/ps"],
                       capture_output=True, text=True)
    try:
        for m in json.loads(r.stdout).get("models", []):
            if m.get("name") == model or m.get("model") == model:
                return {"size_vram": m.get("size_vram"), "size": m.get("size")}
    except Exception:
        pass
    return None

def unload(model):
    payload = {"model": model, "keep_alive": 0, "prompt": ""}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(payload, tf); pf = tf.name
    subprocess.run(["curl", "-s", "--max-time", "30", "-X", "POST",
                    f"{HOST}/api/generate", "-d", f"@{pf}"], capture_output=True)
    os.unlink(pf)

def load_done(path):
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                r = json.loads(line)
                done.add((r["frame"], r["view"]))
            except Exception:
                pass
    return done

def main():
    manifest = json.load(open(MANIFEST))
    only = sys.argv[1] if len(sys.argv) > 1 else None
    models = [only] if only else MODELS
    for model in models:
        out = os.path.join(OUTDIR, f"{slug(model)}.jsonl")
        done = load_done(out)
        print(f"\n=== {model} -> {out} ({len(done)} already done) ===", flush=True)
        vram_recorded = False
        with open(out, "a") as fh:
            for i, p in enumerate(manifest):
                frame = p["frame"]
                views = {"whole": os.path.join(SCREEN, frame)}
                if p["layout"] == "dual":
                    views.update(ensure_crops(frame))
                for view, img_path in views.items():
                    if (frame, view) in done:
                        continue
                    res = call(model, img_path)
                    if not vram_recorded and "error" not in res:
                        res["_vram"] = vram(model)
                        vram_recorded = True
                    row = {"model": model, "frame": frame, "view": view,
                           "layout": p["layout"], "dims": p["dims"],
                           "gt_class": p["gt_class"], "gt_title": p["gt_title"],
                           "gt_delta_s": p["gt_delta_s"], **res}
                    fh.write(json.dumps(row) + "\n"); fh.flush()
                    tag = "ERR" if "error" in res else f"{res.get('total_duration_s')}s"
                    print(f"  [{i+1}/{len(manifest)}] {frame[:19]} {view:6} {tag}", flush=True)
        unload(model)
        print(f"  unloaded {model}", flush=True)

if __name__ == "__main__":
    main()
