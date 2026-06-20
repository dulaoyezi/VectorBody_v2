# -*- coding: utf-8 -*-
"""Generate the VectorBody 4-5 minute PPT through PowerPoint COM."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pythoncom
import win32com.client


OUT_DIR = Path(r"D:\VectorBody")
BG_IMAGE = Path(
    r"D:\WeChat\xwechat_files\zhangyingxia7912_4fd4\temp\RWTemp\2026-06"
    r"\7670859d0a5e43c7d88aff40ef4b995c.jpg"
)
PPTX_PATH = OUT_DIR / "VectorBody_4到5分钟展示PPT.pptx"
SCRIPT_PATH = OUT_DIR / "VectorBody_4到5分钟展示讲稿.md"

SLIDE_W = 960
SLIDE_H = 540

MSO_TRUE = -1
MSO_FALSE = 0
MSO_SHAPE_RECT = 1
MSO_SHAPE_ROUND_RECT = 5
MSO_TEXT_HORIZONTAL = 1
MSO_ALIGN_LEFT = 1
MSO_ALIGN_CENTER = 2
MSO_ANCHOR_TOP = 1
MSO_CONNECTOR_STRAIGHT = 1
MSO_ARROW_TRIANGLE = 3
PP_LAYOUT_BLANK = 12
PP_SAVE_AS_OPEN_XML = 24


def rgb(hex_color: str) -> int:
    hex_color = hex_color.strip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return r + (g << 8) + (b << 16)


SLIDES = [
    {
        "kind": "cover",
        "title": "VectorBody 2.0",
        "subtitle": "基于 MediaPipe 的人体拓扑树与 DLS 迭代算法框架",
        "lines": [
            "用于瑜伽体式视觉生物力学代理评估",
            "团队：昆仑的队  |  西安电子科技大学",
            "答辩时长：4-5 分钟",
        ],
    },
    {
        "title": "选题背景与关键痛点",
        "subtitle": "高校瑜伽教学需要低成本、可解释、可回放的辅助评估",
        "bullets": [
            "仅靠教师肉眼评分，难以对多人训练过程持续量化",
            "传统生物力学设备成本高、布置复杂，不适合日常教学",
            "单目视频关键点存在体型差异、遮挡和静态抖动问题",
            "真实肌肉发力难以直接测量，需要转化为可见结构代理",
        ],
    },
    {
        "kind": "pipeline",
        "title": "总体方案：从视频到评分反馈",
        "subtitle": "把离散关键点组织成可解释的身体结构，再进行稳定化与评分",
        "steps": ["RGB视频", "MediaPipe 33点", "骨盆根拓扑树", "DLS稳定", "三维评分", "反馈归档"],
    },
    {
        "title": "核心技术一：骨盆根人体拓扑树",
        "subtitle": "评分不只看孤立坐标，而是看身体链式关系",
        "bullets": [
            "以左右髋中点构建骨盆中心，并作为人体拓扑根节点",
            "形成躯干链、上肢伸展链、下肢支撑链三类结构",
            "通过骨骼向量、单位方向和虚拟骨长描述节段关系",
            "降低镜头距离、身高臂长差异对评分的干扰",
        ],
    },
    {
        "title": "核心技术二：拓扑约束 DLS 稳定化",
        "subtitle": "解决静态保持中 MediaPipe 关键点抖动的问题",
        "bullets": [
            "目标：在贴合观测关键点的同时保持骨长和时间连续",
            "残差项：观测拟合误差 + 骨长一致误差 + 时间连续误差",
            "采用阻尼最小二乘迭代，提升接近奇异姿态时的求解稳定性",
            "输出稳定后的拓扑关键点，为后续评分提供可靠输入",
        ],
    },
    {
        "kind": "score",
        "title": "核心技术三：发力模式视觉代理与三维评分",
        "subtitle": "不直接宣称测量肌肉力，而是评估可见的支撑与代偿趋势",
    },
    {
        "title": "系统实现：实时检测、提示与归档",
        "subtitle": "已形成可运行的软件链路，而不是单独算法原型",
        "bullets": [
            "支持摄像头实时检测与本地视频导入分析",
            "界面显示综合评分、三个维度评分、代偿风险和纠正建议",
            "语音模块异步播报提示，避免阻塞画面刷新",
            "视频模式自动记录最高评分帧，并生成训练报告归档",
        ],
    },
    {
        "title": "测试与分析",
        "subtitle": "从教师一致性、模块消融和跨动作适应性三个角度验证",
        "bullets": [
            "采集 30 名受试者、覆盖 7 类 8 个核心瑜伽体式",
            "每名受试者完成多次保持动作，形成约 1500 段原始视频",
            "采用 Pearson、Spearman、MAE、RMSE、ICC 与教师评分比较",
            "消融实验表明：拓扑树、DLS 和发力代理三部分互补而非冗余",
        ],
    },
    {
        "title": "应用价值与总结",
        "subtitle": "面向智能体育教学的低成本视觉评估路径",
        "bullets": [
            "普通 RGB 摄像头即可部署，适合课堂训练与课后视频复盘",
            "输出百分制评分、等级、风险维度和可解释纠正建议",
            "可辅助教师发现膝内扣、躯干侧倾、肩颈/腰椎代偿等问题",
            "定位是教学辅助评估，不替代专业教师或医学诊断",
        ],
    },
]

SCRIPT = """# VectorBody 2.0 4-5分钟展示讲稿

