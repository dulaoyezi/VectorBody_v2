# -*- coding: utf-8 -*-
"""Convert the bibliography in 研电赛4.docx into circled-number footnotes."""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

import pythoncom
import win32com.client


DOC_PATH = Path(r"C:\小杜\研电赛修改\研电赛4.docx")

WD_COLLAPSE_END = 0


ANCHOR_GROUPS = [
    (range(1, 6), "现有基于视觉的瑜伽体式评分"),
    (range(6, 11), "本系统先通过 MediaPipe"),
    (range(11, 16), "拓扑约束 DLS 逆运动学用于修正"),
    (range(16, 19), "发力模式视觉代理基于稳定后的拓扑关键点构建"),
    (range(19, 23), "MediaPipe 输出的肩、腕、膝、踝等关键点"),
    (range(23, 27), "以骨盆中心为根节点构建层级人体拓扑结构表达模型"),
    (range(27, 32), "以战士二式为例"),
    (range(32, 36), "在骨盆根人体拓扑树约束下，用阻尼最小二乘逆运动学修正"),
    (range(36, 41), "选取 30 名受试者"),
    (range(41, 45), "计算系统评分与教师评分之间的 Pearson"),
    (range(45, 49), "动作类别适应性验证分析同一三维评分框架"),
]


def clean_text(text: str) -> str:
    return text.replace("\r", "").replace("\x07", "").strip()


def circled_number(n: int) -> str:
    if 1 <= n <= 20:
        return chr(0x2460 + n - 1)
    if 21 <= n <= 35:
        return chr(0x3251 + n - 21)
    if 36 <= n <= 50:
        return chr(0x32B1 + n - 36)
    return f"({n})"


def collect_paragraphs(doc):
    paragraphs = []
    for i in range(1, doc.Paragraphs.Count + 1):
        paragraphs.append((i, clean_text(doc.Paragraphs(i).Range.Text)))
    return paragraphs


def collect_references(paragraphs):
    refs: dict[int, str] = {}
    reference_heading_idx = None
    for idx, text in paragraphs:
        if text == "参考文献":
            reference_heading_idx = idx
        match = re.match(r"^\[(\d+)\]\s*(.+)", text)
        if match:
            refs[int(match.group(1))] = match.group(2).strip()
    if reference_heading_idx is None:
        raise RuntimeError("未找到文末“参考文献”标题。")
    if not refs:
        raise RuntimeError("未读取到形如 [1] 的参考文献条目。")
    missing = [n for n in range(1, max(refs) + 1) if n not in refs]
    if missing:
        raise RuntimeError(f"参考文献编号不连续，缺少：{missing}")
    return refs, reference_heading_idx


def find_anchor_indices(paragraphs):
    anchors: dict[str, int] = {}
    for _idx, text in paragraphs:
        for _group, needle in ANCHOR_GROUPS:
            if needle in text and needle not in anchors:
                anchors[needle] = _idx
    missing = [needle for _group, needle in ANCHOR_GROUPS if needle not in anchors]
    if missing:
        raise RuntimeError("未找到脚注插入锚点：" + "；".join(missing))
    return anchors


def build_reference_to_anchor(anchors):
    ref_to_anchor: dict[int, int] = {}
    for group, needle in ANCHOR_GROUPS:
        for number in group:
            ref_to_anchor[number] = anchors[needle]
    return ref_to_anchor


def add_custom_footnote(doc, paragraph_index: int, mark: str, note_text: str) -> None:
    paragraph = doc.Paragraphs(paragraph_index)
    rng = paragraph.Range.Duplicate
    if rng.End > rng.Start:
        rng.End = rng.End - 1
    rng.Collapse(WD_COLLAPSE_END)
    doc.Footnotes.Add(Range=rng, Reference=mark, Text=note_text)


def delete_reference_section(doc, reference_heading_idx: int) -> None:
    start = doc.Paragraphs(reference_heading_idx).Range.Start
    end = doc.Content.End
    doc.Range(start, end).Delete()


def delete_toc_reference_line(doc) -> bool:
    for i in range(doc.Paragraphs.Count, 0, -1):
        text = clean_text(doc.Paragraphs(i).Range.Text)
        if text.startswith("参考文献"):
            doc.Paragraphs(i).Range.Delete()
            return True
    return False


def convert() -> None:
    if not DOC_PATH.exists():
        raise FileNotFoundError(DOC_PATH)

    backup = DOC_PATH.with_name(
        "ref_to_footnote_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + DOC_PATH.suffix
    )
    shutil.copy2(DOC_PATH, backup)

    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = None
    try:
        doc = word.Documents.Open(str(DOC_PATH))
        paragraphs = collect_paragraphs(doc)
        refs, reference_heading_idx = collect_references(paragraphs)
        anchors = find_anchor_indices(paragraphs)
        ref_to_anchor = build_reference_to_anchor(anchors)

        for number in sorted(refs):
            add_custom_footnote(
                doc,
                ref_to_anchor[number],
                circled_number(number),
                refs[number],
            )

        delete_reference_section(doc, reference_heading_idx)
        delete_toc_reference_line(doc)
        doc.Save()
        print(f"updated={DOC_PATH}")
        print(f"backup={backup}")
        print(f"footnotes={len(refs)}")
    finally:
        if doc is not None:
            doc.Close(False)
        word.Quit()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    convert()
