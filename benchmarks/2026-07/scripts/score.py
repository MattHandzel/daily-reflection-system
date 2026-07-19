#!/usr/bin/env python3
"""Score VLM benchmark outputs (MAT-1461).

Reads outputs/*.jsonl, parses each model's JSON answer, and computes per model:
  - app-identification accuracy (does the answer name the focused app/site?)
  - small-text fidelity (recall of hyprland_log window-title tokens)
  - latency (median inference seconds = total_duration - load_duration)
  - VRAM footprint
  - dual-monitor: whole-image vs per-monitor-split accuracy

Ground truth = focused window (class+title) from hyprland_log within 15s.
The app metric is a lenient token-containment proxy; raw answers are kept for
audit and a manual spot-check subset is emitted.
"""
import os, json, re, glob, statistics
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
OUTDIR = os.path.join(BENCH, "outputs")

STOP = {"google","default","the","and","for","with","new","tab","page","http","https",
        "www","com","html","this","that","from","your","you","are"}

def canon(gt_class):
    """Return (category, set_of_app_tokens) expected for a hyprland window class."""
    c = (gt_class or "").lower()
    if "kitty" in c or "alacritty" in c or "foot" in c:
        return "terminal", {"terminal","kitty","shell","console","command","bash","zsh","nvim","vim","tmux"}
    if c.startswith("chrome-") or c.startswith("chromium") or c.startswith("brave") \
       or "zen-" in c or c in ("firefox","zen") or "browser" in c:
        toks = {"browser","chrome","chromium","brave","firefox","zen","tab","website","web"}
        for site,names in {"linear":{"linear"},"claude.ai":{"claude","ai"},
                           "calendar.google":{"calendar","schedule"},"gemini":{"gemini"},
                           "gmail":{"gmail","mail","email"},"github":{"github"},
                           "server.matthandzel":{"lifelog"},"youtube":{"youtube","video"}}.items():
            if site in c: toks |= names
        return "browser", toks
    if "slack" in c: return "chat", {"slack"}
    if "discord" in c: return "chat", {"discord"}
    if "beeper" in c: return "chat", {"beeper","messages","texts","messaging","chat"}
    if "thunderbird" in c or "betterbird" in c: return "email", {"thunderbird","betterbird","email","mail","inbox"}
    if "zoom" in c: return "video", {"zoom","meeting","call","video","conference"}
    if "minecraft" in c: return "game", {"minecraft","game"}
    if "obsproject" in c: return "media", {"obs","studio","stream","recording"}
    if "nautilus" in c or "dolphin" in c: return "files", {"file","files","nautilus","dolphin","folder","manager"}
    if "mpv" in c or "feh" in c: return "media", {"mpv","feh","image","video","viewer","player","photo"}
    if "calibre" in c: return "reader", {"calibre","ebook","book","reader","library"}
    if "gimp" in c: return "editor", {"gimp","image","editor"}
    if "obsidian" in c: return "notes", {"obsidian","note","notes","markdown"}
    if c == "claude" or "claude" in c: return "chat", {"claude","ai","chat"}
    if "capture" in c or "knowledge-management" in c: return "capture", {"capture","knowledge","kms","note"}
    if "wispr" in c: return "dictation", {"wispr","flow","dictation","transcri"}
    if "anki" in c: return "study", {"anki","flashcard","card","review"}
    if "pavucontrol" in c or "pwvucontrol" in c or "pulseaudio" in c: return "audio", {"volume","audio","sound","mixer"}
    if "zoom" in c: return "video", {"zoom"}
    if not c or c == "none": return None, set()
    return "other", {c.split(".")[-1].split("-")[0]}

def parse_answer(resp):
    if not resp: return None
    s = resp.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m: return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def toks(text):
    return {t for t in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if t not in STOP}

def answer_text(ans):
    if not ans: return ""
    parts = [str(ans.get("primary_app","")), str(ans.get("activity","")),
             str(ans.get("window_title",""))]
    vt = ans.get("visible_text")
    if isinstance(vt, list): parts += [str(x) for x in vt]
    elif vt: parts.append(str(vt))
    return " ".join(parts).lower()

def title_field(ans):
    if not ans: return ""
    parts = [str(ans.get("window_title",""))]
    vt = ans.get("visible_text")
    if isinstance(vt, list): parts += [str(x) for x in vt]
    elif vt: parts.append(str(vt))
    return " ".join(parts)

def score_row(row):
    ans = parse_answer(row.get("response",""))
    if ans is None:  # qwen3-vl sometimes emits the JSON into the thinking field
        ans = parse_answer(row.get("thinking",""))
    cat, app_toks = canon(row["gt_class"])
    text = answer_text(ans)
    # app hit: any expected app token present in the answer text
    app_hit = None
    if app_toks:
        app_hit = any(t in text for t in app_toks)
    # title recall: fraction of significant gt_title tokens found in model's title/text
    gt_toks = toks(row.get("gt_title",""))
    ans_toks = toks(title_field(ans))
    title_recall = (len(gt_toks & ans_toks) / len(gt_toks)) if gt_toks else None
    infer_s = None
    if row.get("total_duration_s") is not None:
        infer_s = round(row["total_duration_s"] - (row.get("load_duration_s") or 0), 2)
    return {"parsed": ans is not None, "app_hit": app_hit, "cat": cat,
            "title_recall": title_recall, "infer_s": infer_s,
            "err": row.get("error")}

