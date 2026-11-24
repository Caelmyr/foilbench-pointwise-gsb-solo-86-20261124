"""Measure single-light transfer, gaps, overprint, and source-image readings."""

import numpy as np
from scipy import ndimage

from . import frame, model


def section(array, rect):
    x0, y0, x1, y1 = rect
    return array[y0:y1, x0:x1]


def layers(library, record, settings):
    rgb = frame.pixels(library, record, settings["light"])
    design = frame.stencil(library, record)
    score = frame.foil_score(rgb)
    return rgb, design, score, score >= settings["threshold"]


def square_area(pixels, settings):
    return round(pixels * settings["mm_per_pixel"] ** 2, 4)


def coverage(design, transfer, settings):
    expected = section(design, settings["inspect"])
    foil = section(transfer, settings["inspect"])
    total = int(expected.sum())
    present = int((expected & foil).sum())
    return [{
        "expected_px": total,
        "transfer_px": present,
        "gap_px": total - present,
        "coverage_pct": round(100 * present / total, 2) if total else None,
        "expected_mm2": square_area(total, settings),
        "gap_mm2": square_area(total - present, settings),
    }]


def components(mask, settings):
    x0, y0, _, _ = settings["inspect"]
    labels, count = ndimage.label(section(mask, settings["inspect"]))
    if not count:
        return [], 0
    populations = np.bincount(labels.ravel())
    keep = np.flatnonzero(populations[1:] >= settings["min_pixels"]) + 1
    ranked = sorted(keep, key=lambda idx: (-int(populations[idx]), int(idx)))
    slices = ndimage.find_objects(labels)
    rows = []
    for order, index in enumerate(ranked[:120], start=1):
        yy, xx = slices[index - 1]
        local = labels[yy, xx] == index
        match = np.flatnonzero(local)[0]
        dy, dx = divmod(int(match), local.shape[1])
        pixels = int(populations[index])
        rows.append({
            "index": order, "pixels": pixels, "area_mm2": square_area(pixels, settings),
            "width_mm": round((xx.stop - xx.start) * settings["mm_per_pixel"], 4),
            "height_mm": round((yy.stop - yy.start) * settings["mm_per_pixel"], 4),
            "x": x0 + xx.start + dx, "y": y0 + yy.start + dy,
            "box": [x0 + xx.start, y0 + yy.start, x0 + xx.stop, y0 + yy.stop],
        })
    return rows, len(ranked)


def profile(score, design, transfer, settings):
    x0, y0, x1, y1 = settings["line"]
    distance = float(np.hypot(x1 - x0, y1 - y0))
    n = min(max(abs(x1 - x0), abs(y1 - y0)) + 1, 1000)
    xs = np.rint(np.linspace(x0, x1, n)).astype(int)
    ys = np.rint(np.linspace(y0, y1, n)).astype(int)
    distances = np.linspace(0, distance * settings["mm_per_pixel"], n)
    return [{
        "x": int(x), "y": int(y), "distance_mm": round(float(length), 4),
        "score": float(score[y, x]), "expected": bool(design[y, x]),
        "foil": bool(transfer[y, x]),
    } for x, y, length in zip(xs, ys, distances)]


def reference(score, transfer, settings, key):
    values = section(score, settings[key])
    p10, median, p90 = np.percentile(values, [10, 50, 90])
    return {
        "reference": model.TOOLS[key], "pixels": int(values.size),
        "low_score": round(float(p10), 2), "median_score": round(float(median), 2),
        "high_score": round(float(p90), 2),
        "foil_pct": round(float(section(transfer, settings[key]).mean()) * 100, 2),
    }


def distribution(score, design, settings):
    values = section(score, settings["inspect"])
    expected = section(design, settings["inspect"])
    bands = [-255, -25, 0, 20, 40, 60, 80, 110, 150, 255]
    target, _ = np.histogram(values[expected], bins=bands)
    paper, _ = np.histogram(values[~expected], bins=bands)
    return [{"lower": lo, "upper": hi, "die_px": int(die), "paper_px": int(stock)}
            for lo, hi, die, stock in zip(bands, bands[1:], target, paper)]


def classification(expected, marked):
    if expected:
        return "已转移" if marked else "缺箔"
    return "越界" if marked else "留白"


def point_reading(library, record, settings, point):
    x, y = point
    rgb, design, score, transfer = layers(library, record, settings)
    expected, marked = bool(design[y, x]), bool(transfer[y, x])
    return {"x": x, "y": y, "rgb": [int(c) for c in rgb[y, x]],
            "score": float(score[y, x]), "light": settings["light"],
            "expected": expected, "foil": marked, "classification": classification(expected, marked)}


def report(library, record, settings, mode):
    _, design, score, transfer = layers(library, record, settings)
    meta = {}
    if mode == "coverage":
        rows = coverage(design, transfer, settings)
    elif mode == "gaps":
        rows, meta["component_count"] = components(design & ~transfer, settings)
    elif mode == "leaks":
        rows, meta["component_count"] = components(transfer & ~design, settings)
    elif mode == "profile":
        rows = profile(score, design, transfer, settings)
    elif mode == "references":
        rows = [reference(score, transfer, settings, key) for key in ("gold", "paper")]
    else:
        rows = distribution(score, design, settings)
    return {"mode": mode, "heading": model.MODES[mode], "settings": settings, "rows": rows, "meta": meta}