## 1. 封面（约20秒）
各位老师好，我们的作品是 VectorBody 2.0，题目是基于 MediaPipe 的人体拓扑树与 DLS 迭代算法框架，用于瑜伽体式视觉生物力学代理评估。简单来说，我们希望用普通摄像头，对瑜伽动作质量进行低成本、可解释的辅助评分。

## 2. 选题背景与痛点（约35秒）
这个题目来自高校瑜伽教学中的真实需求。教师可以判断动作是否标准，但在多人课堂和课后训练中，很难持续量化每个人的动作质量。传统生物力学设备虽然准确，但成本高、布置复杂，不适合日常教学。视觉方案成本低，但会遇到体型差异、单目关键点抖动，以及真实发力无法直接测量的问题。所以我们的目标不是替代教师，而是提供一个可回放、可解释的辅助评估工具。

## 3. 总体方案（约30秒）
系统流程分为六步。首先输入摄像头或视频画面，然后用 MediaPipe 提取 33 个人体关键点。接着，我们不直接用这些离散点评分，而是构建以骨盆为根节点的人体拓扑树。随后用拓扑约束 DLS 方法稳定关键点，最后通过三维评分模型输出总分、风险维度和纠正建议。

## 4. 人体拓扑树（约35秒）
第一个核心技术是人体拓扑树。系统用左右髋中点作为骨盆中心，并作为根节点，把身体组织成躯干链、上肢伸展链和下肢支撑链。这样评分依据从单个坐标转为相对结构关系。例如战士二式中，我们关注的是前腿支撑链、骨盆稳定、肩臂水平和躯干相对骨盆的偏移，而不是某一个点的绝对位置。

## 5. DLS 稳定化（约35秒）
第二个核心技术是拓扑约束 DLS 稳定化。静态保持动作里，人实际上变化很小，但 MediaPipe 关键点会因为遮挡、衣物边缘或置信度变化出现抖动。我们把观测拟合误差、骨长一致误差和时间连续误差放进统一优化目标，通过阻尼最小二乘迭代修正关键点，使骨架序列更稳定。

## 6. 三维评分（约45秒）
第三个核心技术是发力模式视觉代理和三维评分。由于单目视频不能直接测量肌肉激活和关节力矩，我们把“发力是否合理”转化为可见结构代理，包括关节对齐、支撑链连续、骨盆控制和躯干稳定。最终评分由三个维度融合：关节-姿态符合度占 30%，拓扑稳定与代偿控制占 35%，发力模式代理合理性占 35%。这样既有动作标准度，也有稳定性和代偿风险。

## 7. 系统实现（约35秒）
在软件实现上，系统已经形成完整链路。用户可以使用摄像头实时检测，也可以导入视频分析。界面会显示综合评分、三维评分、风险提示和纠正建议。语音模块异步播报，不影响画面刷新。视频模式还会记录整段视频的最高评分帧，并生成训练报告，便于课后复盘。

## 8. 测试分析（约40秒）
测试部分选取 30 名受试者，覆盖 7 类 8 个核心瑜伽体式，形成约 1500 段原始视频。我们用 Pearson、Spearman、MAE、RMSE 和 ICC 等指标与教师评分比较，并进行模块消融。结果表明，完整系统在评分一致性、误差控制和稳定性上优于去掉单一模块的版本，说明拓扑树、DLS 和发力代理是互补关系。

