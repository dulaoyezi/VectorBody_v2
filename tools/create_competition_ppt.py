# -*- coding: utf-8 -*-
"""
Generate a 4-5 minute VectorBody competition presentation as a PPTX.

The script writes a native PowerPoint OpenXML package without external
PowerPoint/python-pptx dependencies.
"""
from __future__ import annotations

import html
import shutil
import zipfile
from datetime import datetime
from pathlib import Path


OUT_DIR = Path(r"D:\VectorBody")
BG_IMAGE = Path(
    r"D:\WeChat\xwechat_files\zhangyingxia7912_4fd4\temp\RWTemp\2026-06"
    r"\7670859d0a5e43c7d88aff40ef4b995c.jpg"
)
PPTX_PATH = OUT_DIR / "VectorBody_4到5分钟展示PPT.pptx"
SCRIPT_PATH = OUT_DIR / "VectorBody_4到5分钟展示讲稿.md"

SLIDE_W = 12192000
SLIDE_H = 6858000
EMU = 914400


def emu(inches: float) -> int:
    return int(round(inches * EMU))


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def rgb(color: str, alpha: int | None = None) -> str:
    color = color.strip("#").upper()
    if alpha is None:
        return f'<a:srgbClr val="{color}"/>'
    return f'<a:srgbClr val="{color}"><a:alpha val="{alpha}"/></a:srgbClr>'


def text_run(text: str, size: int, color: str, bold: bool = False) -> str:
    b = ' b="1"' if bold else ""
    return (
        f'<a:r><a:rPr lang="zh-CN" sz="{size}"{b}>'
        f'<a:solidFill>{rgb(color)}</a:solidFill>'
        '<a:latin typeface="Microsoft YaHei"/>'
        '<a:ea typeface="Microsoft YaHei"/>'
        '<a:cs typeface="Microsoft YaHei"/>'
        f'</a:rPr><a:t>{esc(text)}</a:t></a:r>'
    )


def paragraph(
    text: str,
    size: int,
    color: str = "0B2239",
    bold: bool = False,
    bullet: bool = False,
    align: str | None = None,
) -> str:
    align_attr = f' algn="{align}"' if align else ""
    if bullet:
        ppr = (
            f'<a:pPr marL="{emu(0.20)}" indent="-{emu(0.14)}"{align_attr}>'
            '<a:buChar char="•"/>'
            '</a:pPr>'
        )
    else:
        ppr = f'<a:pPr{align_attr}/>'
    return f"<a:p>{ppr}{text_run(text, size, color, bold)}</a:p>"


def text_box(
    shape_id: int,
    name: str,
    x: float,
    y: float,
    w: float,
    h: float,
    paragraphs_xml: str,
    fill: str | None = None,
    line_color: str | None = None,
    radius: bool = False,
    margin: float = 0.08,
) -> str:
    fill_xml = "<a:noFill/>" if fill is None else f"<a:solidFill>{fill}</a:solidFill>"
    line_xml = "<a:ln><a:noFill/></a:ln>" if line_color is None else (
        f'<a:ln w="12000"><a:solidFill>{rgb(line_color)}</a:solidFill></a:ln>'
    )
    prst = "roundRect" if radius else "rect"
    return f"""
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="{shape_id}" name="{esc(name)}"/>
          <p:cNvSpPr txBox="1"/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
          <a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>
          {fill_xml}
          {line_xml}
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square" anchor="t" lIns="{emu(margin)}" tIns="{emu(margin)}" rIns="{emu(margin)}" bIns="{emu(margin)}"/>
          <a:lstStyle/>
          {paragraphs_xml}
        </p:txBody>
      </p:sp>
    """


