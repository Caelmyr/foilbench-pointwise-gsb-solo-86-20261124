"""Validate FoilBench source geometry, current controls, and report mode."""

import math

from image_lab.validation import Invalid

MAX_UPLOAD = 14 * 1024 * 1024
MAX_PIXELS = 4_000_000
SHIFT_LIMIT = 10
LIGHTS = {"a": "灯 A", "b": "灯 B"}
MODES = {
    "coverage": "转移覆盖",
    "gaps": "连续缺箔",
    "leaks": "留白越界",
    "profile": "像素剖线",
    "references": "箔色参照",
    "distribution": "箔色分布",
}
TOOLS = {
    "inspect": "检查窗",
    "gold": "已转移箔色参照",
    "paper": "留白纸色参照",
    "line": "箔色剖线",
}


def document(value):
    if not isinstance(value, dict):
        raise Invalid("请提供一组检查设置。")
    return value


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise Invalid("名称应有 1 至 160 个字符。")
    return value.strip()


def number(value, name, lower, upper):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Invalid(f"{name}应是数字。")
    if not math.isfinite(value) or not lower <= value <= upper:
        raise Invalid(f"{name}须在 {lower} 至 {upper} 之间。")
    return value


def positions(value, size, rectangle):
    bounds = *size, *size
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise Invalid("请在图上选择两个点。")
    points = []
    for coordinate, bound in zip(value, bounds):
        if not isinstance(coordinate, int) or isinstance(coordinate, bool):
            raise Invalid("图像坐标应为整像素。")
        if coordinate < 0 or coordinate >= bound + int(rectangle):
            raise Invalid("选点超出源图范围。")
        points.append(coordinate)
    x0, y0, x1, y1 = points
    if rectangle and (x0 >= x1 or y0 >= y1):
        raise Invalid("检查框必须有正宽和正高。")
    return points


def shift(value):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise Invalid("平移套准应包含横向和纵向两个像素值。")
    chosen = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, int):
            raise Invalid("平移套准应为整像素。")
        if abs(component) > SHIFT_LIMIT:
            raise Invalid(f"平移套准横竖各须在 {SHIFT_LIMIT} 像素内。")
        chosen.append(component)
    return chosen


def defaults(width, height):
    return {
        "light": "a", "threshold": 44, "mm_per_pixel": 0.1, "min_pixels": 6,
        "shift": [0, 0],
        "inspect": [0, 0, width, height],
        "gold": [width // 4, height // 4, width // 2, height // 2],
        "paper": [0, 0, max(width // 8, 1), max(height // 8, 1)],
        "line": [0, height // 2, width - 1, height // 2],
    }


def settings(value, panel):
    value = document(value)
    base = panel["settings"]
    size = panel["width"], panel["height"]
    chosen = {key: positions(value.get(key, base[key]), size, key != "line") for key in TOOLS}
    light = value.get("light", base["light"])
    if not isinstance(light, str) or light not in LIGHTS or light not in panel["sources"]:
        raise Invalid("这份印样尚未导入该方向的照片。")
    chosen.update(
        light=light,
        threshold=number(value.get("threshold", base["threshold"]), "箔色门槛", -255, 255),
        mm_per_pixel=number(value.get("mm_per_pixel", base["mm_per_pixel"]), "毫米每像素", 0.001, 100),
        min_pixels=int(number(value.get("min_pixels", base["min_pixels"]), "最小斑块像素数", 1, MAX_PIXELS)),
        shift=shift(value.get("shift", base.get("shift", [0, 0]))),
    )
    return chosen


def mode(value):
    if not isinstance(value, str) or value not in MODES:
        raise Invalid("请选择一个检查项目。")
    return value


def point(value, panel):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise Invalid("请在图面上取样。")
    x, y, _, _ = positions((*value, *value), (panel["width"], panel["height"]), False)
    return x, y
