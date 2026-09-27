#!/usr/bin/env python3
"""
Generates a self-hosted animated SVG banner (typewriter text + glitter
sparkles) for the profile README. Pure SVG + CSS animation, no JS, no
third-party rendering service (github-readme-typing-svg etc.) involved.

Run manually whenever you want to change the phrases:
    python scripts/generate_banner.py
"""

import os
import random

PHRASES = [
    "Hey there!",
    "Welcome to my GitHub profile!",
    "Take a look around!",
]

FONT_SIZE = 20
CHAR_WIDTH = 12  # forced via textLength, so this is exact, not a guess
BASE_X = 20
BASE_Y = 40
CARET_WIDTH = 3
CARET_GAP = 4

PER_CHAR_TYPE = 0.09
PER_CHAR_ERASE = 0.05
HOLD_DUR = 1.3
GAP_DUR = 0.4

TEXT_COLOR = "#2d77dc"
SPARKLE_COLOR = "#e3b341"

random.seed(7)


def phrase_width(text):
    return len(text) * CHAR_WIDTH


def build_timeline():
    """Returns per-phrase timing windows (in seconds) and the total cycle length."""
    windows = []
    t = 0.0
    for phrase in PHRASES:
        start = t
        type_end = start + len(phrase) * PER_CHAR_TYPE
        hold_end = type_end + HOLD_DUR
        erase_end = hold_end + len(phrase) * PER_CHAR_ERASE
        phase_end = erase_end + GAP_DUR
        windows.append(
            {
                "phrase": phrase,
                "start": start,
                "type_end": type_end,
                "hold_end": hold_end,
                "erase_end": erase_end,
                "phase_end": phase_end,
            }
        )
        t = phase_end
    return windows, t


def pct(t, total):
    return round(t / total * 100, 4)


def render_reveal_keyframes(name, windows, total):
    """One @keyframes per phrase: its clip-rect width goes 0 -> full -> full -> 0,
    staying 0 for the rest of the cycle. steps() per keyframe segment gives the
    per-character snap for both typing and erasing."""
    blocks = []
    for i, w in enumerate(windows):
        full = phrase_width(w["phrase"])
        stops = []

        start_p = pct(w["start"], total)
        type_p = pct(w["type_end"], total)
        hold_p = pct(w["hold_end"], total)
        erase_p = pct(w["erase_end"], total)

        if start_p > 0:
            stops.append((0, 0, None))
        stops.append((start_p, 0, f"steps({max(len(w['phrase']), 1)})"))
        stops.append((type_p, full, "linear"))
        stops.append((hold_p, full, f"steps({max(len(w['phrase']), 1)})"))
        stops.append((erase_p, 0, "linear"))
        if erase_p < 100:
            stops.append((100, 0, None))

        lines = []
        for p, val, timing in stops:
            tf = f" animation-timing-function: {timing};" if timing else ""
            lines.append(f"      {p}% {{ width: {val}px;{tf} }}")

        blocks.append(f"    @keyframes {name}-{i} {{\n" + "\n".join(lines) + "\n    }")
    return "\n".join(blocks)


def render_caret_keyframes(windows, total):
    """Single caret shared across all phrases: x tracks whichever phrase is
    currently typing/erasing, resting at BASE_X during hold/gap."""
    stops = []
    if windows[0]["start"] > 0:
        stops.append((0, 0, None))

    for w in windows:
        full = phrase_width(w["phrase"])
        start_p = pct(w["start"], total)
        type_p = pct(w["type_end"], total)
        hold_p = pct(w["hold_end"], total)
        erase_p = pct(w["erase_end"], total)
        n = max(len(w["phrase"]), 1)

        stops.append((start_p, 0, f"steps({n})"))
        stops.append((type_p, full, "linear"))
        stops.append((hold_p, full, f"steps({n})"))
        stops.append((erase_p, 0, "linear"))

    if stops[-1][0] < 100:
        stops.append((100, 0, None))

    lines = []
    for p, val, timing in stops:
        tf = f" animation-timing-function: {timing};" if timing else ""
        lines.append(f"      {p}% {{ transform: translateX({val}px);{tf} }}")

    return "    @keyframes caret-move {\n" + "\n".join(lines) + "\n    }"


