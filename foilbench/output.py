"""Export tabular findings and a marked view of the capture used for a report."""

import csv
from io import StringIO

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from . import analysis, frame


def csv_text(report):
    target = StringIO(newline="")
    writer = csv.writer(target)
    writer.writerow(("mode", report["mode"], "light", report["settings"]["light"]))
    writer.writerow(("x0", "y0", "x1", "y1", "threshold", "mm_per_pixel", "min_pixels",
                     "shift_x", "shift_y"))
    chosen = report["settings"]
    shift_x, shift_y = chosen.get("shift", (0, 0))
    writer.writerow((*chosen["inspect"], chosen["threshold"], chosen["mm_per_pixel"],
                     chosen["min_pixels"], shift_x, shift_y))
    if report["rows"]:
        keys = [key for key in report["rows"][0] if key != "box"]
        writer.writerow(keys)
        writer.writerows([row.get(key) for key in keys] for row in report["rows"])
    return target.getvalue()


def overlay(library, record, report):
    chosen = report["settings"]
    rgb, design, _, transfer, captured = analysis.layers(library, record, chosen)
    mode = report["mode"]
    marks = np.zeros(design.shape + (4,), dtype=np.uint8)
    marked = analysis.section(marks, chosen["inspect"])
    in_frame = analysis.section(captured, chosen["inspect"])
    die = analysis.section(design, chosen["inspect"]) & in_frame
    detected = analysis.section(transfer, chosen["inspect"])
    if any(analysis.adopted_shift(chosen)):
        marked[~in_frame] = (104, 138, 160, 88)
    if mode in ("coverage", "gaps"):
        marked[die & ~detected] = (232, 97, 111, 182)
    if mode == "leaks":
        marked[~die & detected & in_frame] = (208, 137, 250, 210)
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


def registration_preview(library, record, settings, shift):
    """Render the photo with the proposed stencil translation and out-of-frame edges."""
    rgb = frame.pixels(library, record, settings["light"])
    design = frame.stencil(library, record)
    dx, dy = shift
    aligned = analysis.shifted(design, dx, dy)
    captured = analysis.shifted(np.ones(design.shape, dtype=bool), dx, dy)
    coarse = ndimage.binary_opening(aligned, structure=np.ones((3, 3)))
    fine = aligned & ~coarse
    main_edge = coarse & ~ndimage.binary_erosion(coarse)
    fine_edge = fine & ~ndimage.binary_erosion(fine)
    marks = np.zeros(design.shape + (4,), dtype=np.uint8)
    marks[~captured] = (104, 138, 160, 88)
    marks[main_edge] = (101, 229, 203, 235)
    marks[fine_edge] = (250, 220, 136, 235)
    image = Image.alpha_composite(Image.fromarray(rgb).convert("RGBA"), Image.fromarray(marks))
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = settings["inspect"]
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline="#65e5cb", width=2)
    return frame.encode(image.convert("RGB"))
