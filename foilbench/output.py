"""Export tabular findings and a marked view of the capture used for a report."""

import csv
from io import StringIO

import numpy as np
from PIL import Image, ImageDraw

from . import analysis, frame


def csv_text(report):
    target = StringIO(newline="")
    writer = csv.writer(target)
    writer.writerow(("mode", report["mode"], "light", report["settings"]["light"],
                     "dual_light", report.get("dual_light", False)))
    writer.writerow(("x0", "y0", "x1", "y1", "threshold", "mm_per_pixel", "min_pixels"))
    chosen = report["settings"]
    writer.writerow((*chosen["inspect"], chosen["threshold"], chosen["mm_per_pixel"], chosen["min_pixels"]))
    if report["rows"]:
        keys = [key for key in report["rows"][0] if key != "box"]
        writer.writerow(keys)
        writer.writerows([row.get(key) for key in keys] for row in report["rows"])
    return target.getvalue()


def dual_overlay(library, record, report):
    chosen = report["settings"]
    rgb_a, rgb_b, design, _, _, detect_a, detect_b = analysis.dual_layers(library, record, chosen)
    masks = analysis.dual_arbitration(design, detect_a, detect_b)
    marks = np.zeros(design.shape + (4,), dtype=np.uint8)
    marked = analysis.section(marks, chosen["inspect"])
    gap = analysis.section(masks["gap"], chosen["inspect"])
    pending = analysis.section(masks["pending"], chosen["inspect"])
    marked[gap] = (232, 97, 111, 182)
    marked[pending] = (245, 178, 74, 190)
    image = Image.alpha_composite(Image.fromarray(rgb_a).convert("RGBA"), Image.fromarray(marks))
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = chosen["inspect"]
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline="#65e5cb", width=2)
    return frame.encode(image.convert("RGB"))


def overlay(library, record, report):
    if report.get("dual_light"):
        return dual_overlay(library, record, report)
    chosen = report["settings"]
    rgb, design, _, transfer = analysis.layers(library, record, chosen)
    mode = report["mode"]
    marks = np.zeros(design.shape + (4,), dtype=np.uint8)
    marked = analysis.section(marks, chosen["inspect"])
    die = analysis.section(design, chosen["inspect"])
    detected = analysis.section(transfer, chosen["inspect"])
    if mode in ("coverage", "gaps"):
        marked[die & ~detected] = (232, 97, 111, 182)
    if mode == "leaks":
        marked[~die & detected] = (208, 137, 250, 210)
    image = Image.alpha_composite(Image.fromarray(rgb).convert("RGBA"), Image.fromarray(marks))
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = chosen["inspect"]
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline="#65e5cb", width=2)
    if mode == "profile":
        draw.line(chosen["line"], fill="#74e7cb", width=2)
    if mode == "references":
        for key in ("gold", "paper"):
            draw.rectangle(chosen[key], outline="#fadc88", width=2)
    for row in report["rows"]:
        if "box" in row:
            x0, y0, x1, y1 = row["box"]
            draw.rectangle((x0 - 2, y0 - 2, x1 + 1, y1 + 1), outline="#ffd5dc", width=1)
    return frame.encode(image.convert("RGB"))
