"""Place one unfoiled sticker stripe inside the inspection window and check its clearance."""

import numpy as np
from scipy import ndimage

from . import analysis

DEFAULT_WIDTH_MM = 2.0
DEFAULT_CLEARANCE_MM = 1.0
SIDES = ("左", "右", "上", "下")


def parameters(settings):
    """Return the window, sticker width, clearance, and any adopted left edge."""
    label = settings.get("label") or {}
    return settings["inspect"], *measures(label, settings["mm_per_pixel"]), label.get("x")


def measures(label, scale):
    """Convert the sticker width and minimum clearance from millimetres to pixels."""
    width_mm = float(label.get("width_mm", DEFAULT_WIDTH_MM))
    clearance_mm = float(label.get("clearance_mm", DEFAULT_CLEARANCE_MM))
    return max(1, int(round(width_mm / scale))), max(0, int(round(clearance_mm / scale)))


def foil_mask(design, transfer):
    """Everything the sticker must clear: printed foil and foil detected in the photograph."""
    return design | transfer


def field(design, transfer):
    """Distance to the nearest foil pixel and the source coordinate of that pixel."""
    foil = foil_mask(design, transfer)
    return ndimage.distance_transform_edt(~foil, return_indices=True)


def band_rect(box, clearance, width, height):
    x0, y0, x1, y1 = box
    return [max(0, x0 - clearance), max(0, y0 - clearance),
            min(width, x1 + clearance), min(height, y1 + clearance)]


def masks(design, transfer, settings, box):
    """Return the sticker stripe and the safety ring around it, clipped to the photograph."""
    y0, y1 = box[1], box[3]
    height, width = design.shape
    _, stripe, clearance, _ = parameters(settings)
    band_box = [box[0], y0, box[0] + stripe, y1]
    label = np.zeros_like(design)
    label[band_box[1]:band_box[3], band_box[0]:band_box[2]] = True
    bx0, by0, bx1, by1 = band_rect(band_box, clearance, width, height)
    band = np.zeros_like(design)
    band[by0:by1, bx0:bx1] = True
    return band_box, label, band & ~label


def nearest(field_map, box):
    """Reading for the closest foil pixel anywhere in the photograph, including outside the window."""
    distance, (rows, columns) = field_map
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return None
    values = distance[y0:y1, x0:x1]
    flat = int(np.argmin(values))
    local_y, local_x = divmod(flat, x1 - x0)
    y, x = y0 + local_y, x0 + local_x
    return {"pixels": float(values[local_y, local_x]),
            "x": int(columns[y, x]), "y": int(rows[y, x])}


def unviewable(box, clearance, shape, scale):
    """Report the parts of the safety ring that fall outside the photograph."""
    x0, y0, x1, y1 = box
    height, width = shape
    full = (x1 - x0 + 2 * clearance) * (y1 - y0 + 2 * clearance)
    clipped = band_rect(box, clearance, width, height)
    seen = max(0, clipped[2] - clipped[0]) * max(0, clipped[3] - clipped[1])
    depths = {
        "左": min(clearance, x0), "右": min(clearance, width - x1),
        "上": min(clearance, y0), "下": min(clearance, height - y1),
    }
    ranges = [{"side": side, "from_mm": round(depths[side] * scale, 4),
               "to_mm": round(clearance * scale, 4),
               "width_mm": round((clearance - depths[side]) * scale, 4)}
              for side in SIDES if depths[side] < clearance]
    covered = 100 * (full - seen) / full if full else 0.0
    return {"ranges": ranges, "area_mm2": round((full - seen) * scale ** 2, 4),
            "pct": round(covered, 2)}


