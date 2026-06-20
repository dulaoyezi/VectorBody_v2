# -*- coding: utf-8 -*-
"""Insert circled-number footnotes into 研电赛4.docx using OOXML."""
from __future__ import annotations

import copy
import re
import shutil
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET


TARGET_DOC = Path(r"C:\小杜\研电赛修改\研电赛4.docx")
REFERENCE_SOURCE_DOC = Path(r"C:\小杜\研电赛修改\研电赛3_润色版.docx")

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
W = f"{{{NS['w']}}}"


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


for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def paragraph_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()


def circled_number(n: int) -> str:
    if 1 <= n <= 20:
        return chr(0x2460 + n - 1)
    if 21 <= n <= 35:
        return chr(0x3251 + n - 21)
    if 36 <= n <= 50:
        return chr(0x32B1 + n - 36)
    return f"({n})"


def load_xml_from_docx(path: Path, member: str) -> ET.Element:
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(member))


def extract_references(source_doc: Path) -> dict[int, str]:
    root = load_xml_from_docx(source_doc, "word/document.xml")
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError("参考文献来源文档缺少 word/document.xml body。")

    refs: dict[int, str] = {}
    for p in body.findall("w:p", NS):
        text = paragraph_text(p)
        match = re.match(r"^\[(\d+)\]\s*(.+)", text)
        if match:
            refs[int(match.group(1))] = match.group(2).strip()

    if len(refs) != 48:
        raise RuntimeError(f"预期读取 48 条参考文献，实际读取 {len(refs)} 条。")
    missing = [n for n in range(1, 49) if n not in refs]
    if missing:
        raise RuntimeError(f"参考文献编号缺失：{missing}")
    return refs


def find_anchor_paragraphs(body: ET.Element) -> dict[str, ET.Element]:
    paragraphs = body.findall("w:p", NS)
    anchors: dict[str, ET.Element] = {}
    for p in paragraphs:
        text = paragraph_text(p)
        for _group, needle in ANCHOR_GROUPS:
            if needle in text and needle not in anchors:
                anchors[needle] = p
    missing = [needle for _group, needle in ANCHOR_GROUPS if needle not in anchors]
    if missing:
        raise RuntimeError("未找到脚注插入锚点：" + "；".join(missing))
    return anchors


def make_reference_run(footnote_id: int, mark: str) -> ET.Element:
    r = ET.Element(W + "r")
    r_pr = ET.SubElement(r, W + "rPr")
    vert = ET.SubElement(r_pr, W + "vertAlign")
    vert.set(W + "val", "superscript")
    sz = ET.SubElement(r_pr, W + "sz")
    sz.set(W + "val", "18")
    sz_cs = ET.SubElement(r_pr, W + "szCs")
    sz_cs.set(W + "val", "18")
    ref = ET.SubElement(r, W + "footnoteReference")
    ref.set(W + "id", str(footnote_id))
    ref.set(W + "customMarkFollows", "1")
    t = ET.SubElement(r, W + "t")
    t.text = mark
    return r


def make_footnote(footnote_id: int, mark: str, text: str) -> ET.Element:
    footnote = ET.Element(W + "footnote")
    footnote.set(W + "id", str(footnote_id))

    p = ET.SubElement(footnote, W + "p")
    p_pr = ET.SubElement(p, W + "pPr")
    spacing = ET.SubElement(p_pr, W + "spacing")
    spacing.set(W + "line", "240")
    spacing.set(W + "lineRule", "auto")

    mark_run = ET.SubElement(p, W + "r")
    mark_pr = ET.SubElement(mark_run, W + "rPr")
    vert = ET.SubElement(mark_pr, W + "vertAlign")
    vert.set(W + "val", "superscript")
    mark_text = ET.SubElement(mark_run, W + "t")
    mark_text.text = mark

    space_run = ET.SubElement(p, W + "r")
    space_text = ET.SubElement(space_run, W + "t")
    space_text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    space_text.text = " "

    text_run = ET.SubElement(p, W + "r")
    text_pr = ET.SubElement(text_run, W + "rPr")
    lang = ET.SubElement(text_pr, W + "lang")
    lang.set(W + "eastAsia", "zh-CN")
    t = ET.SubElement(text_run, W + "t")
    t.text = text
    return footnote


def insert_footnote_runs(body: ET.Element, refs: dict[int, str], start_id: int) -> list[tuple[int, str, str]]:
    anchors = find_anchor_paragraphs(body)
    pending: dict[ET.Element, list[int]] = defaultdict(list)
    for group, needle in ANCHOR_GROUPS:
        para = anchors[needle]
        for number in group:
            pending[para].append(number)

    inserted: list[tuple[int, str, str]] = []
    for para, numbers in pending.items():
        for number in sorted(numbers):
            footnote_id = start_id + number - 1
            mark = circled_number(number)
            para.append(make_reference_run(footnote_id, mark))
            inserted.append((footnote_id, mark, refs[number]))
    return inserted


def remove_reference_heading_if_present(body: ET.Element) -> bool:
    removed = False
    for p in list(body.findall("w:p", NS)):
        text = paragraph_text(p)
        if text == "参考文献" or text.startswith("参考文献\t"):
            body.remove(p)
            removed = True
    return removed


def max_footnote_id(root: ET.Element) -> int:
    values = []
    for fn in root.findall("w:footnote", NS):
        raw = fn.get(W + "id")
        if raw is not None:
            try:
                values.append(int(raw))
            except ValueError:
                pass
    return max([v for v in values if v >= 0], default=0)


def convert() -> None:
    if not TARGET_DOC.exists():
        raise FileNotFoundError(TARGET_DOC)
    if not REFERENCE_SOURCE_DOC.exists():
        raise FileNotFoundError(REFERENCE_SOURCE_DOC)

    refs = extract_references(REFERENCE_SOURCE_DOC)

    backup = TARGET_DOC.with_name(
        "circled_footnote_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + TARGET_DOC.suffix
    )
    shutil.copy2(TARGET_DOC, backup)

    with zipfile.ZipFile(TARGET_DOC, "r") as zin:
        files = {name: zin.read(name) for name in zin.namelist()}

    doc_root = ET.fromstring(files["word/document.xml"])
    body = doc_root.find("w:body", NS)
    if body is None:
        raise RuntimeError("目标文档缺少 body。")
    if doc_root.findall(".//w:footnoteReference", NS):
        raise RuntimeError("目标文档已存在脚注引用，为避免重复插入，本次停止。")

    footnotes_root = ET.fromstring(files["word/footnotes.xml"])
    start_id = max_footnote_id(footnotes_root) + 1

    remove_reference_heading_if_present(body)
    inserted = insert_footnote_runs(body, refs, start_id)
    for footnote_id, mark, text in inserted:
        footnotes_root.append(make_footnote(footnote_id, mark, text))

    files["word/document.xml"] = ET.tostring(doc_root, encoding="utf-8", xml_declaration=True)
    files["word/footnotes.xml"] = ET.tostring(footnotes_root, encoding="utf-8", xml_declaration=True)

    tmp = TARGET_DOC.with_name("circled_footnote_tmp_" + datetime.now().strftime("%Y%m%d_%H%M%S") + TARGET_DOC.suffix)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in files.items():
            zout.writestr(name, data)
    tmp.replace(TARGET_DOC)

    print(f"updated={TARGET_DOC}")
    print(f"backup={backup}")
    print(f"footnotes={len(inserted)}")
    print(f"start_id={start_id}")


if __name__ == "__main__":
    convert()
