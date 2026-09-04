"""Generate the in-repo brand images.

Since Home Assistant 2026.3 a custom integration carries its own brand images
and no pull request against `home-assistant/brands` is needed. HACS reads
`custom_components/<domain>/brand/` first.

Sizes are exact requirements, not suggestions:

    icon.png       256x256 exactly
    icon@2x.png    512x512 exactly
    logo.png       shortest side 128-256
    logo@2x.png    shortest side 256-512

home-assistant/brands asks for a transparent background and a mark that
fills the image, so the canvas is transparent and the padding is a few
percent, enough to keep the rounded corners off the edge.

The mark is what the device is: a monitor with a live picture, a keyboard
under it, and the network lead that lets you reach both from elsewhere.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

BG = (0, 0, 0, 0)
PAD_FRAC = 0.06
# The mark is a square's width but not its height: monitor (0.62), gap and
# stand (0.11), keyboard (0.15). It is centred vertically on this height.
MARK_H_FRAC = 0.88
BEZEL = (58, 68, 84, 255)
SCREEN = (72, 190, 232, 255)
PROMPT = (235, 245, 250, 255)
KEYS = (150, 162, 180, 255)
LEAD = (245, 176, 66, 255)


def draw(size: tuple[int, int], pad_frac: float) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, BG)
    d = ImageDraw.Draw(img)

    # Work in a square box centred on the canvas so the mark is the same on
    # the icon and the wide logo.
    side = min(w, h)
    pad = side * pad_frac
    box = side - 2 * pad
    x0 = (w - box) / 2
    y0 = (h - box * MARK_H_FRAC) / 2
    line = max(2, int(box * 0.045))
    radius = box * 0.06

    # Monitor: bezel and picture.
    mon_x0, mon_y0 = x0, y0
    mon_x1, mon_y1 = x0 + box, y0 + box * 0.62
    d.rounded_rectangle([mon_x0, mon_y0, mon_x1, mon_y1], radius=radius, fill=BEZEL)
    inset = box * 0.06
    d.rounded_rectangle(
        [mon_x0 + inset, mon_y0 + inset, mon_x1 - inset, mon_y1 - inset],
        radius=radius * 0.6,
        fill=SCREEN,
    )
    # A prompt on the screen: the picture is a computer, not a film.
    px = mon_x0 + inset + box * 0.08
    py = mon_y0 + inset + box * 0.10
    d.line(
        [(px, py), (px + box * 0.10, py + box * 0.08), (px, py + box * 0.16)],
        fill=PROMPT,
        width=line,
    )
    d.line(
        [(px + box * 0.14, py + box * 0.16), (px + box * 0.30, py + box * 0.16)],
        fill=PROMPT,
        width=line,
    )

    # Stand.
    sx = x0 + box / 2
    d.rectangle(
        [sx - box * 0.05, mon_y1, sx + box * 0.05, mon_y1 + box * 0.07], fill=BEZEL
    )

    # Keyboard: a bar with key ticks.
    kb_y0 = mon_y1 + box * 0.11
    kb_y1 = kb_y0 + box * 0.15
    d.rounded_rectangle([x0, kb_y0, x0 + box, kb_y1], radius=radius * 0.5, fill=BEZEL)
    ticks = 7
    gap = box / (ticks + 1)
    for i in range(1, ticks + 1):
        tx = x0 + gap * i
        d.line(
            [(tx, kb_y0 + box * 0.045), (tx, kb_y1 - box * 0.045)],
            fill=KEYS,
            width=line,
        )

    # Network lead, out of the keyboard and off to the right: the "over IP".
    # It runs into the padding, stopping short of the edge by the plug's
    # radius so nothing is clipped.
    ly = (kb_y0 + kb_y1) / 2
    r = line * 1.1
    end = min(x0 + box + pad * 0.9, w - r - 1)
    d.line([(x0 + box, ly), (end, ly)], fill=LEAD, width=line)
    d.ellipse([end - r, ly - r, end + r, ly + r], fill=LEAD)
    return img


def main() -> None:
    out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "custom_components",
        "glkvm",
        "brand",
    )
    os.makedirs(out, exist_ok=True)
    specs = {
        "icon.png": (256, 256),
        "icon@2x.png": (512, 512),
        "logo.png": (512, 256),
        "logo@2x.png": (1024, 512),
    }
    for name, size in specs.items():
        path = os.path.join(out, name)
        draw(size, pad_frac=PAD_FRAC).save(path, "PNG")
        print(f"  {name:14s} {size[0]}x{size[1]}")

    # Verify against the published rules rather than trusting the call above:
    # the sizes, a transparent background (the corners are the one place the
    # mark never reaches), and a mark that fills the square rather than
    # floating in it.
    ok = True
    for name, (want_w, want_h) in specs.items():
        with Image.open(os.path.join(out, name)) as im:
            w, h = im.size
            alpha = im.convert("RGBA").getchannel("A")
        if name.startswith("icon"):
            good = (w, h) == (want_w, want_h) and w == h
        else:
            short = min(w, h)
            good = (256 <= short <= 512) if "@2x" in name else (128 <= short <= 256)
        corners = [alpha.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1))]
        transparent = all(a == 0 for a in corners)
        left, top, right, bottom = alpha.getbbox() or (0, 0, 0, 0)
        # The mark spans the square minus the padding: its full width, and
        # its own height, with a pixel of slack for anti-aliasing.
        box = min(w, h) * (1 - 2 * PAD_FRAC)
        filled = (right - left) >= box - 2 and (bottom - top) >= box * MARK_H_FRAC - 2
        verdict = "OK" if good and transparent and filled else "FAILS THE RULE"
        print(
            f"  check {name:14s} {w}x{h} transparent={transparent} "
            f"filled={filled} {verdict}"
        )
        ok &= good and transparent and filled
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
