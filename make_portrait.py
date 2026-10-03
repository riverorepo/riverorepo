"""Turn a photo into a neofetch-style ASCII portrait.

Usage:
    python make_portrait.py photo.png            # writes portrait_dark.txt + portrait_light.txt
    python make_portrait.py photo.png --cols 96  # wider = more detail

Needs: pip install pillow numpy opencv-python-headless rembg[cpu]
(rembg is optional; without it the photo is used as-is, so crop to the subject first.)
"""
import argparse, sys
import numpy as np
import cv2
from PIL import Image

RAMP = " .-:^~!*)|vztCo2e$&HD#MB"   # glyphs sorted by ink density (DejaVu Sans Mono)


def cut_out(img: Image.Image) -> Image.Image:
    """Remove the background with rembg and keep only the largest blob (the person)."""
    try:
        from rembg import remove, new_session
    except ImportError:
        print("rembg not installed; using the photo as-is", file=sys.stderr)
        return img.convert("RGBA")
    from scipy import ndimage
    out = remove(img.convert("RGBA"), session=new_session("u2net_human_seg"))
    a = np.array(out)
    mask = ndimage.binary_opening(a[:, :, 3] > 140, iterations=3)
    labels, n = ndimage.label(mask)
    if n > 1:
        sizes = ndimage.sum(mask, labels, range(1, n + 1))
        keep = ndimage.binary_dilation(labels == (np.argmax(sizes) + 1), iterations=2)
        a[:, :, 3] = np.where(keep, a[:, :, 3], 0)
    out = Image.fromarray(a)
    return out.crop(out.getbbox())


def to_ascii(img: Image.Image, cols=96, invert=True, gamma=1.3, unsharp=0.8, aspect=0.5):
    """invert=True: bright pixels -> dense glyphs (for dark backgrounds).
    invert=False: dark pixels -> dense glyphs (for light backgrounds)."""
    arr = np.array(img.convert("RGBA"))
    g = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    al = arr[:, :, 3].astype(np.float32) / 255.0
    if unsharp > 0:
        g = np.clip(g + unsharp * (g - cv2.GaussianBlur(g, (0, 0), 6)), 0, 1)
    h, w = g.shape
    rows = max(1, round(h * (cols / w) * aspect))
    gs = cv2.resize(g, (cols, rows), interpolation=cv2.INTER_AREA)
    als = cv2.resize(al, (cols, rows), interpolation=cv2.INTER_AREA)
    vis = gs[als > 0.5]
    lo, hi = np.percentile(vis, 1), np.percentile(vis, 99)
    lum = np.clip((gs - lo) / max(hi - lo, 1e-6), 0, 1)
    dens = (lum if invert else 1 - lum) ** gamma
    lines = []
    for r in range(rows):
        line = "".join(" " if als[r, c] < 0.4 else RAMP[int(round(dens[r, c] * (len(RAMP) - 1)))]
                       for c in range(cols))
        lines.append(line.rstrip())
    return lines


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--cols", type=int, default=96)
    ap.add_argument("--no-cutout", action="store_true", help="skip background removal")
    args = ap.parse_args()
    img = Image.open(args.photo)
    if not args.no_cutout:
        img = cut_out(img)
    # dark background: bright pixels -> ink (gamma 1.3); light background: dark pixels -> ink (gamma 0.75)
    for name, invert, gamma in (("portrait_dark.txt", True, 1.3), ("portrait_light.txt", False, 0.75)):
        lines = to_ascii(img, cols=args.cols, invert=invert, gamma=gamma)
        with open(name, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"wrote {name}: {len(lines)} rows x {max(map(len, lines))} cols")