## 9. 总结（约30秒）
最后总结一下，VectorBody 2.0 的价值在于用普通 RGB 视频实现低成本、无标记、可解释的瑜伽动作辅助评估。它能够输出评分、等级、风险维度和纠正建议，帮助教师发现膝内扣、躯干侧倾、肩颈或腰椎代偿等问题。当然，它不是医学诊断，也不替代专业教师，而是为智能体育教学提供一种可部署的视觉评估路径。谢谢各位老师。
"""


def set_text(shape, text: str, size: float, color: str = "0B2239", bold: bool = False, align: int = MSO_ALIGN_LEFT):
    tf = shape.TextFrame2
    tf.TextRange.Text = text
    tf.WordWrap = MSO_TRUE
    tf.VerticalAnchor = MSO_ANCHOR_TOP
    tf.MarginLeft = 5
    tf.MarginRight = 5
    tf.MarginTop = 3
    tf.MarginBottom = 3
    tr = tf.TextRange
    tr.Font.Name = "Microsoft YaHei"
    tr.Font.NameFarEast = "Microsoft YaHei"
    tr.Font.Size = size
    tr.Font.Bold = MSO_TRUE if bold else MSO_FALSE
    tr.Font.Fill.ForeColor.RGB = rgb(color)
    tr.ParagraphFormat.Alignment = align


def add_text(slide, text: str, x: float, y: float, w: float, h: float, size: float, color: str = "0B2239", bold: bool = False, align: int = MSO_ALIGN_LEFT):
    shape = slide.Shapes.AddTextbox(MSO_TEXT_HORIZONTAL, x, y, w, h)
    set_text(shape, text, size, color, bold, align)
    shape.Line.Visible = MSO_FALSE
    shape.Fill.Visible = MSO_FALSE
    return shape


def add_panel(slide, x: float, y: float, w: float, h: float, fill: str = "FFFFFF", line: str = "BFE5F2", transparency: float = 0.12, rounded: bool = True):
    shape_type = MSO_SHAPE_ROUND_RECT if rounded else MSO_SHAPE_RECT
    shape = slide.Shapes.AddShape(shape_type, x, y, w, h)
    shape.Fill.Visible = MSO_TRUE
    shape.Fill.Solid()
    shape.Fill.ForeColor.RGB = rgb(fill)
    shape.Fill.Transparency = transparency
    shape.Line.Visible = MSO_TRUE
    shape.Line.ForeColor.RGB = rgb(line)
    shape.Line.Transparency = 0
    shape.Line.Weight = 1.25
    return shape


def add_title(slide, title: str, subtitle: str | None):
    accent = slide.Shapes.AddShape(MSO_SHAPE_RECT, 45, 44, 6, 42)
    accent.Fill.ForeColor.RGB = rgb("00A6D6")
    accent.Line.Visible = MSO_FALSE
    add_text(slide, title, 56, 34, 505, 42, 23, "063A6B", True)
    if subtitle:
        add_text(slide, subtitle, 58, 72, 520, 28, 11.5, "2C5C7B")


def add_footer(slide, page: int):
    add_text(slide, f"VectorBody 2.0  |  4-5分钟展示  |  {page:02d}", 57, 505, 330, 18, 7.5, "4B6D84")


def add_bullets(slide, bullets: list[str], x: float = 64, y: float = 116, w: float = 475, h: float = 330):
    add_panel(slide, x - 6, y - 8, w + 12, h + 16)
    text = "\r".join(f"• {b}" for b in bullets)
    shape = add_text(slide, text, x + 10, y + 8, w - 20, h - 16, 14.5, "0B2239")
    shape.TextFrame2.TextRange.ParagraphFormat.SpaceAfter = 8
    return shape


def add_metric_card(slide, x: float, y: float, title: str, body: str, color: str):
    add_panel(slide, x, y, 154, 88, fill="FFFFFF", line=color, transparency=0.08)
    add_text(slide, title, x + 8, y + 13, 138, 24, 12, color, True, MSO_ALIGN_CENTER)
    add_text(slide, body, x + 10, y + 43, 134, 30, 9.5, "0B2239", False, MSO_ALIGN_CENTER)


def add_bg(slide):
    pic = slide.Shapes.AddPicture(str(BG_IMAGE), MSO_FALSE, MSO_TRUE, 0, 0, SLIDE_W, SLIDE_H)
    pic.ZOrder(1)


def build():
    if not BG_IMAGE.exists():
        raise FileNotFoundError(BG_IMAGE)

    pythoncom.CoInitialize()
    ppt = win32com.client.DispatchEx("PowerPoint.Application")
    pres = None
    try:
        pres = ppt.Presentations.Add(WithWindow=MSO_FALSE)
        pres.PageSetup.SlideWidth = SLIDE_W
        pres.PageSetup.SlideHeight = SLIDE_H

        for idx, data in enumerate(SLIDES, 1):
            slide = pres.Slides.Add(idx, PP_LAYOUT_BLANK)
            add_bg(slide)

            if data.get("kind") == "cover":
                add_panel(slide, 64, 154, 500, 236, transparency=0.13)
                add_text(slide, data["title"], 86, 171, 455, 58, 38, "063A6B", True)
                add_text(slide, data["subtitle"], 88, 226, 455, 33, 16, "164B73")
                y = 272
                for line in data["lines"]:
                    add_text(slide, line, 91, y, 440, 24, 12.5, "1F4256")
                    y += 30
                add_footer(slide, idx)
                continue

            add_title(slide, data["title"], data.get("subtitle"))

            if data.get("kind") == "pipeline":
                colors = ["0077B6", "0096C7", "00A6D6", "26B99A", "F59E0B", "EF6C35"]
                x0, y0, bw, bh, gap = 57, 224, 116, 62, 22
                for i, step in enumerate(data["steps"]):
                    x = x0 + i * (bw + gap)
                    add_panel(slide, x, y0, bw, bh, line=colors[i], transparency=0.06)
                    add_text(slide, step, x + 7, y0 + 20, bw - 14, 22, 10.5, colors[i], True, MSO_ALIGN_CENTER)
                    if i < len(data["steps"]) - 1:
                        conn = slide.Shapes.AddConnector(MSO_CONNECTOR_STRAIGHT, x + bw, y0 + bh / 2, x + bw + gap - 4, y0 + bh / 2)
                        conn.Line.ForeColor.RGB = rgb("14A3D9")
                        conn.Line.EndArrowheadStyle = MSO_ARROW_TRIANGLE
                        conn.Line.Weight = 1.6
                add_bullets(
                    slide,
                    [
                        "前端：摄像头/视频导入、骨架可视化、语音提示",
                        "算法：关键点稳定、拓扑树、DLS、虚拟骨长、风险评分",
                        "输出：百分制总分、三维分项、风险部位、训练报告",
                    ],
                    75,
                    333,
                    470,
                    105,
                )
            elif data.get("kind") == "score":
                add_metric_card(slide, 66, 156, "关节-姿态符合度", "角度 / 对齐 / 范围", "0077B6")
                add_metric_card(slide, 235, 156, "拓扑稳定与代偿控制", "骨长 / 时序 / 支撑链", "009688")
                add_metric_card(slide, 404, 156, "发力模式代理合理性", "支撑 / 骨盆 / 躯干", "E87500")
                add_panel(slide, 68, 310, 470, 86, transparency=0.10)
                add_text(
                    slide,
                    "综合评分 = 0.30 × 符合度 + 0.35 × 稳定控制 + 0.35 × 发力代理",
                    84,
                    324,
                    438,
                    28,
                    12.6,
                    "0B376D",
                    True,
                    MSO_ALIGN_CENTER,
                )
                add_text(
                    slide,
                    "核心代码：core/compensation_risk_engine.py  →  _score_dimensions()",
                    92,
                    358,
                    420,
                    22,
                    9.5,
                    "465A69",
                    False,
                    MSO_ALIGN_CENTER,
                )
            else:
                add_bullets(slide, data["bullets"])

            add_footer(slide, idx)

        if PPTX_PATH.exists():
            backup = PPTX_PATH.with_name(
                PPTX_PATH.stem + "_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".pptx"
            )
            shutil.copy2(PPTX_PATH, backup)
            PPTX_PATH.unlink()
        pres.SaveAs(str(PPTX_PATH), PP_SAVE_AS_OPEN_XML)
        SCRIPT_PATH.write_text(SCRIPT, encoding="utf-8")
    finally:
        if pres is not None:
            try:
                pres.Close()
            except Exception:
                pass
        ppt.Quit()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    build()
    print(PPTX_PATH)
    print(SCRIPT_PATH)