def main():
    results = {}
    spot = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(OUTDIR, "*.jsonl"))):
        model = None
        rows = [json.loads(l) for l in open(path) if l.strip()]
        if not rows: continue
        model = rows[0]["model"]
        agg = {"n":0,"err":0,"parsed":0,"app_hits":[],"title_recalls":[],
               "infer_single":[],"infer_all":[],"vram":None,
               "dual_whole_app":[],"dual_split_app":[],"dual_whole_title":[],"dual_split_title":[]}
        # group by frame for dual whole-vs-split
        by_frame = defaultdict(dict)
        for r in rows:
            if r.get("_vram"): agg["vram"] = r["_vram"]
            s = score_row(r)
            agg["n"] += 1
            if s["err"]: agg["err"] += 1; continue
            if s["parsed"]: agg["parsed"] += 1
            by_frame[r["frame"]][r["view"]] = (r, s)
            if r["view"] == "whole":
                if s["app_hit"] is not None: agg["app_hits"].append(s["app_hit"])
                if s["title_recall"] is not None: agg["title_recalls"].append(s["title_recall"])
                if s["infer_s"] is not None:
                    agg["infer_all"].append(s["infer_s"])
                    if r["layout"] == "single": agg["infer_single"].append(s["infer_s"])
        # dual whole vs split
        for frame, views in by_frame.items():
            if "whole" not in views: continue
            wr, ws = views["whole"]
            if wr["layout"] != "dual": continue
            crops = [views[v] for v in ("DP-1","eDP-1") if v in views]
            if not crops: continue
            if ws["app_hit"] is not None:
                agg["dual_whole_app"].append(ws["app_hit"])
                agg["dual_split_app"].append(any(cs["app_hit"] for _,cs in crops if cs["app_hit"] is not None))
            if ws["title_recall"] is not None:
                agg["dual_whole_title"].append(ws["title_recall"])
                agg["dual_split_title"].append(max([cs["title_recall"] for _,cs in crops if cs["title_recall"] is not None] or [0]))
            # collect spot-check
            spot[model].append({"frame":frame,"gt_class":wr["gt_class"],"gt_title":(wr["gt_title"] or "")[:60],
                                "whole_app":ws["app_hit"],"whole_title_recall":ws["title_recall"]})
        results[model] = agg

    def pct(lst): return round(100*sum(lst)/len(lst),1) if lst else None
    def med(lst): return round(statistics.median(lst),1) if lst else None

    print(f"{'model':22} {'n':>4} {'err':>4} {'parse%':>7} {'app_acc%':>9} {'title_rec%':>11} {'med_infer_s':>12} {'single_s':>9} {'vram_GB':>8}")
    summary = {}
    for model, a in results.items():
        # 'size' = full model memory footprint (stable); 'size_vram' fluctuates under GPU contention
        vram_gb = round(a["vram"]["size"]/1e9,2) if a["vram"] and a["vram"].get("size") else None
        row = {"n":a["n"],"err":a["err"],"parse_pct":round(100*a["parsed"]/max(1,a["n"]-a["err"]),1),
               "app_acc":pct(a["app_hits"]),"title_recall":pct([1 if x>0 else 0 for x in a["title_recalls"]]),
               "title_recall_mean":round(100*statistics.mean(a["title_recalls"]),1) if a["title_recalls"] else None,
               "med_infer_s":med(a["infer_all"]),"med_single_s":med(a["infer_single"]),"vram_gb":vram_gb,
               "dual_whole_app":pct(a["dual_whole_app"]),"dual_split_app":pct(a["dual_split_app"]),
               "dual_whole_title_mean":round(100*statistics.mean(a["dual_whole_title"]),1) if a["dual_whole_title"] else None,
               "dual_split_title_mean":round(100*statistics.mean(a["dual_split_title"]),1) if a["dual_split_title"] else None,
               "n_app_scored":len(a["app_hits"]),"n_dual":len(a["dual_whole_app"])}
        summary[model] = row
        print(f"{model:22} {a['n']:>4} {a['err']:>4} {row['parse_pct']:>7} {str(row['app_acc']):>9} {str(row['title_recall']):>11} {str(row['med_infer_s']):>12} {str(row['med_single_s']):>9} {str(vram_gb):>8}")

    print("\nDUAL whole vs split (app_acc% / mean title-recall%):")
    for model, r in summary.items():
        print(f"  {model:22} app: whole {r['dual_whole_app']} -> split {r['dual_split_app']} | title: whole {r['dual_whole_title_mean']} -> split {r['dual_split_title_mean']} (n={r['n_dual']})")

    json.dump({"summary":summary,"spot":spot}, open(os.path.join(BENCH,"results.json"),"w"), indent=2)
    print(f"\nwrote {os.path.join(BENCH,'results.json')}")

if __name__ == "__main__":
    main()
