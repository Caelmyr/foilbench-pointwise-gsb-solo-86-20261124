"""Measure single-light transfer, gaps, overprint, and source-image readings."""

import numpy as np
from scipy import ndimage

from image_lab.validation import Invalid

from . import frame, model


def section(array, rect):
    x0, y0, x1, y1 = rect
    return array[y0:y1, x0:x1]


def adopted_shift(settings):
    dx, dy = settings.get("shift") or (0, 0)
    return int(dx), int(dy)


def shifted(mask, dx, dy):
    """Translate a boolean mask by (dx, dy); pixels arriving from outside read False."""
    if not dx and not dy:
        return mask
    height, width = mask.shape
    out = np.zeros_like(mask)
    xs = slice(max(0, -dx), min(width, width - dx))
    ys = slice(max(0, -dy), min(height, height - dy))
    out[ys.start + dy:ys.stop + dy, xs.start + dx:xs.stop + dx] = mask[ys, xs]
    return out


def layers(library, record, settings):
    rgb = frame.pixels(library, record, settings["light"])
    design = frame.stencil(library, record)
    score = frame.foil_score(rgb)
    transfer = score >= settings["threshold"]
    dx, dy = adopted_shift(settings)
    if dx or dy:
        design = shifted(design, dx, dy)
        captured = shifted(np.ones(design.shape, dtype=bool), dx, dy)
    else:
        captured = np.ones(design.shape, dtype=bool)
    return rgb, design, score, transfer, captured


def square_area(pixels, settings):
    return round(pixels * settings["mm_per_pixel"] ** 2, 4)


def coverage(design, captured, transfer, settings):
    in_frame = section(captured, settings["inspect"])
    expected = section(design, settings["inspect"]) & in_frame
    foil = section(transfer, settings["inspect"])
    total = int(expected.sum())
    present = int((expected & foil).sum())
    row = {
        "expected_px": total,
        "transfer_px": present,
        "gap_px": total - present,
        "coverage_pct": round(100 * present / total, 2) if total else None,
        "expected_mm2": square_area(total, settings),
        "gap_mm2": square_area(total - present, settings),
    }
    if any(adopted_shift(settings)):
        outside = int((~in_frame).sum())
        row["out_of_frame_px"] = outside
        row["out_of_frame_mm2"] = square_area(outside, settings)
    return [row]


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


def profile(score, design, transfer, settings, captured):
    x0, y0, x1, y1 = settings["line"]
    distance = float(np.hypot(x1 - x0, y1 - y0))
    n = min(max(abs(x1 - x0), abs(y1 - y0)) + 1, 1000)
    xs = np.rint(np.linspace(x0, x1, n)).astype(int)
    ys = np.rint(np.linspace(y0, y1, n)).astype(int)
    distances = np.linspace(0, distance * settings["mm_per_pixel"], n)
    aligned = any(adopted_shift(settings))
    rows = []
    for x, y, length in zip(xs, ys, distances):
        row = {
            "x": int(x), "y": int(y), "distance_mm": round(float(length), 4),
            "score": float(score[y, x]), "expected": bool(design[y, x]),
            "foil": bool(transfer[y, x]),
        }
        if aligned:
            row["captured"] = bool(captured[y, x])
        rows.append(row)
    return rows


def reference(score, transfer, settings, key):
    values = section(score, settings[key])
    p10, median, p90 = np.percentile(values, [10, 50, 90])
    return {
        "reference": model.TOOLS[key], "pixels": int(values.size),
        "low_score": round(float(p10), 2), "median_score": round(float(median), 2),
        "high_score": round(float(p90), 2),
        "foil_pct": round(float(section(transfer, settings[key]).mean()) * 100, 2),
    }


def distribution(score, design, captured, settings):
    values = section(score, settings["inspect"])
    in_frame = section(captured, settings["inspect"])
    expected = section(design, settings["inspect"]) & in_frame
    bands = [-255, -25, 0, 20, 40, 60, 80, 110, 150, 255]
    target, _ = np.histogram(values[expected], bins=bands)
    paper, _ = np.histogram(values[in_frame & ~expected], bins=bands)
    return [{"lower": lo, "upper": hi, "die_px": int(die), "paper_px": int(stock)}
            for lo, hi, die, stock in zip(bands, bands[1:], target, paper)]


def classification(expected, marked):
    if expected:
        return "已转移" if marked else "缺箔"
    return "越界" if marked else "留白"


def point_reading(library, record, settings, point):
    x, y = point
    rgb, design, score, transfer, captured = layers(library, record, settings)
    in_frame = bool(captured[y, x])
    expected = bool(design[y, x]) if in_frame else None
    marked = bool(transfer[y, x])
    reading = {
        "x": x, "y": y, "rgb": [int(c) for c in rgb[y, x]],
        "score": float(score[y, x]), "light": settings["light"], "captured": in_frame,
        "expected": expected, "foil": marked,
        "classification": classification(expected, marked) if in_frame else "画面外",
    }
    dx, dy = adopted_shift(settings)
    if dx or dy:
        reading["plate_x"] = x - dx if in_frame else None
        reading["plate_y"] = y - dy if in_frame else None
    return reading


