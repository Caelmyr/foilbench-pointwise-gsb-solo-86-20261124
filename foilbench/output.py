"""Export tabular findings and a marked view of the capture used for a report."""

import csv
from io import StringIO

import numpy as np
from PIL import Image, ImageDraw

from . import analysis, frame, placement


def csv_text(report):
    target = StringIO(newline="")
    writer = csv.writer(target)
    writer.writerow(("mode", report["mode"], "light", report["settings"]["light"]))
    writer.writerow(("x0", "y0", "x1", "y1", "threshold", "mm_per_pixel", "min_pixels"))
    chosen = report["settings"]
    writer.writerow((*chosen["inspect"], chosen["threshold"], chosen["mm_per_pixel"], chosen["min_pixels"]))
    label = chosen.get("label")
    located = report["meta"].get("label")
    if label and located:
        writer.writerow(("label_width_mm", "label_clearance_mm", "label_actual_mm",
                         "label_x0", "label_x1", "label_offset_mm"))
        writer.writerow((label["width_mm"], label["clearance_mm"], located["clearance_mm"],
                         located["x0"], located["x1"], located["offset_mm"]))
        writer.writerow(("label_foil_px", report["meta"].get("label_foil_px"),
                         "ring_foil_px", report["meta"].get("ring_foil_px")))
        ranges = (report["meta"].get("unviewable") or {}).get("ranges") or []
        if ranges:
            writer.writerow(("unviewable_side", "width_mm"))
            writer.writerows((item["side"], item["width_mm"]) for item in ranges)
    if report["rows"]:
        keys = [key for key in report["rows"][0] if key != "box"]
        writer.writerow(keys)
        writer.writerows([row.get(key) for key in keys] for row in report["rows"])
    return target.getvalue()


def _clip_marks(draw, size, located, unviewable):
    """Mark photograph edges where the safety ring runs past the frame."""
    if not unviewable or not unviewable.get("ranges"):
        return
    width, height = size
    sides = {item["side"] for item in unviewable["ranges"]}
    x0, y0, x1, y1 = located["x0"], located["y0"], located["x1"], located["y1"]
    if "左" in sides:
        draw.line((0, y0, 0, y1 - 1), fill="#ff9fa8", width=3)
    if "右" in sides:
        draw.line((width - 1, y0, width - 1, y1 - 1), fill="#ff9fa8", width=3)
    if "上" in sides:
        draw.line((x0, 0, x1 - 1, 0), fill="#ff9fa8", width=3)
    if "下" in sides:
        draw.line((x0, height - 1, x1 - 1, height - 1), fill="#ff9fa8", width=3)


def overlay(library, record, report):
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
        slate = analysis.section(marks, chosen["inspect"])
        outside = analysis.section(transfer & ~design, chosen["inspect"])
        if report["meta"].get("label"):
            _, stripe, ring = placement.masks(design, transfer, chosen, report["meta"]["label"]["box"])
            stripe = analysis.section(stripe, chosen["inspect"])
            ring = analysis.section(ring, chosen["inspect"])
            slate[outside & stripe] = (208, 137, 250, 215)
            slate[outside & ring] = (95, 190, 235, 205)
            slate[outside & ~stripe & ~ring] = (208, 137, 250, 120)
        else:
            slate[outside] = (208, 137, 250, 210)
    image = Image.alpha_composite(Image.fromarray(rgb).convert("RGBA"), Image.fromarray(marks))
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = chosen["inspect"]
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline="#65e5cb", width=2)
    located = report["meta"].get("label") if mode == "leaks" else None
    if located:
        draw.rectangle((located["x0"], located["y0"], located["x1"] - 1, located["y1"] - 1),
                       outline="#f4f1e8", width=2)
        _clip_marks(draw, image.size, located, report["meta"].get("unviewable"))
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