def rect(
    shape_id: int,
    name: str,
    x: float,
    y: float,
    w: float,
    h: float,
    color: str,
    alpha: int = 100000,
    line: str | None = None,
    radius: bool = False,
) -> str:
    line_xml = "<a:ln><a:noFill/></a:ln>" if line is None else (
        f'<a:ln w="14000"><a:solidFill>{rgb(line)}</a:solidFill></a:ln>'
    )
    prst = "roundRect" if radius else "rect"
    return f"""
      <p:sp>
        <p:nvSpPr><p:cNvPr id="{shape_id}" name="{esc(name)}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
          <a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>
          <a:solidFill>{rgb(color, alpha)}</a:solidFill>
          {line_xml}
        </p:spPr>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
      </p:sp>
    """


def line(shape_id: int, x1: float, y1: float, x2: float, y2: float, color: str = "14A3D9") -> str:
    return f"""
      <p:cxnSp>
        <p:nvCxnSpPr><p:cNvPr id="{shape_id}" name="connector {shape_id}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>
        <p:spPr>
          <a:xfrm><a:off x="{emu(min(x1, x2))}" y="{emu(min(y1, y2))}"/><a:ext cx="{emu(abs(x2-x1))}" cy="{emu(abs(y2-y1))}"/></a:xfrm>
          <a:prstGeom prst="line"><a:avLst/></a:prstGeom>
          <a:ln w="26000"><a:solidFill>{rgb(color)}</a:solidFill><a:tailEnd type="triangle"/></a:ln>
        </p:spPr>
      </p:cxnSp>
    """


def background_pic() -> str:
    return f"""
      <p:pic>
        <p:nvPicPr>
          <p:cNvPr id="2" name="background.jpg"/>
          <p:cNvPicPr><a:picLocks noChangeAspect="0"/></p:cNvPicPr>
          <p:nvPr/>
        </p:nvPicPr>
        <p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
        <p:spPr>
          <a:xfrm><a:off x="0" y="0"/><a:ext cx="{SLIDE_W}" cy="{SLIDE_H}"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
      </p:pic>
    """


def title_block(title: str, subtitle: str | None = None) -> str:
    pars = paragraph(title, 3000, "063A6B", True)
    if subtitle:
        pars += paragraph(subtitle, 1450, "2C5C7B")
    return (
        rect(10, "title accent", 0.62, 0.62, 0.08, 0.58, "00A6D6")
        + text_box(11, "title", 0.76, 0.48, 6.85, 0.95, pars)
    )


def footer(page: int) -> str:
    return text_box(
        90,
        "footer",
        0.78,
        6.95,
        4.3,
        0.25,
        paragraph(f"VectorBody 2.0  |  4-5分钟展示  |  {page:02d}", 820, "4B6D84"),
    )


def bullet_panel(shape_id: int, bullets: list[str], x: float = 0.85, y: float = 1.55, w: float = 6.55, h: float = 4.65) -> str:
    xml = "".join(paragraph(b, 1550, "0B2239", bullet=True) for b in bullets)
    return (
        rect(shape_id, "content panel", x, y, w, h, "FFFFFF", 88000, line="BFE5F2", radius=True)
        + text_box(shape_id + 1, "bullets", x + 0.22, y + 0.22, w - 0.44, h - 0.42, xml)
    )


def metric_card(shape_id: int, x: float, y: float, title: str, body: str, accent: str) -> str:
    pars = paragraph(title, 1420, accent, True, align="ctr") + paragraph(body, 1050, "0B2239", align="ctr")
    return (
        rect(shape_id, "metric card", x, y, 2.15, 1.35, "FFFFFF", 90000, line=accent, radius=True)
        + text_box(shape_id + 1, title, x + 0.08, y + 0.1, 1.99, 1.14, pars, margin=0.03)
    )


