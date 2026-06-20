# -*- coding: utf-8 -*-
"""
Compensation risk and scoring engine for yoga pose analysis.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from core.human_topology import HumanTopologyTree
from core.topology_ik import TopologyIKStabilizer
from core.virtual_bone_length import VirtualBoneLengthTracker


def zh(text: str) -> str:
    return text.encode("ascii").decode("unicode_escape")


class DriveCategory(str, Enum):
    SHOULDER = "shoulder"
    THORACIC = "thoracic"
    HIP = "hip"


@dataclass(frozen=True)
class MetricRule:
    name: str
    label: str
    category: str
    weight: float
    mode: str
    normal_a: float
    normal_b: float
    beginner_a: float
    beginner_b: float
    geom_gain: float
    stability_weight: float
    note: str


@dataclass(frozen=True)
class PoseCompensationProfile:
    title: str
    primary_drive: DriveCategory
    metrics: Tuple[MetricRule, ...]
    mobile_group_weight: float
    stiff_group_weight: float


def _angle_3pt(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    ba = a - b
    bc = c - b
    denom = (np.linalg.norm(ba) * np.linalg.norm(bc)) + 1e-6
    cos_v = float(np.dot(ba, bc) / denom)
    return float(np.degrees(np.arccos(np.clip(cos_v, -1.0, 1.0))))


def _mid(p: np.ndarray, i: int, j: int) -> np.ndarray:
    return (np.asarray(p[i], dtype=float) + np.asarray(p[j], dtype=float)) / 2.0


def _line_tilt_from_horizontal(a: np.ndarray, b: np.ndarray) -> float:
    v = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    raw = float(np.degrees(np.arctan2(float(v[1]), float(v[0]) + 1e-6)))
    return abs(((raw + 90.0) % 180.0) - 90.0)


def _xy(point: np.ndarray) -> np.ndarray:
    return np.asarray(point, dtype=float)[:2]


class CompensationRiskEngine:
    DRIVE_CN = {
        DriveCategory.SHOULDER: zh(r"\u80a9\u5173\u8282"),
        DriveCategory.THORACIC: zh(r"\u80f8\u690e"),
        DriveCategory.HIP: zh(r"\u9acb\u5173\u8282"),
    }

    WARRIOR1_METRICS = (
        MetricRule(
            name="shoulder_elevation",
            label=zh(r"\u80a9\u5173\u8282\u4e0a\u4e3e"),
            category="mobile",
            weight=0.22,
            mode="range",
            normal_a=150.0,
            normal_b=195.0,
            beginner_a=135.0,
            beginner_b=205.0,
            geom_gain=20.0,
            stability_weight=0.20,
            note=zh(r"\u80a9\u5173\u8282\u4e0a\u4e3e\u4e0d\u8db3\u6216\u8fc7\u5ea6\uff0c\u5bb9\u6613\u501f\u80f8\u690e\u6216\u8170\u690e\u4ee3\u507f\u62ac\u624b\u3002"),
        ),
        MetricRule(
            name="thoracic_lateral_proxy",
            label=zh(r"\u80f8\u690e\u4fa7\u503e"),
            category="mobile",
            weight=0.23,
            mode="upper",
            normal_a=8.0,
            normal_b=0.0,
            beginner_a=11.0,
            beginner_b=0.0,
            geom_gain=10.0,
            stability_weight=0.20,
            note=zh(r"\u80f8\u690e\u6216\u80a9\u7ebf\u4fa7\u503e\u660e\u663e\uff0c\u8bf4\u660e\u8eaf\u5e72\u63a7\u5236\u4e0d\u591f\u5e72\u51c0\u3002"),
        ),
        MetricRule(
            name="cervical_lateral_proxy",
            label=zh(r"\u9888\u690e\u504f\u79fb"),
            category="stiff",
            weight=0.15,
            mode="upper",
            normal_a=3.5,
            normal_b=0.0,
            beginner_a=5.0,
            beginner_b=0.0,
            geom_gain=3.5,
            stability_weight=0.35,
            note=zh(r"\u9888\u690e\u504f\u79fb\u589e\u5927\uff0c\u5bb9\u6613\u7528\u8116\u5b50\u5bfb\u627e\u5e73\u8861\u3002"),
        ),
        MetricRule(
            name="lumbar_lateral_proxy",
            label=zh(r"\u8170\u690e\u4fa7\u504f"),
            category="stiff",
            weight=0.15,
            mode="upper",
            normal_a=6.0,
            normal_b=0.0,
            beginner_a=8.5,
            beginner_b=0.0,
            geom_gain=6.0,
            stability_weight=0.35,
            note=zh(r"\u8170\u690e\u529b\u7ebf\u504f\u79bb\uff0c\u5e38\u89c1\u4e8e\u6838\u5fc3\u5931\u7a33\u540e\u7684\u4fa7\u5f2f\u4ee3\u507f\u3002"),
        ),
        MetricRule(
            name="knee_front_flex",
            label=zh(r"\u524d\u819d\u89d2\u5ea6"),
            category="stiff",
            weight=0.13,
            mode="target",
            normal_a=90.0,
            normal_b=12.0,
            beginner_a=90.0,
            beginner_b=18.0,
            geom_gain=15.0,
            stability_weight=0.40,
            note=zh(r"\u524d\u819d\u89d2\u5ea6\u504f\u79bb\u6216\u6ce2\u52a8\u5927\uff0c\u819d\u5173\u8282\u5bf9\u7ebf\u53ef\u80fd\u5931\u7a33\u3002"),
        ),
        MetricRule(
            name="knee_back_ext",
            label=zh(r"\u540e\u819d\u4f38\u5c55"),
            category="stiff",
            weight=0.12,
            mode="lower",
            normal_a=165.0,
            normal_b=0.0,
            beginner_a=155.0,
            beginner_b=0.0,
            geom_gain=15.0,
            stability_weight=0.35,
            note=zh(r"\u540e\u819d\u5c48\u66f2\u504f\u5927\uff0c\u8bf4\u660e\u9acb\u4f38\u5c55\u4e0d\u8db3\u65f6\u628a\u538b\u529b\u8f6c\u7ed9\u4e86\u819d\u3002"),
        ),
    )

    WARRIOR1_SIDE_METRICS = (
        MetricRule(
            name="knee_front_flex",
            label=zh(r"\u524d\u819d\u5c48\u66f2"),
            category="stiff",
            weight=0.24,
            mode="target",
            normal_a=90.0,
            normal_b=12.0,
            beginner_a=90.0,
            beginner_b=18.0,
            geom_gain=15.0,
            stability_weight=0.40,
            note=zh(r"\u524d\u819d\u5c48\u66f2\u89d2\u5ea6\u504f\u79bb\u6216\u6ce2\u52a8\u5927\uff0c\u8bf7\u8ba9\u524d\u819d\u7a33\u5b9a\u5bf9\u51c6\u524d\u811a\u65b9\u5411\u3002"),
        ),
        MetricRule(
            name="knee_back_ext",
            label=zh(r"\u540e\u819d\u4f38\u5c55"),
            category="stiff",
            weight=0.18,
            mode="lower",
            normal_a=165.0,
            normal_b=0.0,
            beginner_a=155.0,
            beginner_b=0.0,
            geom_gain=15.0,
            stability_weight=0.35,
            note=zh(r"\u540e\u819d\u5c48\u66f2\u504f\u5927\uff0c\u8bf7\u4ece\u540e\u817f\u6839\u90e8\u5411\u540e\u5ef6\u5c55\uff0c\u4f46\u4e0d\u8981\u9501\u6b7b\u819d\u76d6\u3002"),
        ),
        MetricRule(
            name="lumbar_lateral_proxy",
            label=zh(r"\u8eaf\u5e72\u524d\u540e\u503e"),
            category="stiff",
            weight=0.20,
            mode="upper",
            normal_a=8.0,
            normal_b=0.0,
            beginner_a=12.0,
            beginner_b=0.0,
            geom_gain=10.0,
            stability_weight=0.35,
            note=zh(r"\u8eaf\u5e72\u660e\u663e\u524d\u503e\u6216\u540e\u4ef0\uff0c\u8bf7\u6536\u7d27\u6838\u5fc3\uff0c\u4fdd\u6301\u80f8\u8154\u548c\u9aa8\u76c6\u5bf9\u4f4d\u3002"),
        ),
        MetricRule(
            name="cervical_lateral_proxy",
            label=zh(r"\u9888\u690e\u524d\u63a2"),
            category="stiff",
            weight=0.12,
            mode="upper",
            normal_a=4.5,
            normal_b=0.0,
            beginner_a=6.5,
            beginner_b=0.0,
            geom_gain=4.5,
            stability_weight=0.35,
            note=zh(r"\u5934\u9888\u76f8\u5bf9\u8eaf\u5e72\u504f\u79fb\u589e\u5927\uff0c\u8bf7\u653e\u677e\u9888\u90e8\uff0c\u4e0b\u5df4\u5fae\u6536\u3002"),
        ),
        MetricRule(
            name="shoulder_elevation",
            label=zh(r"\u624b\u81c2\u4e0a\u4e3e"),
            category="mobile",
            weight=0.16,
            mode="range",
            normal_a=150.0,
            normal_b=195.0,
            beginner_a=135.0,
            beginner_b=205.0,
            geom_gain=20.0,
            stability_weight=0.25,
            note=zh(r"\u624b\u81c2\u4e0a\u4e3e\u4e0d\u8db3\u6216\u8fc7\u5ea6\uff0c\u8bf7\u5411\u5934\u9876\u4e0a\u65b9\u5ef6\u5c55\uff0c\u4e0d\u8981\u501f\u8170\u540e\u4ef0\u5b8c\u6210\u3002"),
        ),
        MetricRule(
            name="thoracic_lateral_proxy",
            label=zh(r"\u80a9\u9acb\u91cd\u5408\u5ea6"),
            category="mobile",
            weight=0.08,
            mode="upper",
            normal_a=12.0,
            normal_b=0.0,
            beginner_a=16.0,
            beginner_b=0.0,
            geom_gain=12.0,
            stability_weight=0.25,
            note=zh(r"\u4fa7\u4f4d\u89c2\u6d4b\u4e0b\u80a9\u9acb\u6295\u5f71\u504f\u79bb\u660e\u663e\uff0c\u8bf7\u8ba9\u8eab\u4f53\u4fa7\u9762\u66f4\u7a33\u5b9a\u5730\u9762\u5411\u6444\u50cf\u5934\u3002"),
        ),
    )

    WARRIOR2_METRICS = (
        MetricRule(
            name="knee_front_flex",
            label=zh(r"\u524d\u819d\u5c48\u66f2"),
            category="stiff",
            weight=0.22,
            mode="target",
            normal_a=85.0,
            normal_b=10.0,
            beginner_a=75.0,
            beginner_b=18.0,
            geom_gain=15.0,
            stability_weight=0.40,
            note=zh(r"\u524d\u819d\u89d2\u5ea6\u6216\u7a33\u5b9a\u6027\u4e0d\u8db3\uff0c\u8bf7\u8ba9\u819d\u76d6\u5bf9\u51c6\u7b2c\u4e8c\u3001\u7b2c\u4e09\u811a\u8dbe\u3002"),
        ),
        MetricRule(
            name="pelvis_tilt_proxy",
            label=zh(r"\u9aa8\u76c6\u4e2d\u6b63"),
            category="stiff",
            weight=0.16,
            mode="upper",
            normal_a=4.0,
            normal_b=0.0,
            beginner_a=6.0,
            beginner_b=0.0,
            geom_gain=6.0,
            stability_weight=0.35,
            note=zh(r"\u9aa8\u76c6\u51fa\u73b0\u503e\u659c\uff0c\u8bf7\u6536\u7d27\u6838\u5fc3\uff0c\u8ba9\u9aa8\u76c6\u4fdd\u6301\u6b63\u4e2d\u3002"),
        ),
        MetricRule(
            name="lumbar_lateral_proxy",
            label=zh(r"\u8170\u690e\u4e2d\u7acb"),
            category="stiff",
            weight=0.15,
            mode="upper",
            normal_a=5.0,
            normal_b=0.0,
            beginner_a=8.0,
            beginner_b=0.0,
            geom_gain=6.0,
            stability_weight=0.35,
            note=zh(r"\u8170\u690e\u529b\u7ebf\u504f\u79bb\uff0c\u8bf7\u808b\u9aa8\u56de\u6536\uff0c\u907f\u514d\u584c\u8170\u6216\u4fa7\u5f2f\u4ee3\u507f\u3002"),
        ),
        MetricRule(
            name="knee_back_ext",
            label=zh(r"\u540e\u819d\u4f38\u5c55"),
            category="stiff",
            weight=0.12,
            mode="lower",
            normal_a=165.0,
            normal_b=0.0,
            beginner_a=155.0,
            beginner_b=0.0,
            geom_gain=15.0,
            stability_weight=0.35,
            note=zh(r"\u540e\u819d\u5c48\u66f2\u504f\u5927\uff0c\u8bf7\u8ba9\u540e\u817f\u6839\u57fa\u66f4\u7a33\u5b9a\uff0c\u4f46\u4e0d\u8981\u9501\u6b7b\u819d\u76d6\u3002"),
        ),
        MetricRule(
            name="shoulder_horizontal_proxy",
            label=zh(r"\u53cc\u81c2\u6c34\u5e73\u5ef6\u5c55"),
            category="mobile",
            weight=0.12,
            mode="upper",
            normal_a=8.0,
            normal_b=0.0,
            beginner_a=12.0,
            beginner_b=0.0,
            geom_gain=12.0,
            stability_weight=0.25,
            note=zh(r"\u53cc\u81c2\u672a\u4fdd\u6301\u6c34\u5e73\u5ef6\u5c55\uff0c\u8bf7\u80a9\u8180\u4e0b\u6c89\uff0c\u6307\u5c16\u5411\u4e24\u4fa7\u5ef6\u4f38\u3002"),
        ),
        MetricRule(
            name="thoracic_lateral_proxy",
            label=zh(r"\u80f8\u690e\u6b63\u76f4"),
            category="mobile",
            weight=0.10,
            mode="upper",
            normal_a=8.0,
            normal_b=0.0,
            beginner_a=11.0,
            beginner_b=0.0,
            geom_gain=10.0,
            stability_weight=0.25,
            note=zh(r"\u80f8\u690e\u6216\u80a9\u7ebf\u4fa7\u503e\u660e\u663e\uff0c\u8bf7\u4fdd\u6301\u80f8\u8154\u5c55\u5f00\u548c\u8eaf\u5e72\u6b63\u76f4\u3002"),
        ),
        MetricRule(
            name="cervical_lateral_proxy",
            label=zh(r"\u9888\u690e\u653e\u677e"),
            category="stiff",
            weight=0.08,
            mode="upper",
            normal_a=3.5,
            normal_b=0.0,
            beginner_a=5.0,
            beginner_b=0.0,
            geom_gain=3.5,
            stability_weight=0.35,
            note=zh(r"\u9888\u690e\u504f\u79fb\u589e\u5927\uff0c\u8bf7\u653e\u677e\u9888\u90e8\uff0c\u89c6\u7ebf\u81ea\u7136\u770b\u5411\u524d\u65b9\u3002"),
        ),
        MetricRule(
            name="front_hip_opening_proxy",
            label=zh(r"\u524d\u4fa7\u9acb\u6253\u5f00"),
            category="mobile",
            weight=0.15,
            mode="range",
            normal_a=35.0,
            normal_b=70.0,
            beginner_a=25.0,
            beginner_b=75.0,
            geom_gain=15.0,
            stability_weight=0.25,
            note=zh(r"\u9acb\u90e8\u6253\u5f00\u4e0d\u8db3\u53ef\u4ee5\u964d\u4f4e\u91cd\u5fc3\u5e45\u5ea6\uff0c\u4f46\u4e0d\u8981\u7528\u819d\u5185\u6263\u6216\u8170\u690e\u584c\u9677\u4ee3\u507f\u3002"),
        ),
    )

    WARRIOR2_SIDE_METRICS = (
        MetricRule(
            name="knee_front_flex",
            label=zh(r"\u524d\u819d\u5c48\u66f2"),
            category="stiff",
            weight=0.26,
            mode="target",
            normal_a=85.0,
            normal_b=10.0,
            beginner_a=75.0,
            beginner_b=18.0,
            geom_gain=15.0,
            stability_weight=0.40,
            note=zh(r"\u524d\u819d\u5c48\u66f2\u89d2\u5ea6\u6216\u7a33\u5b9a\u6027\u4e0d\u8db3\uff0c\u4fa7\u4f4d\u4e0b\u8bf7\u907f\u514d\u819d\u76d6\u660e\u663e\u5411\u524d\u51b2\u3002"),
        ),
        MetricRule(
            name="knee_back_ext",
            label=zh(r"\u540e\u819d\u4f38\u5c55"),
            category="stiff",
            weight=0.16,
            mode="lower",
            normal_a=165.0,
            normal_b=0.0,
            beginner_a=155.0,
            beginner_b=0.0,
            geom_gain=15.0,
            stability_weight=0.35,
            note=zh(r"\u540e\u819d\u5c48\u66f2\u504f\u5927\uff0c\u8bf7\u8ba9\u540e\u817f\u6839\u57fa\u66f4\u7a33\uff0c\u4f46\u4e0d\u8981\u9501\u6b7b\u819d\u76d6\u3002"),
        ),
        MetricRule(
            name="lumbar_lateral_proxy",
            label=zh(r"\u8eaf\u5e72\u524d\u540e\u503e"),
            category="stiff",
            weight=0.22,
            mode="upper",
            normal_a=7.0,
            normal_b=0.0,
            beginner_a=10.0,
            beginner_b=0.0,
            geom_gain=10.0,
            stability_weight=0.35,
            note=zh(r"\u8eaf\u5e72\u660e\u663e\u524d\u503e\u6216\u540e\u4ef0\uff0c\u8bf7\u8ba9\u80a9\u9acb\u4fdd\u6301\u5782\u76f4\u5bf9\u4f4d\u3002"),
        ),
        MetricRule(
            name="cervical_lateral_proxy",
            label=zh(r"\u9888\u690e\u524d\u63a2"),
            category="stiff",
            weight=0.14,
            mode="upper",
            normal_a=4.5,
            normal_b=0.0,
            beginner_a=6.5,
            beginner_b=0.0,
            geom_gain=4.5,
            stability_weight=0.35,
            note=zh(r"\u5934\u9888\u76f8\u5bf9\u8eaf\u5e72\u504f\u79fb\u589e\u5927\uff0c\u8bf7\u653e\u677e\u9888\u90e8\uff0c\u907f\u514d\u524d\u63a2\u6216\u4ef0\u5934\u3002"),
        ),
        MetricRule(
            name="shoulder_horizontal_proxy",
            label=zh(r"\u53cc\u81c2\u6c34\u5e73"),
            category="mobile",
            weight=0.10,
            mode="upper",
            normal_a=10.0,
            normal_b=0.0,
            beginner_a=15.0,
            beginner_b=0.0,
            geom_gain=12.0,
            stability_weight=0.25,
            note=zh(r"\u53cc\u81c2\u672a\u7a33\u5b9a\u4fdd\u6301\u6c34\u5e73\uff0c\u8bf7\u80a9\u8180\u4e0b\u6c89\uff0c\u624b\u81c2\u5411\u4e24\u7aef\u5ef6\u5c55\u3002"),
        ),
        MetricRule(
            name="thoracic_lateral_proxy",
            label=zh(r"\u80a9\u9acb\u6295\u5f71\u7a33\u5b9a"),
            category="mobile",
            weight=0.12,
            mode="upper",
            normal_a=12.0,
            normal_b=0.0,
            beginner_a=16.0,
            beginner_b=0.0,
            geom_gain=12.0,
            stability_weight=0.25,
            note=zh(r"\u4fa7\u4f4d\u89c2\u6d4b\u4e0b\u80a9\u9acb\u6295\u5f71\u504f\u79bb\u660e\u663e\uff0c\u8bf7\u8ba9\u8eab\u4f53\u4fa7\u9762\u66f4\u7a33\u5b9a\u5730\u9762\u5411\u6444\u50cf\u5934\u3002"),
        ),
    )

    TADASANA_FRONT_METRICS = (
        MetricRule("spine_vertical", zh(r"\u8eaf\u5e72\u5782\u76f4"), "stiff", 0.35, "upper", 5.0, 0.0, 8.0, 0.0, 6.0, 0.40, zh(r"\u8eaf\u5e72\u504f\u79bb\u5782\u76f4\u8f74")),
        MetricRule("shoulder_symmetry", zh(r"\u80a9\u5bf9\u79f0"), "stiff", 0.30, "upper", 6.0, 0.0, 10.0, 0.0, 6.0, 0.35, zh(r"\u80a9\u9aa8\u76c6\u4e0d\u5bf9\u79f0")),
        MetricRule("pelvis_level", zh(r"\u9aa8\u76c6\u6c34\u5e73"), "stiff", 0.20, "upper", 4.0, 0.0, 7.0, 0.0, 5.0, 0.35, zh(r"\u9aa8\u76c6\u504f\u659c")),
        MetricRule("neck_axis", zh(r"\u9888\u8f74\u5bf9\u9f50"), "mobile", 0.15, "upper", 3.0, 0.0, 5.0, 0.0, 3.0, 0.30, zh(r"\u5934\u9888\u504f\u79fb")),
    )

    TADASANA_SIDE_METRICS = (
        MetricRule("spine_line", zh(r"\u810a\u67f1\u7ebf"), "stiff", 0.40, "upper", 5.0, 0.0, 8.0, 0.0, 6.0, 0.40, zh(r"\u80cc\u90e8\u524d\u540e\u5f2f\u66f2")),
        MetricRule("pelvis_tilt", zh(r"\u9aa8\u76c6\u503e\u659c"), "stiff", 0.30, "upper", 4.0, 0.0, 7.0, 0.0, 5.0, 0.35, zh(r"\u9aa8\u76c6\u524d\u540e\u504f\u79fb")),
        MetricRule("knee_lock", zh(r"\u819d\u5173\u8282"), "stiff", 0.20, "lower", 165.0, 0.0, 155.0, 0.0, 10.0, 0.35, zh(r"\u8fc7\u5ea6\u9501\u6b7b")),
        MetricRule("weight_center", zh(r"\u91cd\u5fc3"), "mobile", 0.10, "upper", 5.0, 0.0, 8.0, 0.0, 6.0, 0.30, zh(r"\u91cd\u5fc3\u524d\u540e\u504f\u79fb")),
    )

    SUKHASANA_FRONT_METRICS = (
        MetricRule("pelvis_balance", zh(r"\u9aa8\u76c6\u5bf9\u79f0"), "stiff", 0.35, "upper", 5.0, 0.0, 8.0, 0.0, 6.0, 0.40, zh(r"\u9aa8\u76c6\u4e0d\u5e73")),
        MetricRule("knee_symmetry", zh(r"\u819d\u5bf9\u79f0"), "stiff", 0.30, "upper", 6.0, 0.0, 10.0, 0.0, 6.0, 0.35, zh(r"\u53cc\u819d\u9ad8\u5ea6\u4e0d\u4e00")),
        MetricRule("spine_upright", zh(r"\u810a\u67f1\u4f38\u5c55"), "stiff", 0.25, "upper", 6.0, 0.0, 10.0, 0.0, 7.0, 0.35, zh(r"\u810a\u67f1\u584c\u9677\u6216\u540e\u503e")),
        MetricRule("shoulder_relax", zh(r"\u80a9\u653e\u677e"), "mobile", 0.10, "upper", 8.0, 0.0, 12.0, 0.0, 6.0, 0.30, zh(r"\u80a9\u8180\u4e0a\u63d0")),
    )

    SUKHASANA_SIDE_METRICS = (
        MetricRule("spine_curve", zh(r"\u810a\u67f1\u5f2f\u66f2"), "stiff", 0.40, "upper", 5.0, 0.0, 8.0, 0.0, 6.0, 0.40, zh(r"\u80cc\u90e8\u5f2f\u66f2")),
        MetricRule("pelvis_forward_back", zh(r"\u9aa8\u76c6\u524d\u540e"), "stiff", 0.30, "upper", 5.0, 0.0, 8.0, 0.0, 6.0, 0.35, zh(r"\u5750\u9aa8\u504f\u79fb")),
        MetricRule("head_forward", zh(r"\u5934\u524d\u4f38"), "mobile", 0.20, "upper", 3.0, 0.0, 5.0, 0.0, 4.0, 0.30, zh(r"\u9888\u90e8\u4ee3\u507f")),
        MetricRule("knee_stack", zh(r"\u819d\u5bf9\u53e0"), "stiff", 0.10, "upper", 6.0, 0.0, 10.0, 0.0, 6.0, 0.35, zh(r"\u53cc\u819d\u4e0d\u5bf9\u79f0")),
    )

    UTTANASANA_FRONT_METRICS = (
        MetricRule("hip_hinge", zh(r"\u9acb\u94f0"), "stiff", 0.40, "target", 90.0, 10.0, 95.0, 15.0, 15.0, 0.40, zh(r"\u8170\u690e\u4ee3\u507f")),
        MetricRule("spine_line", zh(r"\u810a\u67f1\u7ebf"), "stiff", 0.30, "upper", 8.0, 0.0, 12.0, 0.0, 8.0, 0.35, zh(r"\u80cc\u90e8\u5708\u80cc")),
        MetricRule("knee_control", zh(r"\u819d\u63a7\u5236"), "stiff", 0.20, "lower", 170.0, 0.0, 160.0, 0.0, 10.0, 0.35, zh(r"\u8fc7\u4f38\u6216\u5f39\u6027\u4e0d\u8db3")),
        MetricRule("balance", zh(r"\u91cd\u5fc3"), "mobile", 0.10, "upper", 6.0, 0.0, 10.0, 0.0, 6.0, 0.30, zh(r"\u524d\u540e\u5931\u8861")),
    )

    UTTANASANA_SIDE_METRICS = (
        MetricRule("hip_depth", zh(r"\u9acb\u6df1\u5ea6"), "stiff", 0.40, "target", 90.0, 10.0, 95.0, 15.0, 15.0, 0.40, zh(r"\u9acb\u6298\u53e0\u89d2\u5ea6\u4e0d\u51c6")),
        MetricRule("spine_round", zh(r"\u810a\u67f1\u5f2f"), "stiff", 0.30, "upper", 8.0, 0.0, 12.0, 0.0, 8.0, 0.35, zh(r"\u80cc\u90e8\u5708\u80cc")),
        MetricRule("knee_lock", zh(r"\u819d\u9501\u6b7b"), "stiff", 0.20, "lower", 170.0, 0.0, 160.0, 0.0, 10.0, 0.35, zh(r"\u8fc7\u5ea6\u4f38\u819d")),
        MetricRule("weight_shift", zh(r"\u91cd\u5fc3\u504f\u79fb"), "mobile", 0.10, "upper", 6.0, 0.0, 10.0, 0.0, 6.0, 0.30, zh(r"\u5931\u8861")),
    )

    COBRA_FRONT_METRICS = (
        MetricRule("spine_extension", zh(r"\u80f8\u690e\u4f38\u5c55"), "mobile", 0.45, "upper", 25.0, 0.0, 20.0, 0.0, 12.0, 0.40, zh(r"\u8170\u690e\u4ee3\u507f")),
        MetricRule("shoulder_level", zh(r"\u80a9\u5bf9\u79f0"), "stiff", 0.25, "upper", 8.0, 0.0, 12.0, 0.0, 6.0, 0.35, zh(r"\u80a9\u8180\u4e0d\u5bf9\u79f0")),
        MetricRule("pelvis_contact", zh(r"\u9aa8\u76c6\u63a7\u5236"), "stiff", 0.20, "upper", 6.0, 0.0, 10.0, 0.0, 6.0, 0.35, zh(r"\u8170\u690e\u4ee3\u507f")),
        MetricRule("neck_extend", zh(r"\u9888\u4f38\u5c55"), "mobile", 0.10, "upper", 4.0, 0.0, 6.0, 0.0, 4.0, 0.30, zh(r"\u9888\u90e8\u538b\u529b")),
    )

    COBRA_SIDE_METRICS = (
        MetricRule("spine_arc", zh(r"\u810a\u67f1\u5f27\u5ea6"), "mobile", 0.45, "upper", 25.0, 0.0, 20.0, 0.0, 12.0, 0.40, zh(r"\u8fc7\u5ea6\u540e\u4ef0")),
        MetricRule("hip_stability", zh(r"\u9aa8\u76c6\u7a33\u5b9a"), "stiff", 0.25, "upper", 6.0, 0.0, 10.0, 0.0, 6.0, 0.35, zh(r"\u9aa8\u76c6\u6e38\u79fb")),
        MetricRule("shoulder_load", zh(r"\u80a9\u8f7d"), "mobile", 0.20, "upper", 8.0, 0.0, 12.0, 0.0, 6.0, 0.30, zh(r"\u80a9\u538b\u529b")),
        MetricRule("neck_comp", zh(r"\u9888\u4ee3\u507f"), "mobile", 0.10, "upper", 4.0, 0.0, 6.0, 0.0, 4.0, 0.30, zh(r"\u9888\u4ee3\u507f")),
    )

    BALANCE_FRONT_METRICS = (
        MetricRule("vertical_axis", zh(r"\u5782\u76f4\u8f74"), "stiff", 0.45, "upper", 4.0, 0.0, 7.0, 0.0, 6.0, 0.40, zh(r"\u8f74\u504f\u79fb")),
        MetricRule("ankle_control", zh(r"\u8e1d\u7a33\u5b9a"), "stiff", 0.30, "upper", 6.0, 0.0, 10.0, 0.0, 6.0, 0.35, zh(r"\u652f\u6491\u4e0d\u7a33")),
        MetricRule("core_balance", zh(r"\u6838\u5fc3"), "stiff", 0.25, "upper", 6.0, 0.0, 9.0, 0.0, 6.0, 0.35, zh(r"\u6838\u5fc3\u5931\u63a7")),
    )

    BALANCE_SIDE_METRICS = (
        MetricRule("tilt_forward_back", zh(r"\u524d\u540e\u503e"), "stiff", 0.45, "upper", 4.0, 0.0, 7.0, 0.0, 6.0, 0.40, zh(r"\u524d\u540e\u504f\u79fb")),
        MetricRule("hip_stack", zh(r"\u9aa8\u76c6\u53e0\u52a0"), "stiff", 0.30, "upper", 6.0, 0.0, 10.0, 0.0, 6.0, 0.35, zh(r"\u5931\u8861")),
        MetricRule("neck_comp", zh(r"\u9888\u4ee3\u507f"), "mobile", 0.25, "upper", 4.0, 0.0, 6.0, 0.0, 4.0, 0.30, zh(r"\u9888\u4ee3\u507f")),
    )

    DOWNWARD_FRONT_METRICS = (
        MetricRule("hip_angle", zh(r"\u9acb\u89d2"), "stiff", 0.40, "target", 60.0, 10.0, 65.0, 15.0, 12.0, 0.40, zh(r"\u9acb\u9ad8\u4e0d\u51c6")),
        MetricRule("spine_line", zh(r"\u810a\u67f1"), "stiff", 0.30, "upper", 8.0, 0.0, 12.0, 0.0, 8.0, 0.40, zh(r"\u80cc\u5f2f\u66f2")),
        MetricRule("shoulder_load", zh(r"\u80a9\u8f7d"), "mobile", 0.20, "upper", 8.0, 0.0, 12.0, 0.0, 6.0, 0.30, zh(r"\u80a9\u4e0d\u5747")),
        MetricRule("heel_contact", zh(r"\u811a\u8ddf"), "stiff", 0.10, "lower", 0.0, 0.0, 5.0, 0.0, 6.0, 0.35, zh(r"\u811a\u8ddf\u672a\u63a5")),
    )

    DOWNWARD_SIDE_METRICS = (
        MetricRule("hip_height", zh(r"\u9acb\u9ad8\u5ea6"), "stiff", 0.40, "target", 60.0, 10.0, 65.0, 15.0, 12.0, 0.40, zh(r"\u9acb\u4f4d\u9519\u8bef")),
        MetricRule("spine_arc", zh(r"\u810a\u67f1\u5f27"), "stiff", 0.30, "upper", 8.0, 0.0, 12.0, 0.0, 8.0, 0.40, zh(r"\u80cc\u8fc7\u5ea6")),
        MetricRule("shoulder_support", zh(r"\u80a9\u652f\u6491"), "mobile", 0.20, "upper", 8.0, 0.0, 12.0, 0.0, 6.0, 0.30, zh(r"\u652f\u6491\u4e0d\u5747")),
        MetricRule("heel_extend", zh(r"\u811a\u8ddf\u62c9\u4f38"), "stiff", 0.10, "lower", 0.0, 0.0, 5.0, 0.0, 6.0, 0.35, zh(r"\u811a\u8ddf\u4e0d\u5f00")),
    )

    POSE_PROFILES: Dict[str, PoseCompensationProfile] = {
        "warrior1": PoseCompensationProfile(
            title=zh(r"\u6218\u58eb\u4e00\u5f0f"),
            primary_drive=DriveCategory.HIP,
            metrics=WARRIOR1_METRICS,
            mobile_group_weight=0.45,
            stiff_group_weight=0.55,
        ),
        "warrior1_front": PoseCompensationProfile(
            title=zh(r"\u6218\u58eb\u4e00\u5f0f-\u6b63\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=WARRIOR1_METRICS,
            mobile_group_weight=0.45,
            stiff_group_weight=0.55,
        ),
        "warrior1_side": PoseCompensationProfile(
            title=zh(r"\u6218\u58eb\u4e00\u5f0f-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=WARRIOR1_SIDE_METRICS,
            mobile_group_weight=0.30,
            stiff_group_weight=0.70,
        ),
        "virabhadrasana_1": PoseCompensationProfile(
            title=zh(r"\u6218\u58eb\u4e00\u5f0f"),
            primary_drive=DriveCategory.HIP,
            metrics=WARRIOR1_METRICS,
            mobile_group_weight=0.45,
            stiff_group_weight=0.55,
        ),
        "warrior2": PoseCompensationProfile(
            title=zh(r"\u6218\u58eb\u4e8c\u5f0f"),
            primary_drive=DriveCategory.HIP,
            metrics=WARRIOR2_METRICS,
            mobile_group_weight=0.35,
            stiff_group_weight=0.65,
        ),
        "warrior2_front": PoseCompensationProfile(
            title=zh(r"\u6218\u58eb\u4e8c\u5f0f-\u6b63\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=WARRIOR2_METRICS,
            mobile_group_weight=0.35,
            stiff_group_weight=0.65,
        ),
        "warrior2_side": PoseCompensationProfile(
            title=zh(r"\u6218\u58eb\u4e8c\u5f0f-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=WARRIOR2_SIDE_METRICS,
            mobile_group_weight=0.25,
            stiff_group_weight=0.75,
        ),
        "virabhadrasana_2": PoseCompensationProfile(
            title=zh(r"\u6218\u58eb\u4e8c\u5f0f"),
            primary_drive=DriveCategory.HIP,
            metrics=WARRIOR2_METRICS,
            mobile_group_weight=0.35,
            stiff_group_weight=0.65,
        ),
        "tadasana": PoseCompensationProfile(
            title=zh(r"\u5c71\u5f0f"),
            primary_drive=DriveCategory.THORACIC,
            metrics=TADASANA_FRONT_METRICS,
            mobile_group_weight=0.15,
            stiff_group_weight=0.85,
        ),
        "tadasana_front": PoseCompensationProfile(
            title=zh(r"\u5c71\u5f0f-\u6b63\u4f4d"),
            primary_drive=DriveCategory.THORACIC,
            metrics=TADASANA_FRONT_METRICS,
            mobile_group_weight=0.15,
            stiff_group_weight=0.85,
        ),
        "tadasana_side": PoseCompensationProfile(
            title=zh(r"\u5c71\u5f0f-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.THORACIC,
            metrics=TADASANA_SIDE_METRICS,
            mobile_group_weight=0.10,
            stiff_group_weight=0.90,
        ),
        "sukhasana": PoseCompensationProfile(
            title=zh(r"\u7b80\u6613\u5750"),
            primary_drive=DriveCategory.HIP,
            metrics=SUKHASANA_FRONT_METRICS,
            mobile_group_weight=0.10,
            stiff_group_weight=0.90,
        ),
        "sukhasana_front": PoseCompensationProfile(
            title=zh(r"\u7b80\u6613\u5750-\u6b63\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=SUKHASANA_FRONT_METRICS,
            mobile_group_weight=0.10,
            stiff_group_weight=0.90,
        ),
        "sukhasana_side": PoseCompensationProfile(
            title=zh(r"\u7b80\u6613\u5750-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=SUKHASANA_SIDE_METRICS,
            mobile_group_weight=0.20,
            stiff_group_weight=0.80,
        ),
        "uttanasana": PoseCompensationProfile(
            title=zh(r"\u7ad9\u7acb\u524d\u5c48\u5f0f"),
            primary_drive=DriveCategory.HIP,
            metrics=UTTANASANA_FRONT_METRICS,
            mobile_group_weight=0.10,
            stiff_group_weight=0.90,
        ),
        "uttanasana_front": PoseCompensationProfile(
            title=zh(r"\u7ad9\u7acb\u524d\u5c48\u5f0f-\u6b63\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=UTTANASANA_FRONT_METRICS,
            mobile_group_weight=0.10,
            stiff_group_weight=0.90,
        ),
        "uttanasana_side": PoseCompensationProfile(
            title=zh(r"\u7ad9\u7acb\u524d\u5c48\u5f0f-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=UTTANASANA_SIDE_METRICS,
            mobile_group_weight=0.10,
            stiff_group_weight=0.90,
        ),
        "cobra": PoseCompensationProfile(
            title=zh(r"\u773c\u955c\u86c7\u5f0f"),
            primary_drive=DriveCategory.THORACIC,
            metrics=COBRA_FRONT_METRICS,
            mobile_group_weight=0.55,
            stiff_group_weight=0.45,
        ),
        "cobra_front": PoseCompensationProfile(
            title=zh(r"\u773c\u955c\u86c7\u5f0f-\u6b63\u4f4d"),
            primary_drive=DriveCategory.THORACIC,
            metrics=COBRA_FRONT_METRICS,
            mobile_group_weight=0.55,
            stiff_group_weight=0.45,
        ),
        "cobra_side": PoseCompensationProfile(
            title=zh(r"\u773c\u955c\u86c7\u5f0f-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.THORACIC,
            metrics=COBRA_SIDE_METRICS,
            mobile_group_weight=0.75,
            stiff_group_weight=0.25,
        ),
        "bhujangasana": PoseCompensationProfile(
            title=zh(r"\u773c\u955c\u86c7\u5f0f"),
            primary_drive=DriveCategory.THORACIC,
            metrics=COBRA_FRONT_METRICS,
            mobile_group_weight=0.55,
            stiff_group_weight=0.45,
        ),
        "bhujangasana_front": PoseCompensationProfile(
            title=zh(r"\u773c\u955c\u86c7\u5f0f-\u6b63\u4f4d"),
            primary_drive=DriveCategory.THORACIC,
            metrics=COBRA_FRONT_METRICS,
            mobile_group_weight=0.55,
            stiff_group_weight=0.45,
        ),
        "bhujangasana_side": PoseCompensationProfile(
            title=zh(r"\u773c\u955c\u86c7\u5f0f-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.THORACIC,
            metrics=COBRA_SIDE_METRICS,
            mobile_group_weight=0.75,
            stiff_group_weight=0.25,
        ),
        "balance": PoseCompensationProfile(
            title=zh(r"\u5e73\u8861\u5f0f"),
            primary_drive=DriveCategory.HIP,
            metrics=BALANCE_FRONT_METRICS,
            mobile_group_weight=0.0,
            stiff_group_weight=1.0,
        ),
        "balance_front": PoseCompensationProfile(
            title=zh(r"\u5e73\u8861\u5f0f-\u6b63\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=BALANCE_FRONT_METRICS,
            mobile_group_weight=0.0,
            stiff_group_weight=1.0,
        ),
        "balance_side": PoseCompensationProfile(
            title=zh(r"\u5e73\u8861\u5f0f-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=BALANCE_SIDE_METRICS,
            mobile_group_weight=0.25,
            stiff_group_weight=0.75,
        ),
        "downward": PoseCompensationProfile(
            title=zh(r"\u4e0b\u72ac\u5f0f"),
            primary_drive=DriveCategory.HIP,
            metrics=DOWNWARD_FRONT_METRICS,
            mobile_group_weight=0.20,
            stiff_group_weight=0.80,
        ),
        "downward_front": PoseCompensationProfile(
            title=zh(r"\u4e0b\u72ac\u5f0f-\u6b63\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=DOWNWARD_FRONT_METRICS,
            mobile_group_weight=0.20,
            stiff_group_weight=0.80,
        ),
        "downward_side": PoseCompensationProfile(
            title=zh(r"\u4e0b\u72ac\u5f0f-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=DOWNWARD_SIDE_METRICS,
            mobile_group_weight=0.20,
            stiff_group_weight=0.80,
        ),
        "downward_dog": PoseCompensationProfile(
            title=zh(r"\u4e0b\u72ac\u5f0f"),
            primary_drive=DriveCategory.HIP,
            metrics=DOWNWARD_FRONT_METRICS,
            mobile_group_weight=0.20,
            stiff_group_weight=0.80,
        ),
        "downward_dog_front": PoseCompensationProfile(
            title=zh(r"\u4e0b\u72ac\u5f0f-\u6b63\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=DOWNWARD_FRONT_METRICS,
            mobile_group_weight=0.20,
            stiff_group_weight=0.80,
        ),
        "downward_dog_side": PoseCompensationProfile(
            title=zh(r"\u4e0b\u72ac\u5f0f-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.HIP,
            metrics=DOWNWARD_SIDE_METRICS,
            mobile_group_weight=0.20,
            stiff_group_weight=0.80,
        ),
    }

    def __init__(self, history_len: int = 12, level: str = "normal"):
        self.history_len = max(3, int(history_len))
        self.level = level if level in ("normal", "beginner") else "normal"
        self._hist: Dict[str, Deque[float]] = {}
        self._hold_points: Deque[np.ndarray] = deque(maxlen=max(8, self.history_len))
        self._hold_motion: Deque[float] = deque(maxlen=8)
        self.bone_length_tracker = VirtualBoneLengthTracker(
            window_frames=30,
            update_interval=5,
            deviation_threshold=0.30,
        )
        self.ik_stabilizer = TopologyIKStabilizer()

    def reset(self) -> None:
        self._hist.clear()
        self._hold_points.clear()
        self._hold_motion.clear()
        self.bone_length_tracker.reset()
        self.ik_stabilizer.reset()

    def _thr_pair(self, rule: MetricRule) -> Tuple[float, float]:
        if self.level == "beginner":
            return rule.beginner_a, rule.beginner_b
        return rule.normal_a, rule.normal_b

    def _push_hist(self, name: str, value: float) -> None:
        if name not in self._hist:
            self._hist[name] = deque(maxlen=self.history_len)
        self._hist[name].append(float(value))

    def _stability(self, name: str) -> float:
        h = self._hist.get(name)
        if not h or len(h) < 3:
            return 1.0
        arr = np.asarray(h, dtype=float)
        ref = 6.0 if self.level == "normal" else 8.0
        return float(np.clip(1.0 - float(np.std(arr)) / ref, 0.0, 1.0))

    def _update_hold_motion(self, pts: np.ndarray) -> float:
        key_idx = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
        xy_points = np.asarray(pts[key_idx, :2], dtype=float)
        body_height = float(np.ptp(np.asarray(pts[:, 1], dtype=float))) + 1e-6
        if not self._hold_points:
            motion_ratio = 1.0
        else:
            previous = self._hold_points[-1]
            motion_ratio = float(np.mean(np.linalg.norm(xy_points - previous, axis=1)) / body_height)
        self._hold_points.append(xy_points)
        self._hold_motion.append(motion_ratio)
        return motion_ratio

    def _hold_phase_detail(
        self,
        profile: PoseCompensationProfile,
        pts: np.ndarray,
        score: float,
        metric_scores: Dict[str, Dict[str, float]],
    ) -> Dict[str, object]:
        motion_ratio = self._update_hold_motion(pts)
        motion_window = np.asarray(self._hold_motion, dtype=float)
        motion_mean = float(np.mean(motion_window)) if len(motion_window) else motion_ratio
        score_threshold = 65.0 if self.level == "beginner" else 70.0
        motion_threshold = 0.035 if self.level == "beginner" else 0.025
        min_history = min(8, self.history_len)
        metric_names = [rule.name for rule in profile.metrics if rule.name in metric_scores]
        history_counts = [len(self._hist.get(name, ())) for name in metric_names]
        history_ready = bool(history_counts) and min(history_counts) >= min_history
        motion_ready = len(self._hold_motion) >= min(5, self._hold_motion.maxlen or 5)
        stabilities = [
            float(metric_scores[name].get("stability", 1.0))
            for name in metric_names
        ]
        mean_stability = float(np.mean(stabilities)) if stabilities else 0.0
        min_stability = float(np.min(stabilities)) if stabilities else 0.0
        stability_ok = history_ready and mean_stability >= 0.65 and min_stability >= 0.45
        motion_ok = motion_ready and motion_mean <= motion_threshold
        score_ok = float(score) >= score_threshold
        hold_ready = bool(score_ok and stability_ok and motion_ok)
        if hold_ready:
            phase = "holding"
            label = zh(r"\u4fdd\u6301\u4e2d")
        elif not score_ok:
            phase = "preparing"
            label = zh(r"\u51c6\u5907\u4e2d")
        elif not history_ready or not motion_ready:
            phase = "building_window"
            label = zh(r"\u5efa\u7acb\u4fdd\u6301\u7a97\u53e3")
        else:
            phase = "adjusting"
            label = zh(r"\u8c03\u6574\u4e2d")
        return {
            "hold_ready": hold_ready,
            "hold_phase": phase,
            "hold_phase_label": label,
            "hold_score_ok": score_ok,
            "hold_score_threshold": score_threshold,
            "hold_history_ready": history_ready,
            "hold_motion_ready": motion_ready,
            "hold_motion_ratio": motion_mean,
            "hold_motion_threshold": motion_threshold,
            "hold_metric_stability": mean_stability,
            "hold_min_metric_stability": min_stability,
        }

    def _non_hold_detail(self, phase: str = "preparing") -> Dict[str, object]:
        label = zh(r"\u7b49\u5f85\u4fdd\u6301")
        return {
            "hold_ready": False,
            "hold_phase": phase,
            "hold_phase_label": label,
            "hold_score_ok": False,
            "hold_score_threshold": 65.0 if self.level == "beginner" else 70.0,
            "hold_history_ready": False,
            "hold_motion_ready": False,
            "hold_motion_ratio": 0.0,
            "hold_motion_threshold": 0.035 if self.level == "beginner" else 0.025,
            "hold_metric_stability": 0.0,
            "hold_min_metric_stability": 0.0,
        }

    def _front_back_legs(self, pts: np.ndarray) -> Tuple[str, str]:
        if float(pts[27][0]) > float(pts[28][0]):
            return "right", "left"
        return "left", "right"

    def _compute_metrics(self, pts: np.ndarray, topology=None) -> Dict[str, float]:
        p = np.asarray(pts, dtype=float)
        if p.shape[0] < 33:
            raise ValueError("landmarks must contain at least 33 points")

        if topology is None:
            topology = HumanTopologyTree.build(p)
        nodes = topology.nodes
        idx = {
            "right": {"hip": "right_hip", "knee": "right_knee", "ankle": "right_ankle"},
            "left": {"hip": "left_hip", "knee": "left_knee", "ankle": "left_ankle"},
        }
        knee_angles = {
            side: _angle_3pt(
                _xy(nodes[landmarks["hip"]]),
                _xy(nodes[landmarks["knee"]]),
                _xy(nodes[landmarks["ankle"]]),
            )
            for side, landmarks in idx.items()
        }
        if abs(knee_angles["left"] - knee_angles["right"]) >= 8.0:
            front = min(knee_angles, key=knee_angles.get)
            back = "left" if front == "right" else "right"
        else:
            front, back = self._front_back_legs(p)

        mid_sh = _xy(nodes["shoulder_center"])
        mid_hp = _xy(nodes["pelvis_center"])

        def elev_angle(sh_xy: np.ndarray, wr_xy: np.ndarray) -> float:
            v = wr_xy - sh_xy
            down = np.array([0.0, 1.0])
            denom = (np.linalg.norm(v) * np.linalg.norm(down)) + 1e-6
            c = float(np.clip(np.dot(v, down) / denom, -1.0, 1.0))
            return float(np.degrees(np.arccos(c)))

        shoulder_elevation = (
            elev_angle(_xy(nodes["right_shoulder"]), _xy(nodes["right_wrist"]))
            + elev_angle(_xy(nodes["left_shoulder"]), _xy(nodes["left_wrist"]))
        ) / 2.0
        thoracic_lateral_proxy = _line_tilt_from_horizontal(
            _xy(nodes["left_shoulder"]), _xy(nodes["right_shoulder"])
        )
        pelvis_tilt_proxy = _line_tilt_from_horizontal(
            _xy(nodes["left_hip"]), _xy(nodes["right_hip"])
        )
        trunk_mid_x = float((mid_sh[0] + mid_hp[0]) / 2.0)
        cervical_lateral_proxy = abs(float(nodes["nose"][0]) - trunk_mid_x) * 100.0

        dx = float(mid_sh[0] - mid_hp[0])
        dy = float(abs(mid_sh[1] - mid_hp[1]) + 1e-6)
        lumbar_lateral_proxy = float(np.degrees(np.arctan2(dx, dy)))
        shoulder_horizontal_proxy = (
            abs(float(nodes["left_wrist"][1] - nodes["left_shoulder"][1]))
            + abs(float(nodes["right_wrist"][1] - nodes["right_shoulder"][1]))
        ) * 50.0
        front_hip_opening_proxy = _angle_3pt(_xy(nodes[idx[front]["knee"]]), _xy(nodes[idx[front]["hip"]]), mid_hp)
        mid_ankle = (_xy(nodes["left_ankle"]) + _xy(nodes["right_ankle"])) / 2.0
        head_center = _xy(nodes["head_center"])
        left_knee = _xy(nodes["left_knee"])
        right_knee = _xy(nodes["right_knee"])
        left_shoulder = _xy(nodes["left_shoulder"])
        right_shoulder = _xy(nodes["right_shoulder"])
        left_wrist = _xy(nodes["left_wrist"])
        right_wrist = _xy(nodes["right_wrist"])
        left_heel = _xy(nodes["left_heel"])
        right_heel = _xy(nodes["right_heel"])
        left_foot_index = _xy(nodes["left_foot_index"])
        right_foot_index = _xy(nodes["right_foot_index"])

        spine_vertical_proxy = abs(lumbar_lateral_proxy)
        spine_line_proxy = abs(180.0 - _angle_3pt(mid_hp, mid_sh, head_center))
        hip_fold_angle = _angle_3pt(mid_sh, mid_hp, mid_ankle)
        knee_control_angle = min(knee_angles.values())
        weight_center_proxy = abs(float(mid_hp[0] - mid_ankle[0])) * 100.0
        knee_symmetry_proxy = abs(float(left_knee[1] - right_knee[1])) * 100.0
        knee_stack_proxy = abs(float(left_knee[0] - right_knee[0])) * 100.0
        pelvis_forward_back_proxy = abs(float(mid_hp[0] - mid_sh[0])) * 100.0
        arm_length_asym_proxy = abs(
            float(np.linalg.norm(left_wrist - left_shoulder) - np.linalg.norm(right_wrist - right_shoulder))
        ) * 100.0
        shoulder_wrist_stack_proxy = (
            abs(float(left_wrist[0] - left_shoulder[0]))
            + abs(float(right_wrist[0] - right_shoulder[0]))
        ) * 50.0
        shoulder_load_proxy = max(abs(thoracic_lateral_proxy), arm_length_asym_proxy, shoulder_wrist_stack_proxy)
        heel_lift_proxy = (
            max(0.0, float(left_foot_index[1] - left_heel[1]))
            + max(0.0, float(right_foot_index[1] - right_heel[1]))
        ) * 50.0
        core_balance_proxy = (spine_vertical_proxy + abs(pelvis_tilt_proxy)) / 2.0

        return {
            "shoulder_elevation": shoulder_elevation,
            "thoracic_lateral_proxy": abs(thoracic_lateral_proxy),
            "pelvis_tilt_proxy": abs(pelvis_tilt_proxy),
            "cervical_lateral_proxy": cervical_lateral_proxy,
            "lumbar_lateral_proxy": abs(lumbar_lateral_proxy),
            "shoulder_horizontal_proxy": shoulder_horizontal_proxy,
            "front_hip_opening_proxy": front_hip_opening_proxy,
            "knee_front_flex": knee_angles[front],
            "knee_back_ext": knee_angles[back],
            "spine_vertical": spine_vertical_proxy,
            "shoulder_symmetry": abs(thoracic_lateral_proxy),
            "pelvis_level": abs(pelvis_tilt_proxy),
            "neck_axis": cervical_lateral_proxy,
            "spine_line": spine_line_proxy,
            "pelvis_tilt": abs(pelvis_tilt_proxy),
            "knee_lock": knee_control_angle,
            "weight_center": weight_center_proxy,
            "pelvis_balance": abs(pelvis_tilt_proxy),
            "knee_symmetry": knee_symmetry_proxy,
            "spine_upright": spine_vertical_proxy,
            "shoulder_relax": abs(thoracic_lateral_proxy),
            "spine_curve": spine_line_proxy,
            "pelvis_forward_back": pelvis_forward_back_proxy,
            "head_forward": cervical_lateral_proxy,
            "knee_stack": knee_stack_proxy,
            "hip_hinge": hip_fold_angle,
            "knee_control": knee_control_angle,
            "balance": weight_center_proxy,
            "hip_depth": hip_fold_angle,
            "spine_round": spine_line_proxy,
            "weight_shift": weight_center_proxy,
            "spine_extension": spine_line_proxy,
            "shoulder_level": abs(thoracic_lateral_proxy),
            "pelvis_contact": abs(pelvis_tilt_proxy),
            "neck_extend": cervical_lateral_proxy,
            "spine_arc": spine_line_proxy,
            "hip_stability": abs(pelvis_tilt_proxy),
            "shoulder_load": shoulder_load_proxy,
            "neck_comp": cervical_lateral_proxy,
            "vertical_axis": spine_vertical_proxy,
            "ankle_control": weight_center_proxy,
            "core_balance": core_balance_proxy,
            "tilt_forward_back": spine_vertical_proxy,
            "hip_stack": pelvis_forward_back_proxy,
            "hip_angle": hip_fold_angle,
            "heel_contact": -heel_lift_proxy,
            "hip_height": hip_fold_angle,
            "shoulder_support": shoulder_load_proxy,
            "heel_extend": -heel_lift_proxy,
        }

    def _metric_geom_risk(self, rule: MetricRule, value: float) -> float:
        a, b = self._thr_pair(rule)
        if rule.mode == "range":
            if value < a:
                return float(np.clip((a - value) / rule.geom_gain, 0.0, 1.0))
            if value > b:
                return float(np.clip((value - b) / rule.geom_gain, 0.0, 1.0))
            return 0.0
        if rule.mode == "upper":
            return float(np.clip((value - a) / rule.geom_gain, 0.0, 1.0))
        if rule.mode == "lower":
            return float(np.clip((a - value) / rule.geom_gain, 0.0, 1.0))
        if rule.mode == "target":
            return float(np.clip((abs(value - a) - b) / rule.geom_gain, 0.0, 1.0))
        return 0.0

    def _metric_total_risk(self, rule: MetricRule, value: float) -> float:
        geom_risk = self._metric_geom_risk(rule, value)
        stability_risk = 1.0 - self._stability(rule.name)
        return float(
            np.clip(
                (1.0 - rule.stability_weight) * geom_risk + rule.stability_weight * stability_risk,
                0.0,
                1.0,
            )
        )

    def _score_metrics(
        self, profile: PoseCompensationProfile, metrics: Dict[str, float]
    ) -> Tuple[float, float, float, List[str], Dict[str, Dict[str, float]]]:
        metric_scores: Dict[str, Dict[str, float]] = {}
        notes: List[str] = []
        mobile_weight = 0.0
        stiff_weight = 0.0
        mobile_sum = 0.0
        stiff_sum = 0.0

        for rule in profile.metrics:
            value = metrics[rule.name]
            self._push_hist(rule.name, value)
            geom_risk = self._metric_geom_risk(rule, value)
            stability = self._stability(rule.name)
            total_risk = self._metric_total_risk(rule, value)
            score = 100.0 * (1.0 - total_risk)
            metric_scores[rule.name] = {
                "value": value,
                "geom_risk": geom_risk,
                "stability": stability,
                "risk": total_risk,
                "score": score,
                "weight": rule.weight,
            }

            if geom_risk > 0.15 or (1.0 - stability) > 0.35:
                notes.append(rule.note)

            if rule.category == "mobile":
                mobile_sum += total_risk * rule.weight
                mobile_weight += rule.weight
            else:
                stiff_sum += total_risk * rule.weight
                stiff_weight += rule.weight

        mobile_risk = mobile_sum / mobile_weight if mobile_weight else 0.0
        stiff_risk = stiff_sum / stiff_weight if stiff_weight else 0.0
        overall_risk = (
            mobile_risk * profile.mobile_group_weight + stiff_risk * profile.stiff_group_weight
        ) / (profile.mobile_group_weight + profile.stiff_group_weight)
        return float(overall_risk), float(mobile_risk), float(stiff_risk), notes, metric_scores

    def _score_dimensions(
        self,
        profile: PoseCompensationProfile,
        metric_scores: Dict[str, Dict[str, float]],
        mobile_risk: float,
        stiff_risk: float,
        hold_detail: Dict[str, object],
        bone_detail: Dict[str, object],
    ) -> Dict[str, float]:
        weighted_geom = 0.0
        weighted_stability = 0.0
        total_weight = 0.0
        for rule in profile.metrics:
            item = metric_scores.get(rule.name)
            if not item:
                continue
            weight = float(rule.weight)
            weighted_geom += (1.0 - float(item.get("geom_risk", 0.0))) * weight
            weighted_stability += float(item.get("stability", 1.0)) * weight
            total_weight += weight

        if total_weight <= 0.0:
            joint_conformity = 0.0
            metric_stability = 0.0
        else:
            joint_conformity = float(np.clip(weighted_geom / total_weight, 0.0, 1.0)) * 100.0
            metric_stability = float(np.clip(weighted_stability / total_weight, 0.0, 1.0))

        if bone_detail.get("bone_length_ready"):
            bone_quality = float(bone_detail.get("bone_length_quality", 0.0))
        else:
            bone_quality = metric_stability

        motion_ratio = float(hold_detail.get("hold_motion_ratio", 0.0))
        motion_threshold = float(hold_detail.get("hold_motion_threshold", 0.025)) + 1e-6
        motion_score = float(np.clip(1.0 - motion_ratio / max(motion_threshold * 2.0, 1e-6), 0.0, 1.0))
        topology_stability = (
            0.55 * metric_stability
            + 0.25 * float(np.clip(bone_quality, 0.0, 1.0))
            + 0.20 * motion_score
        ) * 100.0

        proxy_risk = (
            mobile_risk * profile.mobile_group_weight + stiff_risk * profile.stiff_group_weight
        ) / (profile.mobile_group_weight + profile.stiff_group_weight)
        force_proxy = float(np.clip(1.0 - proxy_risk, 0.0, 1.0)) * 100.0
        overall = (
            0.30 * joint_conformity
            + 0.35 * topology_stability
            + 0.35 * force_proxy
        )
        return {
            "score_joint_conformity": float(np.clip(joint_conformity, 0.0, 100.0)),
            "score_topology_stability": float(np.clip(topology_stability, 0.0, 100.0)),
            "score_force_proxy": float(np.clip(force_proxy, 0.0, 100.0)),
            "score_overall": float(np.clip(overall, 0.0, 100.0)),
        }

    def analyze(
        self, points: np.ndarray, action_tag: str
    ) -> Optional[Tuple[float, float, str, str, Dict[str, float], Dict[str, float], Dict[str, Dict[str, float]]]]:
        if points is None:
            return None
        pts = np.asarray(points, dtype=float)
        if pts.shape[0] < 33:
            return None
        if float(pts[23][1]) > 0.9 or float(pts[24][1]) > 0.9:
            return None

        profile = self.POSE_PROFILES.get((action_tag or "").strip().lower())
        if profile is None:
            return None

        raw_topology = HumanTopologyTree.build(pts)
        ik_result = self.ik_stabilizer.stabilize(pts, raw_topology)
        stable_pts = ik_result.landmarks
        topology = ik_result.topology
        metrics = self._compute_metrics(stable_pts, topology)
        risk, mobile_risk, stiff_risk, notes, metric_scores = self._score_metrics(profile, metrics)
        provisional_score = float(np.clip(100.0 * (1.0 - risk), 0.0, 100.0))
        hold_detail = self._hold_phase_detail(profile, stable_pts, provisional_score, metric_scores)
        bone_status = self.bone_length_tracker.update(
            topology,
            learn_reference=bool(hold_detail["hold_ready"]),
        )
        bone_detail = bone_status.as_detail()
        dimension_scores = self._score_dimensions(
            profile,
            metric_scores,
            mobile_risk,
            stiff_risk,
            hold_detail,
            bone_detail,
        )
        score = dimension_scores["score_overall"]
        risk = float(np.clip(1.0 - score / 100.0, 0.0, 1.0))
        grade, voice = self._voice_ladder(score, notes, profile)
        detail = {
            "risk_mobile_lock": mobile_risk,
            "risk_stiff_comp": stiff_risk,
            "score": score,
            **dimension_scores,
            **hold_detail,
            **bone_detail,
            **ik_result.detail,
        }
        return risk, score, grade, voice, metrics, detail, metric_scores

    def analyze_report(
        self, points: np.ndarray, action_tag: str
    ) -> Optional[
        Tuple[Dict[str, str], str, str, float, float, str, Dict[str, float], Dict[str, Dict[str, float]]]
    ]:
        result = self.analyze(points, action_tag)
        if result is None:
            return None

        risk, score, grade, voice, metrics, detail, metric_scores = result
        profile = self.POSE_PROFILES[(action_tag or "").strip().lower()]
        status = self._status_map(detail)
        report_html = self._build_report_html(profile, risk, score, grade, voice, metrics, detail, metric_scores)
        return status, report_html, voice, risk, score, grade, detail, metric_scores

    def _voice_ladder(
        self, score: float, notes: List[str], profile: PoseCompensationProfile
    ) -> Tuple[str, str]:
        drive = self.DRIVE_CN[profile.primary_drive]
        if score >= 85.0:
            prefix = zh(r"\u5f53\u524d\u4ee5")
            suffix = zh(r"\u9a71\u52a8\u4e3a\u4e3b\uff0c\u52a8\u4f5c\u8d28\u91cf\u5f88\u597d\uff0c\u7ee7\u7eed\u4fdd\u6301\u547c\u5438\u548c\u5ef6\u5c55\u3002")
            return "A", f"{profile.title}{prefix}{drive}{suffix}"
        if score >= 70.0:
            return "B", zh(r"\u8f7b\u5ea6\u4ee3\u507f\u98ce\u9669\uff1a") + (
                notes[0] if notes else zh(r"\u5fae\u8c03\u9aa8\u76c6\u548c\u808b\u9aa8\u5bf9\u4f4d\u3002")
            )
        if score >= 55.0:
            return "C", zh(r"\u4e2d\u5ea6\u4ee3\u507f\u98ce\u9669\uff1a") + (
                zh(r"\uff1b").join(notes[:2])
                if notes
                else zh(r"\u7f29\u5c0f\u5e45\u5ea6\uff0c\u4f18\u5148\u627e\u7a33\u5b9a\u3002")
            )
        return "D", zh(r"\u9ad8\u98ce\u9669\u9884\u8b66\uff1a\u5148\u9000\u56de\u5230\u5b89\u5168\u5e45\u5ea6\u3002") + (
            " " + notes[0] if notes else ""
        )

    def _status_map(self, detail: Dict[str, float]) -> Dict[str, str]:
        status = {"neck": "ok", "shoulder_l": "ok", "shoulder_r": "ok", "pelvis": "ok", "spine": "ok"}
        if detail.get("risk_stiff_comp", 0.0) >= 0.2:
            status["neck"] = "issue"
            status["spine"] = "issue"
            status["pelvis"] = "issue"
        if detail.get("risk_mobile_lock", 0.0) >= 0.2:
            status["shoulder_l"] = "issue"
            status["shoulder_r"] = "issue"
        return status

    def _build_report_html(
        self,
        profile: PoseCompensationProfile,
        risk: float,
        score: float,
        grade: str,
        voice: str,
        metrics: Dict[str, float],
        detail: Dict[str, float],
        metric_scores: Dict[str, Dict[str, float]],
    ) -> str:
        grade_color = {"A": "#10B981", "B": "#F59E0B", "C": "#F97316", "D": "#EF4444"}.get(grade, "#E2E8F0")
        drive = self.DRIVE_CN[profile.primary_drive]
        colon = zh(r"\uff1a")
        weight_label = zh(r"\uff0c\u6743\u91cd")
        metric_score_label = zh(r"\uff0c\u8bc4\u5206")
        metric_lines = []
        for rule in profile.metrics:
            item = metric_scores[rule.name]
            metric_lines.append(
                f"<li style='color:#E2E8F0;'>{rule.label}{colon}{item['value']:.1f}{weight_label} {rule.weight:.2f}{metric_score_label} {item['score']:.0f}</li>"
            )
        report_title = zh(r"\u52a8\u4f5c\u8bc4\u5206\u62a5\u544a")
        drive_label = zh(r"\u52a8\u4f5c\u9a71\u52a8\uff1a")
        drive_suffix = zh(r"\u9a71\u52a8\u7c7b\uff1b")
        grade_label = zh(r"\u4f53\u6001\u7b49\u7ea7\uff1a")
        score_label = zh(r"\u52a8\u4f5c\u8bc4\u5206\uff1a")
        risk_open = zh(r"\uff08\u603b\u4f53\u98ce\u9669")
        risk_close = zh(r"\uff09")
        dimension_label = zh(r"\u8bba\u6587\u4e09\u7ef4\u8bc4\u5206\uff1a")
        joint_label = zh(r"\u5173\u8282-\u59ff\u6001\u7b26\u5408\u5ea6")
        topology_label = zh(r"\u62d3\u6251\u7a33\u5b9a\u4e0e\u4ee3\u507f\u63a7\u5236")
        force_label = zh(r"\u529b\u6a21\u5f0f\u4ee3\u7406\u5408\u7406\u6027")
        group_label = zh(r"\u5206\u7ec4\u98ce\u9669\uff1a")
        mobile_label = zh(r"\u7075\u6d3b\u5173\u8282\u9501\u5b9a")
        stiff_label = zh(r"\u975e\u7075\u6d3b\u5173\u8282\u4ee3\u507f")
        hold_label = zh(r"\u4fdd\u6301\u9636\u6bb5\uff1a")
        sample_label = zh(r"\u865a\u62df\u9aa8\u957f\u91c7\u6837\uff1a")
        topology_ik_label = zh(r"\u62d3\u6251/IK/\u9aa8\u9abc\u5411\u91cf\uff1a")
        node_label = zh(r"\u8282\u70b9")
        edge_label = zh(r"\u8fb9")
        ik_iter_label = zh(r"IK \u8fed\u4ee3")
        residual_label = zh(r"\u6b8b\u5dee")
        vector_label = zh(r"\u5e73\u5747\u5411\u91cf\u957f")
        hold_text = str(detail.get("hold_phase_label", zh(r"\u51c6\u5907\u4e2d")))
        sample_text = (
            zh(r"\u91c7\u6837\u4e2d")
            if detail.get("bone_length_learn_reference")
            else zh(r"\u6682\u505c\u91c7\u6837")
        )
        bone_label = zh(r"\u865a\u62df\u9aa8\u957f\u53ef\u4fe1\u5ea6\uff1a")
        max_dev_label = zh(r"\u6700\u5927\u504f\u79bb")
        if detail.get("bone_length_ready"):
            bone_state = (
                zh(r"\u53ef\u4fe1")
                if detail.get("bone_length_valid")
                else zh(r"\u5f02\u5e38")
            )
            bone_text = (
                f"{bone_state} "
                f"{float(detail.get('bone_length_quality', 0.0)) * 100:.0f}%"
                f" / {max_dev_label} "
                f"{float(detail.get('bone_length_max_deviation', 0.0)) * 100:.1f}%"
            )
        else:
            bone_text = zh(r"\u7a97\u53e3\u5efa\u7acb\u4e2d")
        voice_label = zh(r"\u8bed\u97f3\u7ea0\u6b63\uff1a")
        return f"""
        <div style='font-size:14px; line-height:1.5;'>
            <h3 style='color: #F59E0B;'>{profile.title}{report_title}</h3>
            <p><b>{drive_label}</b>{drive}{drive_suffix}<b>{grade_label}</b><span style="color:{grade_color};">{grade}</span></p>
            <p><b>{score_label}</b><span style="color:{grade_color};">{score:.0f}</span> / 100
            <span style="color:#94A3B8;">{risk_open} {risk * 100:.0f}%{risk_close}</span></p>
            <p><b>{dimension_label}</b><span style="color:#94A3B8;">{joint_label} {detail.get('score_joint_conformity', 0.0):.0f} / {topology_label} {detail.get('score_topology_stability', 0.0):.0f} / {force_label} {detail.get('score_force_proxy', 0.0):.0f}</span></p>
            <p><b>{group_label}</b><span style="color:#94A3B8;">{mobile_label} {detail['risk_mobile_lock'] * 100:.0f}% / {stiff_label} {detail['risk_stiff_comp'] * 100:.0f}%</span></p>
            <p><b>{topology_ik_label}</b><span style="color:#94A3B8;">{node_label} {detail.get('topology_node_count', 0)} / {edge_label} {detail.get('topology_edge_count', 0)} / {ik_iter_label} {detail.get('ik_iterations', 0)} / {residual_label} {detail.get('ik_final_residual', 0.0):.4f} / {vector_label} {detail.get('skeleton_vector_mean_length', 0.0):.3f}</span></p>
            <p><b>{hold_label}</b><span style="color:#94A3B8;">{hold_text}</span> <b>{sample_label}</b><span style="color:#94A3B8;">{sample_text}</span></p>
            <p><b>{bone_label}</b><span style="color:#94A3B8;">{bone_text}</span></p>
            <ul>{''.join(metric_lines)}</ul>
            <p style='color: #94A3B8;'><b>{voice_label}</b>{voice}</p>
        </div>
        """

