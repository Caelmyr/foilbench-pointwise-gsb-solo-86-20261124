"""Single-light transfer checks and the symmetric two-light coverage review."""

import numpy as np
from scipy import ndimage

from . import frame, model

# A disagreement component is only kept as foil when it continues the confirmed
# foil along a real edge: one accidental touch from a speck inside a gap is not
# enough, but a thin line joining confirmed foil on both sides always is.
RESCUE_CONTACTS = 2

TRANSFERRED = "已转移"
MISSING = "缺箔"
REVIEW = "待复看"


def section(array, rect):
    x0, y0, x1, y1 = rect
    return array[y0:y1, x0:x1]


def layers(library, record, settings):
    rgb = frame.pixels(library, record, settings["light"])
    design = frame.stencil(library, record)
    score = frame.foil_score(rgb)
    return rgb, design, score, score >= settings["threshold"]


def dual_layers(library, record, settings):
    design = frame.stencil(library, record)
    rgb_a = frame.pixels(library, record, "a")
    rgb_b = frame.pixels(library, record, "b")
    detect_a = frame.foil_score(rgb_a) >= settings["threshold"]
    detect_b = frame.foil_score(rgb_b) >= settings["threshold"]
    return rgb_a, rgb_b, design, frame.foil_score(rgb_a), frame.foil_score(rgb_b), detect_a, detect_b


def dual_arbitration(design, detect_a, detect_b):
    """Combine two directional lights into transfer / gap / review masks.

    The combination only uses set operations and four-neighbour connectivity,
    so swapping the two lights produces exactly the same verdict.
    """
    confirmed = design & detect_a & detect_b
    disagreement = detect_a ^ detect_b
    labels, count = ndimage.label(disagreement)
    touching = ndimage.binary_dilation(confirmed, iterations=1) & disagreement
    populations = np.bincount(labels[touching].ravel())
    keep = np.flatnonzero(populations >= RESCUE_CONTACTS)
    rescued = np.isin(labels, keep) & disagreement & design
    # Review only enters the die-based coverage account; disagreement on the
    # paper margin is surfaced by point readings but never counted as foil.
    pending = disagreement & design & ~rescued
    transfer = confirmed | rescued
    gap = design & ~transfer & ~pending
    return {
        "detect_a": detect_a, "detect_b": detect_b, "confirmed": confirmed,
        "disagreement": disagreement, "rescued": rescued, "pending": pending,
        "transfer": transfer, "gap": gap,
    }


def dual_coverage(masks, settings):
    expected = section(masks["transfer"] | masks["gap"] | masks["pending"], settings["inspect"])
    transfer = section(masks["transfer"], settings["inspect"])
    gap = section(masks["gap"], settings["inspect"])
    pending = section(masks["pending"], settings["inspect"])
    detect_a = section(masks["detect_a"], settings["inspect"])
    detect_b = section(masks["detect_b"], settings["inspect"])
    total = int(expected.sum())
    present = int(transfer.sum())
    review_px = int(pending.sum())
    decidable = present + int(gap.sum())
    return [{
        "expected_px": total,
        "transfer_px": present,
        "gap_px": int(gap.sum()),
        "review_px": review_px,
        "coverage_pct": round(100 * present / decidable, 2) if decidable else None,
        "expected_mm2": square_area(total, settings),
        "gap_mm2": square_area(int(gap.sum()), settings),
        "review_mm2": square_area(review_px, settings),
        "light_a_px": int(detect_a.sum()),
        "light_b_px": int(detect_b.sum()),
    }]


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
        return TRANSFERRED if marked else MISSING
    return "越界" if marked else "留白"


def dual_classification(design_yx, transfer_yx, pending_yx, disagreement_yx):
    if pending_yx or (not design_yx and disagreement_yx):
        return REVIEW
    if design_yx:
        return TRANSFERRED if transfer_yx else MISSING
    return "越界"


def point_reading(library, record, settings, point):
    x, y = point
    rgb, design, score, transfer = layers(library, record, settings)
    expected, marked = bool(design[y, x]), bool(transfer[y, x])
    return {"x": x, "y": y, "rgb": [int(c) for c in rgb[y, x]],
            "score": float(score[y, x]), "light": settings["light"],
            "expected": expected, "foil": marked, "classification": classification(expected, marked)}


def dual_point_reading(library, record, settings, point):
    x, y = point
    rgb_a, rgb_b, design, score_a, score_b, detect_a, detect_b = dual_layers(library, record, settings)
    masks = dual_arbitration(design, detect_a, detect_b)
    expected = bool(design[y, x])
    verdict = dual_classification(expected, bool(masks["transfer"][y, x]),
                                  bool(masks["pending"][y, x]),
                                  bool(masks["disagreement"][y, x]))
    return {
        "x": x, "y": y, "dual_light": True, "expected": expected,
        "verdict": verdict, "rescued": bool(masks["rescued"][y, x]),
        "lights": [
            {"light": "a", "rgb": [int(c) for c in rgb_a[y, x]],
             "score": round(float(score_a[y, x]), 2), "foil": bool(detect_a[y, x])},
            {"light": "b", "rgb": [int(c) for c in rgb_b[y, x]],
             "score": round(float(score_b[y, x]), 2), "foil": bool(detect_b[y, x])},
        ],
    }


def has_two_lights(record):
    return all(role in record["sources"] for role in ("a", "b"))


def report(library, record, settings, mode):
    if mode == "coverage" and has_two_lights(record):
        rgb_a, rgb_b, design, _, _, detect_a, detect_b = dual_layers(library, record, settings)
        masks = dual_arbitration(design, detect_a, detect_b)
        rows = dual_coverage(masks, settings)
        meta = {
            "dual_light": True,
            "agreed_present_px": int(section(masks["confirmed"], settings["inspect"]).sum()),
            "rescued_px": int(section(masks["rescued"], settings["inspect"]).sum()),
            "pending_px": int(section(masks["pending"], settings["inspect"]).sum()),
            "disagreement_px": int(section(masks["disagreement"], settings["inspect"]).sum()),
        }
        return {"mode": mode, "heading": model.MODES[mode], "settings": settings,
                "rows": rows, "meta": meta, "dual_light": True}
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
