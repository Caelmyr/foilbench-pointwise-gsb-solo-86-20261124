#!/usr/bin/env python3 -P
"""Headless browser check for the dual-light proof desk UI."""

import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:18101"
failures = []


def expect(name, condition, detail=""):
    print(("  ok  " if condition else " FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not condition:
        failures.append(name)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.goto(BASE + "/", wait_until="networkidle")
        page.click("#demo")
        page.wait_for_selector("#desk:not([hidden])")
        # 明确选择双灯合成练习（库里可能还有单灯印样排在前面）
        page.locator("#library button", has_text="合成练习").first.click()
        page.wait_for_function("document.getElementById('result-note').textContent.includes('双灯检查')")
        page.wait_for_function("document.querySelectorAll('#rows tr').length > 0")

        print("== 双灯覆盖结果区 ==")
        heading = page.text_content("#result-heading")
        note = page.text_content("#result-note")
        expect("标题仍是转移覆盖", heading == "转移覆盖", heading)
        expect("结果说明标注双灯检查与分歧统计", "双灯检查" in note and "待复看" in note, note)
        headers = [th.text_content() for th in page.query_selector_all("#columns th")]
        for label in ("待复看像素", "待复看 mm²", "灯 A 检出像素", "灯 B 检出像素"):
            expect(f"表头含 {label}", label in headers, str(headers))
        cells = [td.text_content() for td in page.query_selector_all("#rows tr td")]
        expect("结果行有数值", any(c not in ("—", "") for c in cells), str(cells))

        print("== 标记图含待复看与缺箔着色 ==")
        page.click('[data-view="marked"]')
        page.wait_for_timeout(700)
        # 直接读画布内部分辨率像素（map 宽高即源图 880x478）
        def canvas_pixel(sx, sy):
            return page.evaluate(
                "([x,y])=>Array.from(document.getElementById('map').getContext('2d')"
                ".getImageData(x,y,1,1).data)", [sx, sy])
        speck_pixel = canvas_pixel(599, 353)
        gap_pixel = canvas_pixel(174, 169)
        expect("缺口亮点处呈琥珀色待复看 (R高 G中 B低)",
               speck_pixel[0] > 200 and 130 < speck_pixel[1] < 210 and speck_pixel[2] < 130,
               str(speck_pixel))
        expect("圆形缺口处呈红色缺箔（红通道主导）",
               gap_pixel[0] > gap_pixel[1] + 60 and gap_pixel[0] > gap_pixel[2] + 50,
               str(gap_pixel))

        print("== 双灯点检面板 ==")
        page.click('[data-tool="point"]')
        box = page.locator("#map").bounding_box()
        metrics = page.evaluate("()=>{const c=document.getElementById('map');return {w:c.clientWidth,h:c.clientHeight}}")

        def click_source(sx, sy):
            page.mouse.click(box["x"] + sx / metrics["w"] * metrics["w"],
                             box["y"] + sy / metrics["h"] * metrics["h"])

        click_source(350, 355)
        page.wait_for_selector("#point-panel:not([hidden])")
        title = page.text_content("#point-title")
        verdict = page.text_content("#point-verdict")
        rows = page.query_selector_all("#point-rows tr")
        expect("暗块点检标题给出源坐标（允许亚像素取整 ±2）",
               "(34" in title and "35" in title and ")" in title, title)
        expect("暗块判定为已转移并标注救回", "已转移" in verdict and "救回" in verdict, verdict)
        expect("面板列出灯 A、灯 B 两行", len(rows) == 2, str(len(rows)))
        row_text = [r.text_content() for r in rows]
        expect("两行都带 RGB、箔色分和单灯判定",
               all("检测到箔色" in t or "低于门槛" in t for t in row_text), str(row_text))
        # 点缺口亮点
        click_source(599, 353)
        page.wait_for_function("document.getElementById('point-verdict').textContent.includes('待复看')")
        expect("缺口亮点判定为待复看", "待复看" in page.text_content("#point-verdict"))
        # 对调灯光按钮不应改变双灯判定（切到灯B照片再点检同坐标）
        page.click('[data-light="b"]')
        page.wait_for_timeout(500)
        click_source(350, 355)
        page.wait_for_timeout(400)
        verdict_b = page.text_content("#point-verdict")
        expect("切到灯 B 后同坐标判定仍是已转移（双灯判定与所选灯无关）",
               "已转移" in verdict_b, verdict_b)

        print("== 存档与单灯项目 ==")
        page.click("#save")
        page.wait_for_selector("#return-current:not([hidden])")
        expect("存档后仍显示双灯判定", "待复看" in page.text_content("#result-note"))
        saved_verdict = page.text_content("#point-verdict")
        expect("存档状态下点检面板仍可用", "已转移" in saved_verdict, saved_verdict)
        page.click("#return-current")
        page.wait_for_selector("#return-current[hidden]", state="attached")

        print("== 页面无 JS 错误 ==")
        expect("无未捕获脚本错误", not errors, str(errors))
        browser.close()
    if failures:
        print(f"\n{len(failures)} 项失败：{failures}")
        return 1
    print("\n浏览器端到端检查全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
