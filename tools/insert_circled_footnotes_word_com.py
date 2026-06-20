# -*- coding: utf-8 -*-
"""Insert circled-number footnotes into 研电赛4.docx via Word COM."""
from __future__ import annotations

import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import pythoncom
import win32com.client


TARGET_DOC = Path(r"C:\小杜\研电赛修改\研电赛4.docx")
REFERENCE_SOURCE_DOC = Path(r"C:\小杜\研电赛修改\研电赛3_润色版.docx")
CLEAN_BASE = Path(r"C:\小杜\研电赛修改\circled_footnote_backup_20260620_102808.docx")

WD_COLLAPSE_END = 0

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

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


def paragraph_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()


def extract_references(path: Path) -> dict[int, str]:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError("来源文档缺少 body。")
    refs: dict[int, str] = {}
    for p in body.findall("w:p", NS):
        text = paragraph_text(p)
        match = re.match(r"^\[(\d+)\]\s*(.+)", text)
        if match:
            refs[int(match.group(1))] = match.group(2).strip()
    if len(refs) != 48:
        raise RuntimeError(f"预期读取 48 条参考文献，实际读取 {len(refs)} 条。")
    return refs


def circled_number(n: int) -> str:
    if 1 <= n <= 20:
        return chr(0x2460 + n - 1)
    if 21 <= n <= 35:
        return chr(0x3251 + n - 21)
    if 36 <= n <= 50:
        return chr(0x32B1 + n - 36)
    return f"({n})"


def clean_com_text(text: str) -> str:
    return text.replace("\r", "").replace("\x07", "").strip()


def find_anchor_paragraph_indices(doc) -> dict[str, int]:
    anchors: dict[str, int] = {}
    for i in range(1, doc.Paragraphs.Count + 1):
        text = clean_com_text(doc.Paragraphs(i).Range.Text)
        for _group, needle in ANCHOR_GROUPS:
            if needle in text and needle not in anchors:
                anchors[needle] = i
    missing = [needle for _group, needle in ANCHOR_GROUPS if needle not in anchors]
    if missing:
        raise RuntimeError("未找到脚注插入锚点：" + "；".join(missing))
    return anchors


def add_custom_footnote(doc, paragraph_index: int, mark: str, note_text: str) -> None:
    rng = doc.Paragraphs(paragraph_index).Range.Duplicate
    if rng.End > rng.Start:
        rng.End = rng.End - 1
    rng.Collapse(WD_COLLAPSE_END)
    doc.Footnotes.Add(Range=rng, Reference=mark, Text=note_text)


def main() -> None:
    if not CLEAN_BASE.exists():
        raise FileNotFoundError(CLEAN_BASE)
    refs = extract_references(REFERENCE_SOURCE_DOC)

    damaged_backup = TARGET_DOC.with_name(
        "damaged_ooxml_footnote_attempt_" + datetime.now().strftime("%Y%m%d_%H%M%S") + TARGET_DOC.suffix
    )
    if TARGET_DOC.exists():
        shutil.copy2(TARGET_DOC, damaged_backup)
    shutil.copy2(CLEAN_BASE, TARGET_DOC)

    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = None
    try:
        doc = word.Documents.Open(str(TARGET_DOC))
        if doc.Footnotes.Count:
            raise RuntimeError("目标文档已存在脚注，停止以避免重复插入。")

        anchors = find_anchor_paragraph_indices(doc)
        for group, needle in ANCHOR_GROUPS:
            para_idx = anchors[needle]
            for number in group:
                add_custom_footnote(doc, para_idx, circled_number(number), refs[number])

        doc.Save()
        print(f"updated={TARGET_DOC}")
        print(f"clean_base={CLEAN_BASE}")
        print(f"damaged_backup={damaged_backup}")
        print(f"footnotes={doc.Footnotes.Count}")
    finally:
        if doc is not None:
            doc.Close(False)
        word.Quit()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
