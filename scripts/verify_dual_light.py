#!/usr/bin/env python3 -P
"""Verify the dual-light transfer coverage check end to end.

Run with the project on PYTHONPATH, e.g.::

    PYTHONPATH=/workspace:/opt/pointwise-env/site-packages python3 -P \\
        scripts/verify_dual_light.py
"""

import csv
import io
import sys
import tempfile
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from foilbench import analysis, demo, frame, output
from foilbench.model import defaults
from foilbench.store import Library
from foilbench.__main__ import application

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition), detail))
    print(("  ok  " if condition else " FAIL ") + name + (f"  ({detail})" if detail else ""))


def make_library():
    root = Path(tempfile.mkdtemp(prefix="foilbench-dual-"))
    return Library(root / "proofs")


def settings_for(record, **overrides):
    chosen = dict(record["settings"])
    chosen.update(overrides)
    return chosen


def main():
    library = make_library()
    record = demo.create(library)
    settings = settings_for(record)

    print("== 1. 合成练习双灯仲裁 ==")
    rgb_a, rgb_b, design, _, _, detect_a, detect_b = analysis.dual_layers(library, record, settings)
    masks = analysis.dual_arbitration(design, detect_a, detect_b)
    h, w = design.shape
    y, x = np.indices((h, w))
    dim = (x > 342) & (x < 373) & (y > 341) & (y < 369) & design
    speck = (x - 599) ** 2 / 65 + (y - 353) ** 2 / 45 < 1
    check("暗块（单灯漏检、与已确认箔整边相接）全部救回为已转移",
          bool((masks["rescued"] & dim).sum() == dim.sum() and dim.sum() > 0),
          f"dim={int(dim.sum())} rescued={int((masks['rescued'] & dim).sum())}")
    check("缺口内单灯孤立亮点不被当成转移，全部待复看",
          bool((masks["transfer"] & speck).sum() == 0 and (masks["pending"] & speck).sum() == speck.sum()),
          f"speck={int(speck.sum())}")
    check("待复看口径仅限版图内（留白反光不进覆盖账）",
          bool((masks["pending"] & ~design).sum() == 0),
          f"outside={int((masks['pending'] & ~design).sum())}")
    check("已转移 + 缺箔 + 待复看 覆盖版图内全部像素",
          np.array_equal(masks["transfer"] | masks["gap"] | masks["pending"], design))
    check("两灯一致位置按一致结果判（都有=已转移，都无=缺箔）",
          bool((masks["confirmed"] == (design & detect_a & detect_b)).all())
          and bool((masks["gap"] & detect_a & detect_b).sum() == 0))

    print("== 2. 对调两灯判定完全相同 ==")
    swapped = analysis.dual_arbitration(design, detect_b, detect_a)
    for key in ("transfer", "gap", "pending", "rescued", "confirmed"):
        check(f"对调后 {key} 掩码一致", np.array_equal(swapped[key], masks[key]))
    report_ab = analysis.report(library, record, settings, "coverage")
    record_swapped = dict(record)
    record_swapped["sources"] = {"design": record["sources"]["design"],
                                 "a": record["sources"]["b"], "b": record["sources"]["a"]}
    report_ba = analysis.report(library, record_swapped, settings, "coverage")
    symmetric_keys = ("expected_px", "transfer_px", "gap_px", "review_px",
                      "coverage_pct", "expected_mm2", "gap_mm2", "review_mm2")
    check("对调后覆盖率与三类判定数值一致",
          all(report_ab["rows"][0][key] == report_ba["rows"][0][key] for key in symmetric_keys))
    check("对调后两灯检出列互换",
          report_ab["rows"][0]["light_a_px"] == report_ba["rows"][0]["light_b_px"]
          and report_ab["rows"][0]["light_b_px"] == report_ba["rows"][0]["light_a_px"])

    print("== 3. 覆盖率只数可确认版图像素，待复看单列 ==")
    row = report_ab["rows"][0]
    decided = row["transfer_px"] + row["gap_px"]
    inspect_die = int(design[
        settings["inspect"][1]:settings["inspect"][3],
        settings["inspect"][0]:settings["inspect"][2]].sum())
    check("分母=已转移+缺箔+待复看=检查窗内版图像素",
          row["expected_px"] == decided + row["review_px"] == inspect_die,
          f"expected={row['expected_px']} decided={decided} review={row['review_px']} die={inspect_die}")
    check("覆盖率=已转移/可确认像素（待复看不计入）",
          row["coverage_pct"] == round(100 * row["transfer_px"] / decided, 2))
    check("待复看面积单独给出", row["review_mm2"] >= 0 and isinstance(row["review_px"], int))

    print("== 4. 双灯点检：同源坐标看到两盏灯的箔色与当前判定 ==")
    py, px = np.where(dim)
    point_dim = (int(px[0]), int(py[0]))
    reading = analysis.dual_point_reading(library, record, settings, point_dim)
    check("暗块点检判定为已转移（救回）", reading["verdict"] == analysis.TRANSFERRED and reading["rescued"])
    check("点检同时返回灯 A、灯 B 的 RGB、箔色与单灯判定",
          len(reading["lights"]) == 2 and {item["light"] for item in reading["lights"]} == {"a", "b"}
          and all("rgb" in item and "score" in item and "foil" in item for item in reading["lights"]))
    sy, sx = np.where(speck)
    reading_speck = analysis.dual_point_reading(library, record, settings, (int(sx[0]), int(sy[0])))
    check("缺口亮点点检判定为待复看", reading_speck["verdict"] == analysis.REVIEW)
    gy, gx = np.where((x - 211) ** 2 + (y - 281) ** 2 < 26)
    reading_glint = analysis.dual_point_reading(library, record, settings, (int(gx[0]), int(gy[0])))
    check("留白区分歧点检为待复看而非越界", reading_glint["verdict"] == analysis.REVIEW)

    print("== 5. 单灯印样继续走原来的单灯检查 ==")
    single = dict(record)
    single["sources"] = {role: record["sources"][role] for role in ("design", "a")}
    check("has_two_lights 对单灯印样为 False", analysis.has_two_lights(single) is False)
    single_report = analysis.report(library, single, settings, "coverage")
    check("单灯报告不携带 dual_light 标记", not single_report.get("dual_light"))
    legacy_keys = {"expected_px", "transfer_px", "gap_px", "coverage_pct", "expected_mm2", "gap_mm2"}
    check("单灯报告保持原有字段", set(single_report["rows"][0]) == legacy_keys)
    single_reading = analysis.point_reading(library, single, settings, point_dim)
    check("单灯点检保持原有结构",
          set(single_reading) == {"x", "y", "rgb", "score", "light", "expected", "foil", "classification"})
    single_modes = [analysis.report(library, single, settings, mode)
                    for mode in ("gaps", "leaks", "profile", "references", "distribution")]
    check("单灯其余检查项目照常产出", all(report["rows"] is not None for report in single_modes))

    print("== 6. 合成小图仲裁判据 ==")
    # 1px 细线中段漏检：两端各一个接触，共 2 个 -> 救回
    tiny_design = np.zeros((9, 21), bool)
    tiny_design[4, 1:20] = True
    ta = tiny_design.copy()
    tb = tiny_design.copy()
    tb[4, 8:14] = False
    tiny = analysis.dual_arbitration(tiny_design, ta, tb)
    check("1px 暗细线中段（两端接已确认箔）救回", bool(tiny["rescued"][4, 8:14].all())
          and tiny["pending"].sum() == 0)
    # 缺口里单点探入：仅 1 个接触 -> 待复看
    gap_design = np.zeros((11, 11), bool)
    gap_design[3:8, 1:10] = True
    ga, gb = gap_design.copy(), gap_design.copy()
    ga[3:8, 4:9] = False
    gb[3:8, 4:9] = False
    ga[5, 4] = True
    gap_case = analysis.dual_arbitration(gap_design, ga, gb)
    check("缺口单点探入不救回、标待复看", gap_case["transfer"][5, 4] == False
          and gap_case["pending"][5, 4] == True)
    # 完全孤立亮点
    ga[5, 6] = True
    isolated = analysis.dual_arbitration(gap_design, ga, gb)
    check("缺口完全孤立亮点标待复看", isolated["pending"][5, 6] == True
          and isolated["transfer"][5, 6] == False)

    print("== 6b. 检查窗口径：窗外像素不进任何计数 ==")
    # 只框住暗块 dim（约 x343-372, y342-368），把缺口亮点排除在窗外
    windowed = settings_for(record, inspect=[343, 342, 373, 369])
    win_report = analysis.report(library, record, windowed, "coverage")
    win_row = win_report["rows"][0]
    win_design = int(analysis.section(design, windowed["inspect"]).sum())
    win_rescued = int(analysis.section(masks["rescued"], windowed["inspect"]).sum())
    check("窗口内版图像素与 expected_px 一致", win_row["expected_px"] == win_design,
          f"expected={win_row['expected_px']} die={win_design}")
    check("窗口内救回数与表格转移一致", win_report["meta"]["rescued_px"] == win_rescued
          and win_row["transfer_px"] == win_rescued)
    check("缺口亮点在窗外，待复看计数为 0", win_row["review_px"] == 0
          and win_report["meta"]["pending_px"] == 0)
    check("meta 与表格同为检查窗口径", win_report["meta"]["pending_px"] == win_row["review_px"])
    # 极小窗（不含任何版图）应安全给出 None 覆盖率
    blank = settings_for(record, inspect=[0, 0, 8, 8])
    blank_report = analysis.report(library, record, blank, "coverage")["rows"][0]
    check("无版图像素的窗覆盖率为 None 且不报错", blank_report["coverage_pct"] is None
          and blank_report["expected_px"] == 0)

    print("== 7. CSV 与标记图导出 ==")
    text = output.csv_text(report_ab)
    reader = list(csv.reader(io.StringIO(text)))
    check("CSV 头部标注 dual_light True", reader[0][4] == "dual_light" and reader[0][5] == "True")
    check("CSV 含待复看列", "review_px" in reader[3] and "review_mm2" in reader[3])
    legacy_text = output.csv_text(single_report)
    check("单灯 CSV 标注 dual_light False", legacy_text.splitlines()[0].endswith("False"))
    overlay_png = output.overlay(library, record, report_ab)
    with Image.open(BytesIO(overlay_png)) as picture:
        check("双灯标记图可解码且尺寸同源", picture.size == (record["width"], record["height"]))
    legacy_overlay = output.overlay(library, single, single_report)
    check("单灯标记图仍走旧渲染", legacy_overlay[:8] == b"\x89PNG\r\n\x1a\n")

    print("== 8. HTTP 全链路（预览、双灯点检、存档与重开）==")
    app = application(data=library.root.parent)
    client = app.test_client()
    panel_id = record["id"]
    preview = client.post(f"/foil/panels/{panel_id}/preview",
                          json={"settings": settings, "mode": "coverage", "revision": record["revision"]})
    check("预览接口返回双灯报告", preview.status_code == 200
          and preview.get_json().get("dual_light") is True)
    point_reply = client.post(f"/foil/panels/{panel_id}/point",
                              json={"settings": settings, "point": list(point_dim)})
    payload = point_reply.get_json()
    check("点检接口返回两盏灯读数", point_reply.status_code == 200
          and payload["dual_light"] is True and len(payload["lights"]) == 2)
    saved = client.post(f"/foil/panels/{panel_id}/reports",
                        json={"settings": settings, "mode": "coverage", "revision": record["revision"]})
    check("存档成功", saved.status_code == 201)
    report_id = saved.get_json()["report"]["id"]
    reopened = client.get(f"/foil/panels/{panel_id}/reports/{report_id}")
    check("重开存档仍为双灯报告", reopened.status_code == 200
          and reopened.get_json()["dual_light"] is True)
    saved_point = client.post(f"/foil/panels/{panel_id}/point",
                              json={"report": report_id, "point": list(point_dim)})
    check("存档点检仍返回双灯读数", saved_point.get_json()["dual_light"] is True)
    saved_overlay = client.get(f"/foil/panels/{panel_id}/reports/{report_id}/overlay.png")
    check("存档标记图可下载", saved_overlay.status_code == 200
          and saved_overlay.data[:8] == b"\x89PNG\r\n\x1a\n")
    saved_csv = client.get(f"/foil/panels/{panel_id}/reports/{report_id}/report.csv")
    check("存档 CSV 可下载且含待复看列", saved_csv.status_code == 200
          and "review_px" in saved_csv.data.decode())
    # 单灯印样 HTTP 链路
    single_record = library.create("单灯印样", {
        role: (Image.open(library.source(record, role)), record["sources"][role]["name"])
        for role in ("design", "a")}, defaults(record["width"], record["height"]))
    single_preview = client.post(f"/foil/panels/{single_record['id']}/preview",
                                 json={"settings": single_record["settings"], "mode": "coverage",
                                       "revision": single_record["revision"]})
    check("单灯印样预览仍是旧单灯报告", single_preview.status_code == 200
          and not single_preview.get_json().get("dual_light"))
    single_point = client.post(f"/foil/panels/{single_record['id']}/point",
                               json={"settings": single_record["settings"], "point": list(point_dim)})
    check("单灯印样点检保持旧结构", "classification" in single_point.get_json()
          and "lights" not in single_point.get_json())

    failures = [name for name, ok, _ in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failures)}/{len(CHECKS)} 项通过")
    if failures:
        print("失败项：")
        for name in failures:
            print(" -", name)
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
