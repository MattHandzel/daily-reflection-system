#!/usr/bin/env python3
"""Split a composited dual-monitor grim frame into per-monitor crops.

Layout (from research/capture-infra-findings + capture geometry):
  eDP-1 laptop = 2880x1800 @ bottom-left; DP-1 external stacked ABOVE it.
  Composited bounding box (W, H): DP-1 occupies top rows (0..H-1800, full W),
  eDP-1 occupies bottom-left (H-1800..H, 0..2880).
Verified on 3840x3960 (DP-1 3840x2160) and 5120x4680 (DP-1 5120x2880, scale 0.75).
"""
import sys, os
from PIL import Image

LAPTOP_H = 1800
LAPTOP_W = 2880

def crops(path):
    """Return {'DP-1': PIL.Image, 'eDP-1': PIL.Image} for a dual frame."""
    im = Image.open(path)
    W, H = im.size
    top_h = H - LAPTOP_H
    dp1 = im.crop((0, 0, W, top_h))              # external monitor (top)
    edp1 = im.crop((0, top_h, min(LAPTOP_W, W), H))  # laptop (bottom-left)
    return {"DP-1": dp1, "eDP-1": edp1}

if __name__ == "__main__":
    path = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else "."
    c = crops(path)
    base = os.path.splitext(os.path.basename(path))[0]
    for name, img in c.items():
        out = os.path.join(outdir, f"{base}__{name}.png")
        img.save(out)
        print(f"{name}: {img.size} -> {out}")