def report(library, record, settings, mode):
    _, design, score, transfer, captured = layers(library, record, settings)
    meta = {}
    if mode == "coverage":
        rows = coverage(design, captured, transfer, settings)
    elif mode == "gaps":
        rows, meta["component_count"] = components(design & captured & ~transfer, settings)
    elif mode == "leaks":
        rows, meta["component_count"] = components(transfer & captured & ~design, settings)
    elif mode == "profile":
        rows = profile(score, design, transfer, settings, captured)
    elif mode == "references":
        rows = [reference(score, transfer, settings, key) for key in ("gold", "paper")]
    else:
        rows = distribution(score, design, captured, settings)
    return {"mode": mode, "heading": model.MODES[mode], "settings": settings, "rows": rows, "meta": meta}


def suggest_registration(library, record, settings, limit=model.SHIFT_LIMIT):
    """Find the translation that best aligns the stencil with the viewed photograph.

    Solid blocks and fine strokes are scored in their own neighbourhoods and
    weighted equally, so wide foil areas cannot outvote small details.
    """
    design = frame.stencil(library, record)
    rgb = frame.pixels(library, record, settings["light"])
    transfer = frame.foil_score(rgb) >= settings["threshold"]
    x0, y0, x1, y1 = settings["inspect"]
    height, width = design.shape
    coarse = ndimage.binary_opening(design, structure=np.ones((3, 3)))
    fine = design & ~coarse
    fine_zone = ndimage.binary_dilation(fine, iterations=3)
    coarse_zone = ndimage.binary_dilation(coarse, iterations=6) & ~fine_zone
    ey0, ey1 = max(0, y0 - limit), min(height, y1 + limit)
    ex0, ex1 = max(0, x0 - limit), min(width, x1 + limit)
    stencil = design[ey0:ey1, ex0:ex1]
    zones = (coarse_zone[ey0:ey1, ex0:ex1], fine_zone[ey0:ey1, ex0:ex1])
    target = transfer[y0:y1, x0:x1]
    grid = {}
    for dy in range(-limit, limit + 1):
        for dx in range(-limit, limit + 1):
            sy0, sy1 = y0 - ey0 - dy, y1 - ey0 - dy
            sx0, sx1 = x0 - ex0 - dx, x1 - ex0 - dx
            cy0, cy1 = max(0, sy0), min(stencil.shape[0], sy1)
            cx0, cx1 = max(0, sx0), min(stencil.shape[1], sx1)
            if cy1 <= cy0 or cx1 <= cx0:
                continue
            source = np.s_[cy0:cy1, cx0:cx1]
            window = target[cy0 - sy0:cy1 - sy0, cx0 - sx0:cx1 - sx0]
            mismatch = stencil[source] != window
            entry = []
            for zone in zones:
                local = zone[source]
                entry += [int((mismatch & local).sum()), int(local.sum())]
            grid[(dx, dy)] = entry

    def rate(entry, component):
        error, base = entry[component * 2:component * 2 + 2]
        return error / base if base else None

    def best(component):
        chosen = None
        for (dx, dy), entry in grid.items():
            value = rate(entry, component)
            if value is None:
                continue
            key = (value, abs(dx) + abs(dy), dx, dy)
            if chosen is None or key < chosen[0]:
                chosen = key, (dx, dy)
        return chosen

    coarse_best, fine_best = best(0), best(1)
    if coarse_best is None and fine_best is None:
        raise Invalid("检查窗内没有足够的版图细节，无法估计平移。")
    choice = None
    for (dx, dy), entry in grid.items():
        present = [value for value in (rate(entry, 0), rate(entry, 1)) if value is not None]
        if not present:
            continue
        key = (sum(present) / len(present), abs(dx) + abs(dy), dx, dy)
        if choice is None or key < choice[0]:
            choice = key, (dx, dy)
    dx, dy = choice[1]

    def describe(component, peak):
        if peak is None:
            return None
        error, base = grid[(dx, dy)][component * 2:component * 2 + 2]
        return {
            "mismatch_px": error, "territory_px": base,
            "mismatch_pct": round(100 * error / base, 2) if base else None,
            "best_shift": list(peak[1]), "best_pct": round(100 * peak[0][0], 2),
        }

    main, detail = describe(0, coarse_best), describe(1, fine_best)
    return {
        "shift": [dx, dy], "light": settings["light"], "limit": limit,
        "main": main, "fine": detail,
        "agree": main is None or detail is None or main["best_shift"] == detail["best_shift"],
    }
