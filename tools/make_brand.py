"""Generate the in-repo brand images.

Since Home Assistant 2026.3 a custom integration carries its own brand images
and no pull request against `home-assistant/brands` is needed. HACS reads
`custom_components/<domain>/brand/` first.

Sizes are exact requirements, not suggestions:

    icon.png       256x256 exactly
    icon@2x.png    512x512 exactly
    logo.png       shortest side 128-256
    logo@2x.png    shortest side 256-512

The mark is what the device is: a monitor with a live picture, a keyboard
under it, and the network lead that lets you reach both from elsewhere.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

BG = (16, 22, 30, 255)
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
    y0 = (h - box) / 2
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
    ly = (kb_y0 + kb_y1) / 2
    d.line([(x0 + box, ly), (x0 + box + pad * 0.7, ly)], fill=LEAD, width=line)
    r = line * 1.1
    d.ellipse(
        [x0 + box + pad * 0.7 - r, ly - r, x0 + box + pad * 0.7 + r, ly + r], fill=LEAD
    )
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
        draw(size, pad_frac=0.16).save(path, "PNG")
        print(f"  {name:14s} {size[0]}x{size[1]}")

    # Verify against the published rules rather than trusting the call above.
    ok = True
    for name, (want_w, want_h) in specs.items():
        with Image.open(os.path.join(out, name)) as im:
            w, h = im.size
        if name.startswith("icon"):
            good = (w, h) == (want_w, want_h) and w == h
        else:
            short = min(w, h)
            good = (256 <= short <= 512) if "@2x" in name else (128 <= short <= 256)
        print(f"  check {name:14s} {w}x{h} {'OK' if good else 'FAILS THE RULE'}")
        ok &= good
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