def render_sparkles(count, area_width, area_height):
    sparkles = []
    for i in range(count):
        cx = random.uniform(10, area_width - 10)
        cy = random.choice([random.uniform(6, 14), random.uniform(area_height - 16, area_height - 6)])
        r = random.uniform(3.5, 6)
        dur = round(random.uniform(1.6, 2.8), 2)
        delay = round(random.uniform(0, 2.4), 2)
        d = (
            f"M {cx} {cy - r} L {cx + r * 0.28:.2f} {cy - r * 0.28:.2f} "
            f"L {cx + r} {cy} L {cx + r * 0.28:.2f} {cy + r * 0.28:.2f} "
            f"L {cx} {cy + r} L {cx - r * 0.28:.2f} {cy + r * 0.28:.2f} "
            f"L {cx - r} {cy} L {cx - r * 0.28:.2f} {cy - r * 0.28:.2f} Z"
        )
        sparkles.append(
            f'<path d="{d}" fill="{SPARKLE_COLOR}" class="sparkle" '
            f'style="animation-duration:{dur}s; animation-delay:-{delay}s;"/>'
        )
    return "\n  ".join(sparkles)


def render_banner():
    windows, total = build_timeline()
    max_width = max(phrase_width(w["phrase"]) for w in windows)
    card_width = BASE_X + max_width + CARET_GAP + CARET_WIDTH + 20
    card_height = 64

    text_groups = []
    for i, w in enumerate(windows):
        clip_id = f"clip-{i}"
        text_groups.append(f"""
  <clipPath id="{clip_id}">
    <rect x="{BASE_X}" y="0" height="{FONT_SIZE + 10}" class="reveal-{i}"/>
  </clipPath>
  <text x="{BASE_X}" y="{BASE_Y}" textLength="{phrase_width(w['phrase'])}" lengthAdjust="spacingAndGlyphs"
        class="banner-text" clip-path="url(#{clip_id})">{escape(w['phrase'])}</text>""")

    reveal_css = render_reveal_keyframes("reveal", windows, total)
    caret_css = render_caret_keyframes(windows, total)
    sparkles = render_sparkles(7, card_width, card_height)

    reveal_rules = "\n".join(
        f"    .reveal-{i} {{ width: 0; animation: reveal-{i} {total:.3f}s linear infinite; }}"
        for i in range(len(windows))
    )

    return f"""<svg width="{card_width:.0f}" height="{card_height}" viewBox="0 0 {card_width:.0f} {card_height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .banner-text {{
      font: 600 {FONT_SIZE}px 'Consolas', 'Fira Code', monospace;
      fill: {TEXT_COLOR};
    }}
{reveal_rules}
    .caret {{
      fill: {TEXT_COLOR};
      animation: caret-move {total:.3f}s linear infinite, caret-blink 0.85s step-end infinite;
    }}
    .sparkle {{
      opacity: 0;
      transform-origin: center;
      animation-name: twinkle;
      animation-timing-function: ease-in-out;
      animation-iteration-count: infinite;
    }}
{reveal_css}
{caret_css}
    @keyframes caret-blink {{
      0%, 50% {{ opacity: 1; }}
      50.01%, 100% {{ opacity: 0; }}
    }}
    @keyframes twinkle {{
      0%, 100% {{ opacity: 0; transform: scale(0.5); }}
      50% {{ opacity: 0.9; transform: scale(1.1); }}
    }}
  </style>
  {sparkles}
  {''.join(text_groups)}
  <rect x="{BASE_X - CARET_WIDTH}" y="{BASE_Y - FONT_SIZE + 4}" width="{CARET_WIDTH}" height="{FONT_SIZE + 2}" class="caret"/>
</svg>
"""


def escape(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def main():
    svg = render_banner()
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "banner.svg")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
