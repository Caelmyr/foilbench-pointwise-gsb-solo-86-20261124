"""Render a labeled synthetic hot foil job with registered directional photographs."""

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .model import defaults


def die_art(size):
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((52, 48, 827, 430), radius=18, outline=255, width=4)
    draw.polygon([(111, 183), (179, 116), (247, 183), (179, 250)], outline=255, width=6)
    draw.ellipse((149, 153, 209, 213), fill=255)
    draw.rectangle((112, 343, 265, 366), fill=255)
    draw.rectangle((289, 343, 376, 366), fill=255)
    draw.rectangle((425, 343, 748, 366), fill=255)
    draw.text((294, 105), "MERIDIAN", font=ImageFont.load_default(72), fill=255)
    draw.text((300, 219), "TYPE  NO.  03", font=ImageFont.load_default(36), fill=255)
    for x in (30, 851):
        draw.line((x - 9, 27, x + 9, 27), fill=255, width=2)
        draw.line((x, 18, x, 36), fill=255, width=2)
    return mask.point(lambda v: 255 if v >= 128 else 0)


def reflectance(design, direction):
    height, width = design.shape
    y, x = np.indices((height, width))
    rng = np.random.default_rng(803)
    grain = rng.normal(0, 1.8, size=design.shape)
    paper = np.array([42, 50, 63]) + (grain + y / 90)[..., None]
    light = 14 * np.sin((x + direction * y * 1.7) / 64) + 5 * np.cos(y / 11)
    gold = np.array([198, 151, 64]) + (grain + light)[..., None]
    missing = ((x >= 591) & (x <= 611) & (y >= 332) & (y <= 372))
    missing |= ((x - 174) ** 2 + (y - 169) ** 2 < 29)
    stock = np.where((design & ~missing)[..., None], gold, paper)
    dim = (x > 342) & (x < 373) & (y > 341) & (y < 369) & design
    stock[dim] = [105, 92, 64] if direction == 1 else [178, 128, 61]
    warm_speck = (x - 599) ** 2 / 65 + (y - 353) ** 2 / 45 < 1
    if direction == 1:
        stock[warm_speck] = [213, 172, 75]
    spill = ((x - 528) ** 2 + (y - 388) ** 2 < 28)
    stock[spill] = gold[spill]
    reflective_glint = ((x - 211) ** 2 + (y - 281) ** 2 < 26)
    if direction == -1:
        stock[reflective_glint] = [204, 171, 78]
    return Image.fromarray(np.uint8(np.clip(stock, 0, 255)), "RGB")


def create(library):
    size = 880, 478
    stencil = die_art(size)
    design = np.array(stencil) >= 128
    chosen = defaults(*size)
    chosen.update(inspect=[82, 80, 788, 411], gold=[159, 176, 197, 199],
                  paper=[102, 282, 158, 311], line=[310, 354, 705, 354])
    return library.create("子午线礼盒 · 合成练习", {
        "design": (stencil, "meridian-die.png"),
        "a": (reflectance(design, 1), "meridian-light-a.png"),
        "b": (reflectance(design, -1), "meridian-light-b.png"),
    }, chosen, synthetic=True)
