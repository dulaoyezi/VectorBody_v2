# -*- coding: utf-8 -*-
"""Format cleanup and typo fixes for C:\\小杜\\昆仑的队\\PPT.pptx."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pythoncom
import win32com.client


PPT_PATH = Path("C:/\u5c0f\u675c/\u6606\u4ed1\u7684\u961f/PPT.pptx")

MSO_TRUE = -1
MSO_FALSE = 0
MSO_ALIGN_CENTER = 2
MSO_ALIGN_LEFT = 1


def rgb(hex_color: str) -> int:
    hex_color = hex_color.strip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return r + (g << 8) + (b << 16)


def has_text(shape) -> bool:
    try:
        return bool(shape.HasTextFrame and shape.TextFrame.HasText)
    except Exception:
        return False


def text_of(shape) -> str:
    if not has_text(shape):
        return ""
    try:
        return str(shape.TextFrame.TextRange.Text)
    except Exception:
        return ""


def set_text(shape, text: str, size: float | None = None, color: str | None = None, bold: bool | None = None, align: int | None = None) -> None:
    shape.TextFrame.TextRange.Text = text
    shape.TextFrame.WordWrap = MSO_TRUE
    try:
        shape.TextFrame.MarginLeft = 5
        shape.TextFrame.MarginRight = 5
        shape.TextFrame.MarginTop = 3
        shape.TextFrame.MarginBottom = 3
    except Exception:
        pass
    tr = shape.TextFrame.TextRange
    tr.Font.Name = "Microsoft YaHei"
    tr.Font.NameFarEast = "Microsoft YaHei"
    if size is not None:
        tr.Font.Size = size
    if color is not None:
        tr.Font.Color.RGB = rgb(color)
    if bold is not None:
        tr.Font.Bold = MSO_TRUE if bold else MSO_FALSE
    if align is not None:
        tr.ParagraphFormat.Alignment = align


def style_existing_text(shape) -> None:
    if not has_text(shape):
        return
    tr = shape.TextFrame.TextRange
    try:
        tr.Font.Name = "Microsoft YaHei"
        tr.Font.NameFarEast = "Microsoft YaHei"
    except Exception:
        pass


def delete_shapes_by_indices(slide, indices: list[int]) -> None:
    for idx in sorted(indices, reverse=True):
        if idx <= slide.Shapes.Count:
            slide.Shapes(idx).Delete()


def add_subtitle_to_thanks(slide) -> None:
    shape = slide.Shapes.AddTextbox(1, 300, 278, 370, 36)
    set_text(shape, "敬请各位老师批评指正", 20, "063A6B", False, MSO_ALIGN_CENTER)
    shape.Line.Visible = MSO_FALSE
    shape.Fill.Visible = MSO_FALSE


def optimize() -> None:
    if not PPT_PATH.exists():
        raise FileNotFoundError(PPT_PATH)

    backup = PPT_PATH.with_name("PPT_format_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".pptx")
    shutil.copy2(PPT_PATH, backup)

    pythoncom.CoInitialize()
    ppt = win32com.client.DispatchEx("PowerPoint.Application")
    pres = None
    try:
        pres = ppt.Presentations.Open(str(PPT_PATH), False, False, False)

        # Global font pass.
        for slide in pres.Slides:
            for i in range(1, slide.Shapes.Count + 1):
                style_existing_text(slide.Shapes(i))

        # Slide 3: avoid repeating the slide-2 subtitle.
        s3 = pres.Slides(3)
        for i in range(1, s3.Shapes.Count + 1):
            sh = s3.Shapes(i)
            if "高校瑜伽教学需要低成本" in text_of(sh):
                set_text(sh, "建立“视觉输入—拓扑建模—稳定优化—评分反馈”的闭环流程", 20, "2C5C7B", False, MSO_ALIGN_CENTER)
                break

        # Slide 5: typo and title layout.
        s5 = pres.Slides(5)
        for i in range(1, s5.Shapes.Count + 1):
            sh = s5.Shapes(i)
            if "核心技术二" in text_of(sh):
                sh.Left = 198
                sh.Top = 58
                sh.Width = 610
                sh.Height = 70
                set_text(
                    sh,
                    "核心技术二、三：拓扑约束 DLS 稳定化\n与发力模式视觉代理三维评分",
                    24,
                    "063A6B",
                    True,
                    MSO_ALIGN_CENTER,
                )
                break

        # Slide 6: fix title wording and remove accidental red connectors.
        s6 = pres.Slides(6)
        for i in range(1, s6.Shapes.Count + 1):
            sh = s6.Shapes(i)
            if "系统实现" in text_of(sh):
                sh.Left = 130
                sh.Width = 700
                set_text(sh, "系统实现与测试结果", 24, "063A6B", True, MSO_ALIGN_CENTER)
                break
        # In this deck the diagonal red callout lines are connector shapes 8-10.
        # Delete by geometry/type so normal screenshots and charts stay intact.
        remove = []
        for i in range(1, s6.Shapes.Count + 1):
            sh = s6.Shapes(i)
            try:
                if sh.Type == 23 and sh.Line.Visible and sh.Width > 70 and sh.Height > 70:
                    remove.append(i)
            except Exception:
                pass
        delete_shapes_by_indices(s6, remove)

        # Slide 7: it contains a hidden old "测试与分析" layer underneath the summary.
        s7 = pres.Slides(7)
        remove = []
        for i in range(1, s7.Shapes.Count + 1):
            txt = text_of(s7.Shapes(i))
            if (
                "测试与分析" in txt
                or "教师一致性" in txt
                or "采集 30 名受试者" in txt
                or "VectorBody 2.0  |  4-5分钟展示  |  08" in txt
            ):
                remove.append(i)
        # Also remove the hidden old background/panel pieces before the visible summary layer.
        remove.extend([1, 2, 5, 8])
        delete_shapes_by_indices(s7, sorted(set(remove)))
        for i in range(1, s7.Shapes.Count + 1):
            sh = s7.Shapes(i)
            txt = text_of(sh)
            if "应用价值与总结" in txt:
                sh.Left = 120
                sh.Width = 520
                set_text(sh, "应用价值与总结", 24, "063A6B", True, MSO_ALIGN_CENTER)
            elif "面向智能体育教学" in txt:
                sh.Left = 200
                sh.Width = 560
                set_text(sh, "面向智能体育教学的低成本视觉评估路径", 18, "2C5C7B", False, MSO_ALIGN_CENTER)
            else:
                style_existing_text(sh)

        # Slide 8: remove empty textbox and polish final page.
        s8 = pres.Slides(8)
        remove = []
        for i in range(1, s8.Shapes.Count + 1):
            txt = text_of(s8.Shapes(i))
            if has_text(s8.Shapes(i)) and not txt.strip():
                remove.append(i)
        delete_shapes_by_indices(s8, remove)
        for i in range(1, s8.Shapes.Count + 1):
            sh = s8.Shapes(i)
            if "感谢聆听" in text_of(sh):
                sh.Left = 284
                sh.Top = 205
                sh.Width = 390
                sh.Height = 70
                set_text(sh, "感谢聆听", 36, "063A6B", True, MSO_ALIGN_CENTER)
        add_subtitle_to_thanks(s8)

        pres.Save()
        print(f"updated={PPT_PATH}")
        print(f"backup={backup}")
    finally:
        if pres is not None:
            pres.Close()
        ppt.Quit()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    optimize()