SLIDES: list[dict] = [
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


def slide_xml(slide: dict, idx: int) -> str:
    shapes = [background_pic()]
    if slide.get("kind") == "cover":
        shapes.append(rect(20, "cover panel", 0.75, 2.05, 6.85, 3.2, "FFFFFF", 87000, line="9AD8EF", radius=True))
        pars = paragraph(slide["title"], 4400, "063A6B", True)
        pars += paragraph(slide["subtitle"], 1850, "164B73")
        for line_text in slide["lines"]:
            pars += paragraph(line_text, 1350, "1F4256")
        shapes.append(text_box(21, "cover text", 1.0, 2.23, 6.35, 2.82, pars, margin=0.08))
        shapes.append(footer(idx))
    elif slide.get("kind") == "pipeline":
        shapes.append(title_block(slide["title"], slide["subtitle"]))
        y = 3.05
        x0 = 0.78
        box_w = 1.62
        gap = 0.34
        colors = ["0077B6", "0096C7", "00A6D6", "26B99A", "F59E0B", "EF6C35"]
        for s_i, step in enumerate(slide["steps"]):
            x = x0 + s_i * (box_w + gap)
            shapes.append(rect(30 + s_i * 3, "step", x, y, box_w, 0.86, "FFFFFF", 92000, line=colors[s_i], radius=True))
            shapes.append(text_box(31 + s_i * 3, "step text", x + 0.04, y + 0.16, box_w - 0.08, 0.48, paragraph(step, 1100, colors[s_i], True, align="ctr"), margin=0.01))
            if s_i < len(slide["steps"]) - 1:
                shapes.append(line(32 + s_i * 3, x + box_w, y + 0.43, x + box_w + gap - 0.05, y + 0.43))
        shapes.append(
            bullet_panel(
                70,
                [
                    "前端：摄像头/视频导入、骨架可视化、语音提示",
                    "算法：关键点稳定、拓扑树、DLS、虚拟骨长、风险评分",
                    "输出：百分制总分、三维分项、风险部位、训练报告",
                ],
                x=0.95,
                y=4.35,
                w=6.35,
                h=1.65,
            )
        )
        shapes.append(footer(idx))
    elif slide.get("kind") == "score":
        shapes.append(title_block(slide["title"], slide["subtitle"]))
        shapes.append(metric_card(30, 0.88, 2.08, "关节-姿态符合度", "角度 / 对齐 / 范围", "0077B6"))
        shapes.append(metric_card(34, 3.10, 2.08, "拓扑稳定与代偿控制", "骨长 / 时序 / 支撑链", "009688"))
        shapes.append(metric_card(38, 5.32, 2.08, "发力模式代理合理性", "支撑 / 骨盆 / 躯干", "E87500"))
        formula = (
            paragraph("综合评分 = 0.30 × 符合度 + 0.35 × 稳定控制 + 0.35 × 发力代理", 1420, "0B376D", True, align="ctr")
            + paragraph("核心代码：core/compensation_risk_engine.py  →  _score_dimensions()", 1080, "465A69", align="ctr")
        )
        shapes.append(rect(50, "formula panel", 0.9, 4.02, 6.4, 1.2, "FFFFFF", 90000, line="9AD8EF", radius=True))
        shapes.append(text_box(51, "formula", 1.03, 4.23, 6.14, 0.74, formula, margin=0.02))
        shapes.append(footer(idx))
    else:
        shapes.append(title_block(slide["title"], slide["subtitle"]))
        shapes.append(bullet_panel(30, slide["bullets"]))
        shapes.append(footer(idx))

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      {''.join(shapes)}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>
"""


def slide_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/background.jpg"/>
</Relationships>
"""


def presentation_xml(slide_count: int) -> str:
    ids = "\n".join(
        f'    <p:sldId id="{256+i}" r:id="rId{2+i}"/>' for i in range(slide_count)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                saveSubsetFonts="1">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
  <p:sldIdLst>
{ids}
  </p:sldIdLst>
  <p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}" type="wide"/>
  <p:notesSz cx="6858000" cy="9144000"/>
  <p:defaultTextStyle>
    <a:defPPr><a:defRPr lang="zh-CN"/></a:defPPr>
  </p:defaultTextStyle>
</p:presentation>
"""


def presentation_rels(slide_count: int) -> str:
    rels = [
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
    ]
    rels.extend(
        f'<Relationship Id="rId{2+i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i+1}.xml"/>'
        for i in range(slide_count)
    )
    rels.append('<Relationship Id="rId20" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>')
    rels.append('<Relationship Id="rId21" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/presProps" Target="presProps.xml"/>')
    rels.append('<Relationship Id="rId22" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/viewProps" Target="viewProps.xml"/>')
    rels.append('<Relationship Id="rId23" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/tableStyles" Target="tableStyles.xml"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n  '
        + "\n  ".join(rels)
        + "\n</Relationships>\n"
    )


def static_files(slide_count: int) -> dict[str, str]:
    overrides = "\n".join(
        f'  <Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, slide_count + 1)
    )
    return {
        "[Content_Types].xml": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"/>
  <Override PartName="/ppt/viewProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"/>
  <Override PartName="/ppt/tableStyles.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"/>
{overrides}
</Types>
""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
""",
        "docProps/app.xml": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Codex</Application>
  <PresentationFormat>On-screen Show (16:9)</PresentationFormat>
  <Slides>{slide_count}</Slides>
  <Notes>0</Notes>
  <Company>西安电子科技大学</Company>
</Properties>
""",
        "docProps/core.xml": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:dcmitype="http://purl.org/dc/dcmitype/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>VectorBody 2.0 4-5分钟展示PPT</dc:title>
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{datetime.utcnow().isoformat(timespec="seconds")}Z</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{datetime.utcnow().isoformat(timespec="seconds")}Z</dcterms:modified>
</cp:coreProperties>
""",
        "ppt/presentation.xml": presentation_xml(slide_count),
        "ppt/_rels/presentation.xml.rels": presentation_rels(slide_count),
        "ppt/presProps.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentationPr xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>
""",
        "ppt/viewProps.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:viewPr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
          xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>
""",
        "ppt/tableStyles.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>
""",
        "ppt/theme/theme1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="VectorBody">
  <a:themeElements>
    <a:clrScheme name="VectorBody">
      <a:dk1><a:srgbClr val="0B2239"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="063A6B"/></a:dk2><a:lt2><a:srgbClr val="DFF4FB"/></a:lt2>
      <a:accent1><a:srgbClr val="0077B6"/></a:accent1><a:accent2><a:srgbClr val="00A6D6"/></a:accent2>
      <a:accent3><a:srgbClr val="26B99A"/></a:accent3><a:accent4><a:srgbClr val="F59E0B"/></a:accent4>
      <a:accent5><a:srgbClr val="EF6C35"/></a:accent5><a:accent6><a:srgbClr val="6B8CAE"/></a:accent6>
      <a:hlink><a:srgbClr val="0077B6"/></a:hlink><a:folHlink><a:srgbClr val="6B8CAE"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="VectorBody"><a:majorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/></a:majorFont><a:minorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/></a:minorFont></a:fontScheme>
    <a:fmtScheme name="VectorBody"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme>
  </a:themeElements>
  <a:objectDefaults/><a:extraClrSchemeLst/>
</a:theme>
""",
        "ppt/slideMasters/slideMaster1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
  <p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>
</p:sldMaster>
""",
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>
""",
        "ppt/slideLayouts/slideLayout1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             type="blank" preserve="1">
  <p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>
""",
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>
""",
    }


def build_pptx() -> None:
    if not BG_IMAGE.exists():
        raise FileNotFoundError(BG_IMAGE)

    files = static_files(len(SLIDES))
    for i, slide in enumerate(SLIDES, 1):
        files[f"ppt/slides/slide{i}.xml"] = slide_xml(slide, i)
        files[f"ppt/slides/_rels/slide{i}.xml.rels"] = slide_rels()

    tmp = PPTX_PATH.with_suffix(".tmp.pptx")
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data.encode("utf-8"))
        z.write(BG_IMAGE, "ppt/media/background.jpg")

    if PPTX_PATH.exists():
        backup = PPTX_PATH.with_name(PPTX_PATH.stem + "_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".pptx")
        shutil.copy2(PPTX_PATH, backup)
    tmp.replace(PPTX_PATH)
    SCRIPT_PATH.write_text(SCRIPT, encoding="utf-8")


if __name__ == "__main__":
    build_pptx()
    print(PPTX_PATH)
    print(SCRIPT_PATH)