def stripe(design, transfer, settings):
    """Choose at most one stripe: fully inside the window, on blank stock, clear of foil."""
    field_map = field(design, transfer)
    distance = field_map[0]
    x0, y0, x1, y1 = settings["inspect"]
    _, width, clearance, adopted = parameters(settings)
    scale = settings["mm_per_pixel"]
    band = unviewable([x0, y0, x1, y1], clearance, design.shape, scale)
    if width > x1 - x0:
        return {"label": None, "reason": "贴位宽度超过检查窗宽度，请缩窄贴位或重画检查窗。",
                "unviewable": band, "candidates": 0}

    blank = ~design[y0:y1, x0:x1].any(axis=0)
    columns = distance[y0:y1, x0:x1].min(axis=0)
    feasible = [x0 + offset for offset in range(x1 - x0 - width + 1)
                if blank[offset:offset + width].all()
                and columns[offset:offset + width].min() >= clearance
                and not unviewable([x0 + offset, y0, x0 + offset + width, y1],
                                   clearance, design.shape, scale)["ranges"]]

    stored = None
    if isinstance(adopted, int) and not isinstance(adopted, bool):
        # An adopted stripe is a physical position: keep it even if the photograph now shows foil there.
        if x0 <= adopted and adopted + width <= x1:
            stored = adopted
    left = stored
    alternative = None
    if left is None and feasible:
        middle = (x0 + x1) / 2
        span = lambda candidate: columns[candidate - x0:candidate - x0 + width].min()
        left = min(feasible, key=lambda candidate: (
            abs(candidate + width / 2 - middle), -span(candidate), candidate))
        roomier = max(feasible, key=lambda candidate: (span(candidate), -abs(candidate + width / 2 - middle)))
        if roomier != left and span(roomier) > span(left):
            alternative = {"x0": roomier, "x1": roomier + width,
                           "clearance_px": span(roomier)}
    if left is None:
        return {"label": None, "reason": "检查窗内没有放得下这条贴位、又留足净距的版图留白。",
                "unviewable": band, "candidates": len(feasible)}

    box = [left, y0, left + width, y1]
    spot = nearest(field_map, box)
    middle = (x0 + x1) / 2
    offset = (left + width / 2 - middle) * scale
    required = float(settings["label"].get("clearance_mm", DEFAULT_CLEARANCE_MM))
    if alternative:
        alternative["clearance_mm"] = round(alternative.pop("clearance_px") * scale, 4)
    return {
        "label": {
            "box": box, "x0": left, "x1": left + width, "y0": y0, "y1": y1,
            "width_mm": round(width * scale, 4),
            "requested_mm": round(required, 4),
            "clearance_mm": round(spot["pixels"] * scale, 4),
            "meets": spot["pixels"] * scale >= required - 1e-9,
            "offset_mm": round(abs(offset), 4),
            "offset_side": "居中" if round(offset, 4) == 0 else ("偏右" if offset > 0 else "偏左"),
            "nearest_x": spot["x"], "nearest_y": spot["y"],
            "nearest_inside": bool(x0 <= spot["x"] < x1 and y0 <= spot["y"] < y1),
            "x": left + width // 2, "y": (y0 + y1) // 2,
            "adopted": stored is not None, "suggested": stored is None,
            "alternative": alternative,
        },
        "unviewable": unviewable(box, clearance, design.shape, scale),
        "candidates": len(feasible),
    }


def components(mask, region, design, settings, kind):
    """Largest connected patches of one class, with source coordinates for point inspection."""
    x0, y0, _, _ = region
    x1, y1 = region[2], region[3]
    labels, count = ndimage.label(mask[y0:y1, x0:x1])
    if not count:
        return [], 0
    populations = np.bincount(labels.ravel())
    keep = np.flatnonzero(populations[1:] >= settings["min_pixels"]) + 1
    ranked = sorted(keep, key=lambda index: (-int(populations[index]), int(index)))
    objects = ndimage.find_objects(labels)
    rows = []
    for order, index in enumerate(ranked, start=1):
        yy, xx = objects[index - 1]
        local = labels[yy, xx] == index
        first = np.flatnonzero(local)[0]
        dy, dx = divmod(int(first), local.shape[1])
        pixels = int(populations[index])
        patch = labels[yy, xx] == index
        rows.append({
            "kind": kind, "index": order, "pixels": pixels,
            "area_mm2": analysis.square_area(pixels, settings),
            "width_mm": round((xx.stop - xx.start) * settings["mm_per_pixel"], 4),
            "height_mm": round((yy.stop - yy.start) * settings["mm_per_pixel"], 4),
            "expected": bool(design[y0 + yy.start:y0 + yy.stop,
                                    x0 + xx.start:x0 + xx.stop][patch].any()),
            "x": x0 + xx.start + dx, "y": y0 + yy.start + dy,
            "box": [x0 + xx.start, y0 + yy.start, x0 + xx.stop, y0 + yy.stop],
        })
    return rows, len(ranked)


def leaks(design, transfer, settings):
    """Classify detected foil inside the sticker stripe separately from its safety ring."""
    located = stripe(design, transfer, settings)
    meta = {key: located[key] for key in ("reason", "unviewable", "candidates") if key in located}
    meta["label"] = located["label"]
    if located["label"] is None:
        meta["component_count"] = 0
        return [], meta
    _, label, ring = masks(design, transfer, settings, located["label"]["box"])
    height, width = design.shape
    band = band_rect(located["label"]["box"], parameters(settings)[2], width, height)
    window = tuple(settings["inspect"])
    leaks_mask = transfer & ~design
    inside, inside_total = components(leaks_mask & label, located["label"]["box"], design,
                                      settings, "贴位")
    around, around_total = components(leaks_mask & ring, tuple(band), design, settings, "安全边")
    elsewhere, elsewhere_total = components(leaks_mask & ~label & ~ring, window, design,
                                            settings, "窗内其他")
    rows = sorted(inside + around + elsewhere, key=lambda row: (-row["pixels"], row["x"], row["y"]))
    for order, row in enumerate(rows, start=1):
        row["index"] = order
    meta["component_count"] = inside_total + around_total + elsewhere_total
    meta["label_foil_px"] = int((leaks_mask & label).sum())
    meta["ring_foil_px"] = int((leaks_mask & ring).sum())
    return rows, meta
