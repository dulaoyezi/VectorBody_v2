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

    SHOULDERSTAND_FRONT_METRICS = (
        MetricRule(
            name="shoulderstand_head_offset_ratio",
            label=zh(r"\u5934\u9888\u504f\u79fb"),
            category="stiff",
            weight=0.14,
            mode="upper",
            normal_a=0.35,
            normal_b=0.0,
            beginner_a=0.50,
            beginner_b=0.0,
            geom_gain=0.35,
            stability_weight=0.35,
            note=zh(r"\u5934\u9888\u504f\u79fb\u589e\u5927\uff0c\u8bf7\u4fdd\u6301\u5934\u90e8\u4e2d\u6b63\uff0c\u4e0d\u8981\u8f6c\u5934\u6216\u504f\u5934\u3002"),
        ),
        MetricRule(
            name="shoulderstand_shoulder_support_proxy",
            label=zh(r"\u80a9\u80cc\u652f\u6491"),
            category="mobile",
            weight=0.14,
            mode="upper",
            normal_a=8.0,
            normal_b=0.0,
            beginner_a=12.0,
            beginner_b=0.0,
            geom_gain=12.0,
            stability_weight=0.30,
            note=zh(r"\u80a9\u80cc\u652f\u6491\u4e0d\u7a33\u5b9a\uff0c\u8bf7\u8ba9\u80a9\u80db\u7a33\u5b9a\u627f\u91cd\uff0c\u907f\u514d\u538b\u529b\u843d\u5230\u9888\u690e\u3002"),
        ),
        MetricRule(
            name="shoulderstand_hip_height_pct",
            label=zh(r"\u9acb\u90e8\u5806\u53e0\u9ad8\u5ea6"),
            category="stiff",
            weight=0.10,
            mode="lower",
            normal_a=0.0,
            normal_b=0.0,
            beginner_a=-5.0,
            beginner_b=0.0,
            geom_gain=20.0,
            stability_weight=0.35,
            note=zh(r"\u9acb\u70b9\u6ca1\u6709\u9ad8\u4e8e\u5934\u90e8\uff0c\u8bf7\u5148\u628a\u9acb\u90e8\u5411\u4e0a\u5806\u53e0\u5230\u80a9\u4e0a\u65b9\u9644\u8fd1\u3002"),
        ),
        MetricRule(
            name="shoulderstand_elbow_width_ratio",
            label=zh(r"\u53cc\u8098\u5bbd\u5ea6"),
            category="mobile",
            weight=0.15,
            mode="range",
            normal_a=0.8,
            normal_b=1.2,
            beginner_a=0.7,
            beginner_b=1.5,
            geom_gain=0.5,
            stability_weight=0.25,
            note=zh(r"\u53cc\u8098\u8ddd\u79bb\u504f\u79bb\u80a9\u5bbd\uff0c\u8bf7\u6536\u56de\u53cc\u8098\uff0c\u7ef4\u6301\u80a9\u80cc\u652f\u6491\u3002"),
        ),
        MetricRule(
            name="shoulderstand_pelvis_tilt_proxy",
            label=zh(r"\u9aa8\u76c6\u503e\u659c"),
            category="stiff",
            weight=0.13,
            mode="upper",
            normal_a=5.0,
            normal_b=0.0,
            beginner_a=10.0,
            beginner_b=0.0,
            geom_gain=10.0,
            stability_weight=0.30,
            note=zh(r"\u9aa8\u76c6\u5de6\u53f3\u503e\u659c\u660e\u663e\uff0c\u8bf7\u8ba9\u4e24\u4fa7\u9acb\u70b9\u4fdd\u6301\u6c34\u5e73\u3002"),
        ),
        MetricRule(
            name="shoulderstand_leg_separation_ratio",
            label=zh(r"\u53cc\u817f\u5e76\u62e2"),
            category="mobile",
            weight=0.14,
            mode="upper",
            normal_a=0.5,
            normal_b=0.0,
            beginner_a=1.0,
            beginner_b=0.0,
            geom_gain=1.0,
            stability_weight=0.25,
            note=zh(r"\u53cc\u817f\u5206\u79bb\u660e\u663e\uff0c\u8bf7\u8ba9\u53cc\u817f\u5411\u4e2d\u7ebf\u5e76\u62e2\u5e76\u4fdd\u6301\u5bf9\u79f0\u3002"),
        ),
        MetricRule(
            name="shoulderstand_midline_offset_pct",
            label=zh(r"\u8eaf\u5e72\u4e2d\u7ebf"),
            category="stiff",
            weight=0.10,
            mode="upper",
            normal_a=5.0,
            normal_b=0.0,
            beginner_a=10.0,
            beginner_b=0.0,
            geom_gain=10.0,
            stability_weight=0.35,
            note=zh(r"\u80a9\u3001\u9acb\u3001\u8e1d\u4e2d\u7ebf\u504f\u79fb\u660e\u663e\uff0c\u8bf7\u8ba9\u8eab\u4f53\u56de\u5230\u540c\u4e00\u4e2d\u7ebf\u9644\u8fd1\u3002"),
        ),
        MetricRule(
            name="shoulderstand_knee_angle",
            label=zh(r"\u819d\u76d6\u4f38\u76f4"),
            category="stiff",
            weight=0.12,
            mode="range",
            normal_a=165.0,
            normal_b=178.0,
            beginner_a=135.0,
            beginner_b=178.0,
            geom_gain=25.0,
            stability_weight=0.30,
            note=zh(r"\u819d\u76d6\u4f38\u5c55\u4e0d\u8db3\u6216\u8fc7\u5ea6\u9501\u6b7b\uff0c\u8bf7\u8f7b\u5fae\u8c03\u6574\u819d\u76d6\uff0c\u4fdd\u6301\u817f\u90e8\u7a33\u5b9a\u5ef6\u5c55\u3002"),
        ),
    )

    SHOULDERSTAND_SIDE_METRICS = (
        MetricRule(
            name="shoulderstand_vertical_stack_angle",
            label=zh(r"\u5782\u76f4\u5806\u53e0"),
            category="mobile",
            weight=0.22,
            mode="upper",
            normal_a=10.0,
            normal_b=0.0,
            beginner_a=20.0,
            beginner_b=0.0,
            geom_gain=20.0,
            stability_weight=0.35,
            note=zh(r"\u80a9\u3001\u9acb\u3001\u8e1d\u5782\u76f4\u5806\u53e0\u4e0d\u8db3\uff0c\u8bf7\u5148\u7f29\u5c0f\u5e45\u5ea6\uff0c\u907f\u514d\u8eab\u4f53\u91cd\u91cf\u538b\u5411\u9888\u690e\u3002"),
        ),
        MetricRule(
            name="shoulderstand_hip_height_pct",
            label=zh(r"\u9acb\u90e8\u5806\u53e0\u9ad8\u5ea6"),
            category="stiff",
            weight=0.18,
            mode="lower",
            normal_a=0.0,
            normal_b=0.0,
            beginner_a=-5.0,
            beginner_b=0.0,
            geom_gain=20.0,
            stability_weight=0.35,
            note=zh(r"\u9acb\u70b9\u6ca1\u6709\u9ad8\u4e8e\u5934\u90e8\uff0c\u8bf7\u5148\u628a\u9acb\u90e8\u5411\u4e0a\u5806\u53e0\u5230\u80a9\u4e0a\u65b9\u9644\u8fd1\u3002"),
        ),
        MetricRule(
            name="shoulderstand_lumbar_collapse_proxy",
            label=zh(r"\u8170\u690e\u584c\u9677"),
            category="stiff",
            weight=0.16,
            mode="upper",
            normal_a=6.0,
            normal_b=0.0,
            beginner_a=8.0,
            beginner_b=0.0,
            geom_gain=12.0,
            stability_weight=0.35,
            note=zh(r"\u8170\u690e\u584c\u9677\u6216\u8eaf\u5e72\u4fa7\u5f2f\u660e\u663e\uff0c\u8bf7\u6536\u7d27\u6838\u5fc3\uff0c\u907f\u514d\u7528\u8170\u90e8\u4ee3\u507f\u3002"),
        ),
        MetricRule(
            name="shoulderstand_shoulder_support_proxy",
            label=zh(r"\u80a9\u80cc\u652f\u6491"),
            category="mobile",
            weight=0.14,
            mode="upper",
            normal_a=8.0,
            normal_b=0.0,
            beginner_a=12.0,
            beginner_b=0.0,
            geom_gain=12.0,
            stability_weight=0.35,
            note=zh(r"\u80a9\u80cc\u652f\u6491\u4e0d\u7a33\u5b9a\uff0c\u8bf7\u8ba9\u80a9\u80db\u7a33\u5b9a\u627f\u91cd\uff0c\u907f\u514d\u538b\u529b\u843d\u5230\u9888\u690e\u3002"),
        ),
        MetricRule(
            name="shoulderstand_knee_angle",
            label=zh(r"\u819d\u76d6\u4f38\u76f4"),
            category="stiff",
            weight=0.14,
            mode="range",
            normal_a=165.0,
            normal_b=178.0,
            beginner_a=135.0,
            beginner_b=178.0,
            geom_gain=25.0,
            stability_weight=0.30,
            note=zh(r"\u819d\u76d6\u4f38\u5c55\u4e0d\u8db3\u6216\u8fc7\u5ea6\u9501\u6b7b\uff0c\u8bf7\u8f7b\u5fae\u8c03\u6574\u819d\u76d6\uff0c\u4fdd\u6301\u817f\u90e8\u7a33\u5b9a\u5ef6\u5c55\u3002"),
        ),
        MetricRule(
            name="shoulderstand_head_offset_ratio",
            label=zh(r"\u5934\u9888\u504f\u79fb"),
            category="stiff",
            weight=0.08,
            mode="upper",
            normal_a=1.4,
            normal_b=0.0,
            beginner_a=1.8,
            beginner_b=0.0,
            geom_gain=0.8,
            stability_weight=0.35,
            note=zh(r"\u5934\u9888\u504f\u79fb\u589e\u5927\uff0c\u8bf7\u4fdd\u6301\u5934\u90e8\u4e2d\u6b63\uff0c\u4e0d\u8981\u8f6c\u5934\u6216\u504f\u5934\u3002"),
        ),
        MetricRule(
            name="shoulderstand_midline_offset_pct",
            label=zh(r"\u8eaf\u5e72\u4e2d\u7ebf"),
            category="stiff",
            weight=0.08,
            mode="upper",
            normal_a=5.0,
            normal_b=0.0,
            beginner_a=10.0,
            beginner_b=0.0,
            geom_gain=10.0,
            stability_weight=0.35,
            note=zh(r"\u80a9\u3001\u9acb\u3001\u8e1d\u4e2d\u7ebf\u504f\u79fb\u660e\u663e\uff0c\u8bf7\u8ba9\u8eab\u4f53\u56de\u5230\u540c\u4e00\u4e2d\u7ebf\u9644\u8fd1\u3002"),
        ),
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
        "shoulderstand": PoseCompensationProfile(
            title=zh(r"\u80a9\u5012\u7acb"),
            primary_drive=DriveCategory.SHOULDER,
            metrics=SHOULDERSTAND_FRONT_METRICS,
            mobile_group_weight=0.40,
            stiff_group_weight=0.60,
        ),
        "shoulderstand_front": PoseCompensationProfile(
            title=zh(r"\u80a9\u5012\u7acb-\u6b63\u4f4d"),
            primary_drive=DriveCategory.SHOULDER,
            metrics=SHOULDERSTAND_FRONT_METRICS,
            mobile_group_weight=0.40,
            stiff_group_weight=0.60,
        ),
        "shoulderstand_side": PoseCompensationProfile(
            title=zh(r"\u80a9\u5012\u7acb-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.SHOULDER,
            metrics=SHOULDERSTAND_SIDE_METRICS,
            mobile_group_weight=0.30,
            stiff_group_weight=0.70,
        ),
        "salamba_sarvangasana": PoseCompensationProfile(
            title=zh(r"\u80a9\u5012\u7acb"),
            primary_drive=DriveCategory.SHOULDER,
            metrics=SHOULDERSTAND_FRONT_METRICS,
            mobile_group_weight=0.40,
            stiff_group_weight=0.60,
        ),
        "salamba_sarvangasana_front": PoseCompensationProfile(
            title=zh(r"\u80a9\u5012\u7acb-\u6b63\u4f4d"),
            primary_drive=DriveCategory.SHOULDER,
            metrics=SHOULDERSTAND_FRONT_METRICS,
            mobile_group_weight=0.40,
            stiff_group_weight=0.60,
        ),
        "salamba_sarvangasana_side": PoseCompensationProfile(
            title=zh(r"\u80a9\u5012\u7acb-\u4fa7\u4f4d"),
            primary_drive=DriveCategory.SHOULDER,
            metrics=SHOULDERSTAND_SIDE_METRICS,
            mobile_group_weight=0.30,
            stiff_group_weight=0.70,
        ),
    }

    def __init__(self, history_len: int = 12, level: str = "normal"):
        self.history_len = max(3, int(history_len))
        self.level = level if level in ("normal", "beginner") else "normal"
        self._hist: Dict[str, Deque[float]] = {}

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

    def _front_back_legs(self, pts: np.ndarray) -> Tuple[str, str]:
        if float(pts[27][0]) > float(pts[28][0]):
            return "right", "left"
        return "left", "right"

    def _compute_metrics(self, pts: np.ndarray) -> Dict[str, float]:
        p = np.asarray(pts, dtype=float)
        if p.shape[0] < 33:
            raise ValueError("landmarks must contain at least 33 points")

        front, back = self._front_back_legs(p)
        idx = {
            "right": {"hip": 24, "knee": 26, "ankle": 28},
            "left": {"hip": 23, "knee": 25, "ankle": 27},
        }

        fh = p[idx[front]["hip"]][:2]
        fk = p[idx[front]["knee"]][:2]
        fa = p[idx[front]["ankle"]][:2]
        bh = p[idx[back]["hip"]][:2]
        bk = p[idx[back]["knee"]][:2]
        ba = p[idx[back]["ankle"]][:2]

        mid_sh = _mid(p, 11, 12)[:2]
        mid_hp = _mid(p, 23, 24)[:2]

        def elev_angle(sh_xy: np.ndarray, wr_xy: np.ndarray) -> float:
            v = wr_xy - sh_xy
            down = np.array([0.0, 1.0])
            denom = (np.linalg.norm(v) * np.linalg.norm(down)) + 1e-6
            c = float(np.clip(np.dot(v, down) / denom, -1.0, 1.0))
            return float(np.degrees(np.arccos(c)))

        shoulder_elevation = (
            elev_angle(p[12][:2], p[16][:2]) + elev_angle(p[11][:2], p[15][:2])
        ) / 2.0
        thoracic_lateral_proxy = float(
            np.degrees(np.arctan2(p[12][1] - p[11][1], (p[12][0] - p[11][0]) + 1e-6))
        )
        pelvis_tilt_proxy = float(
            np.degrees(np.arctan2(p[24][1] - p[23][1], (p[24][0] - p[23][0]) + 1e-6))
        )
        trunk_mid_x = float((mid_sh[0] + mid_hp[0]) / 2.0)
        cervical_lateral_proxy = abs(float(p[0][0]) - trunk_mid_x) * 100.0

        dx = float(mid_sh[0] - mid_hp[0])
        dy = float(abs(mid_sh[1] - mid_hp[1]) + 1e-6)
        lumbar_lateral_proxy = float(np.degrees(np.arctan2(dx, dy)))
        shoulder_horizontal_proxy = (
            abs(float(p[15][1] - p[11][1])) + abs(float(p[16][1] - p[12][1]))
        ) * 50.0
        front_hip_opening_proxy = _angle_3pt(p[idx[front]["knee"]][:2], p[idx[front]["hip"]][:2], mid_hp)

        mid_kn = _mid(p, 25, 26)[:2]
        mid_an = _mid(p, 27, 28)[:2]
        shoulder_width = float(np.linalg.norm(p[11][:2] - p[12][:2])) + 1e-6
        hip_width = float(np.linalg.norm(p[23][:2] - p[24][:2])) + 1e-6
        body_height = float(np.ptp(p[:, 1])) + 1e-6

        def line_angle_from_vertical(a_xy: np.ndarray, b_xy: np.ndarray) -> float:
            v = b_xy - a_xy
            return abs(float(np.degrees(np.arctan2(float(v[0]), abs(float(v[1])) + 1e-6))))

        def point_line_distance(point_xy: np.ndarray, a_xy: np.ndarray, b_xy: np.ndarray) -> float:
            v = b_xy - a_xy
            w = point_xy - a_xy
            cross = abs(float(v[0] * w[1] - v[1] * w[0]))
            return cross / (float(np.linalg.norm(v)) + 1e-6)

        elbow_width_ratio = float(np.linalg.norm(p[13][:2] - p[14][:2]) / shoulder_width)
        leg_separation_ratio = float(np.linalg.norm(p[27][:2] - p[28][:2]) / hip_width)
        knee_l = _angle_3pt(p[23][:2], p[25][:2], p[27][:2])
        knee_r = _angle_3pt(p[24][:2], p[26][:2], p[28][:2])
        shoulderstand_knee_angle = (knee_l + knee_r) / 2.0
        elbow_spread_risk = max(0.0, elbow_width_ratio - 1.2, 0.8 - elbow_width_ratio) * 20.0
        shoulderstand_shoulder_support_proxy = max(abs(thoracic_lateral_proxy), elbow_spread_risk)
        shoulderstand_midline_offset_pct = max(
            point_line_distance(mid_hp, mid_sh, mid_an),
            point_line_distance(mid_kn, mid_sh, mid_an),
        ) / body_height * 100.0
        shoulderstand_vertical_stack_angle = max(
            line_angle_from_vertical(mid_sh, mid_hp),
            line_angle_from_vertical(mid_hp, mid_an),
            line_angle_from_vertical(mid_sh, mid_an),
        )
        head_side = float(np.sign(float(p[0][0]) - float(mid_sh[0])))
        if head_side == 0.0:
            head_side = 1.0
        hip_shift_pct = (float(mid_hp[0]) - float(mid_sh[0])) * head_side / body_height * 100.0
        shoulderstand_hip_foot_shift_pct = max(0.0, -hip_shift_pct)
        leg_head_shift_pct = (float(mid_an[0]) - float(mid_hp[0])) * head_side / body_height * 100.0
        shoulderstand_hip_height_pct = (
            max(float(p[0][1]), float(mid_sh[1])) - float(mid_hp[1])
        ) / body_height * 100.0
        shoulderstand_hip_over_shoulder_pct = (float(mid_sh[1]) - float(mid_hp[1])) / body_height * 100.0
        shoulderstand_knee_height_pct = (
            max(float(p[0][1]), float(mid_sh[1])) - float(mid_kn[1])
        ) / body_height * 100.0
        shoulderstand_ankle_height_pct = (
            max(float(p[0][1]), float(mid_sh[1])) - float(mid_an[1])
        ) / body_height * 100.0
        shoulderstand_knee_over_hip_pct = (float(mid_hp[1]) - float(mid_kn[1])) / body_height * 100.0
        shoulderstand_ankle_over_hip_pct = (float(mid_hp[1]) - float(mid_an[1])) / body_height * 100.0
        shoulderstand_head_below_shoulder_pct = (float(p[0][1]) - float(mid_sh[1])) / body_height * 100.0
        shoulderstand_inversion_pct = min(
            shoulderstand_hip_height_pct,
            shoulderstand_knee_height_pct,
            shoulderstand_ankle_height_pct,
        )
        shoulderstand_lumbar_collapse_proxy = max(
            line_angle_from_vertical(mid_sh, mid_hp),
            shoulderstand_hip_foot_shift_pct,
        )
        head_offset_ref = max(shoulder_width, hip_width, body_height * 0.2)
        shoulderstand_head_offset_ratio = abs(float(p[0][0]) - float(mid_sh[0])) / head_offset_ref

        return {
            "shoulder_elevation": shoulder_elevation,
            "thoracic_lateral_proxy": abs(thoracic_lateral_proxy),
            "pelvis_tilt_proxy": abs(pelvis_tilt_proxy),
            "cervical_lateral_proxy": cervical_lateral_proxy,
            "lumbar_lateral_proxy": abs(lumbar_lateral_proxy),
            "shoulder_horizontal_proxy": shoulder_horizontal_proxy,
            "front_hip_opening_proxy": front_hip_opening_proxy,
            "knee_front_flex": _angle_3pt(fh, fk, fa),
            "knee_back_ext": _angle_3pt(bh, bk, ba),
            "shoulderstand_head_offset_ratio": shoulderstand_head_offset_ratio,
            "shoulderstand_shoulder_support_proxy": shoulderstand_shoulder_support_proxy,
            "shoulderstand_elbow_width_ratio": elbow_width_ratio,
            "shoulderstand_pelvis_tilt_proxy": abs(pelvis_tilt_proxy),
            "shoulderstand_leg_separation_ratio": leg_separation_ratio,
            "shoulderstand_midline_offset_pct": shoulderstand_midline_offset_pct,
            "shoulderstand_knee_angle": shoulderstand_knee_angle,
            "shoulderstand_vertical_stack_angle": shoulderstand_vertical_stack_angle,
            "shoulderstand_hip_height_pct": shoulderstand_hip_height_pct,
            "shoulderstand_hip_over_shoulder_pct": shoulderstand_hip_over_shoulder_pct,
            "shoulderstand_knee_height_pct": shoulderstand_knee_height_pct,
            "shoulderstand_ankle_height_pct": shoulderstand_ankle_height_pct,
            "shoulderstand_knee_over_hip_pct": shoulderstand_knee_over_hip_pct,
            "shoulderstand_ankle_over_hip_pct": shoulderstand_ankle_over_hip_pct,
            "shoulderstand_head_below_shoulder_pct": shoulderstand_head_below_shoulder_pct,
            "shoulderstand_leg_head_shift_pct": max(0.0, leg_head_shift_pct),
            "shoulderstand_inversion_pct": shoulderstand_inversion_pct,
            "shoulderstand_lumbar_collapse_proxy": shoulderstand_lumbar_collapse_proxy,
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

    def _is_shoulderstand_profile(self, profile: PoseCompensationProfile) -> bool:
        return any(rule.name.startswith("shoulderstand_") for rule in profile.metrics)

    def _shoulderstand_gate(
        self, profile: PoseCompensationProfile, metrics: Dict[str, float]
    ) -> Optional[Dict[str, object]]:
        if not self._is_shoulderstand_profile(profile):
            return None

        is_side = any(rule.name == "shoulderstand_vertical_stack_angle" for rule in profile.metrics)
        hip_thr = 2.0 if self.level == "beginner" else 6.0
        leg_thr = 0.0 if self.level == "beginner" else 3.0
        head_thr = -4.0 if self.level == "beginner" else -2.0
        support_thr = 16.0 if self.level == "beginner" else 12.0
        stack_thr = 32.0 if self.level == "beginner" else 25.0

        for name in (
            "shoulderstand_head_offset_ratio",
            "shoulderstand_hip_over_shoulder_pct",
            "shoulderstand_knee_over_hip_pct",
            "shoulderstand_ankle_over_hip_pct",
            "shoulderstand_shoulder_support_proxy",
            "shoulderstand_vertical_stack_angle",
            "shoulderstand_head_below_shoulder_pct",
        ):
            if name in metrics:
                self._push_hist("gate:" + name, metrics[name])

        hip_over_shoulder = metrics.get("shoulderstand_hip_over_shoulder_pct", -100.0)
        knee_over_hip = metrics.get("shoulderstand_knee_over_hip_pct", -100.0)
        ankle_over_hip = metrics.get("shoulderstand_ankle_over_hip_pct", -100.0)
        head_below_shoulder = metrics.get("shoulderstand_head_below_shoulder_pct", -100.0)
        shoulder_support = metrics.get("shoulderstand_shoulder_support_proxy", 100.0)
        stack_angle = metrics.get("shoulderstand_vertical_stack_angle", 0.0)
        leg_head_shift = metrics.get("shoulderstand_leg_head_shift_pct", 0.0)

        hip_ok = hip_over_shoulder >= hip_thr
        legs_ok = knee_over_hip >= leg_thr and ankle_over_hip >= leg_thr
        head_low_ok = head_below_shoulder >= head_thr
        head_static_ok = min(
            self._stability("gate:shoulderstand_head_offset_ratio"),
            self._stability("gate:shoulderstand_head_below_shoulder_pct"),
        ) >= 0.45
        support_ok = shoulder_support <= support_thr
        stack_ok = (not is_side) or stack_angle <= stack_thr
        passed = hip_ok and legs_ok and head_low_ok and head_static_ok and support_ok and stack_ok

        gate_metrics = {
            "hip_over_shoulder": hip_over_shoulder,
            "knee_over_hip": knee_over_hip,
            "ankle_over_hip": ankle_over_hip,
            "head_below_shoulder": head_below_shoulder,
            "shoulder_support": shoulder_support,
            "stack_angle": stack_angle,
        }
        if passed:
            return {
                "passed": True,
                "state": "ready",
                "label": zh(r"\u5012\u7f6e\u6210\u7acb"),
                "reason": zh(r"\u5012\u7f6e\u95e8\u63a7\u5df2\u901a\u8fc7\uff0c\u5f00\u59cb\u80a9\u5012\u7acb\u8bc4\u5206\u3002"),
                "metrics": gate_metrics,
            }

        if not hip_ok:
            if knee_over_hip >= leg_thr or ankle_over_hip >= leg_thr:
                state = "entering"
                label = zh(r"\u8fdb\u5165\u4e2d")
                reason = zh(r"\u817f\u90e8\u5df2\u7ecf\u62ac\u9ad8\uff0c\u4f46\u9aa8\u76c6\u8fd8\u6ca1\u6709\u9ad8\u4e8e\u80a9\u90e8\uff0c\u66f4\u50cf\u4ef0\u5367\u62ac\u817f\u6216\u51c6\u5907\u9636\u6bb5\u3002")
            else:
                state = "not_entered"
                label = zh(r"\u672a\u8fdb\u5165")
                reason = zh(r"\u9acb\u90e8\u8fd8\u6ca1\u6709\u9ad8\u4e8e\u80a9\u90e8\uff0c\u5f53\u524d\u5c1a\u672a\u8fdb\u5165\u80a9\u5012\u7acb\u3002")
        elif not legs_ok:
            if leg_head_shift > 5.0:
                state = "exiting"
                label = zh(r"\u9000\u51fa\u4e2d")
                reason = zh(r"\u9acb\u90e8\u5df2\u9ad8\u4e8e\u80a9\uff0c\u4f46\u53cc\u817f\u5411\u5934\u540e\u65b9\u6389\u843d\uff0c\u66f4\u50cf\u7281\u5f0f\u6216\u80a9\u5012\u7acb\u9000\u51fa\u9636\u6bb5\u3002")
            else:
                state = "half_inverted"
                label = zh(r"\u534a\u5012\u7f6e")
                reason = zh(r"\u9acb\u90e8\u5df2\u9ad8\u4e8e\u80a9\uff0c\u4f46\u53cc\u817f\u6ca1\u6709\u7ee7\u7eed\u9ad8\u4e8e\u9acb\u90e8\uff0c\u53ef\u80fd\u662f\u534a\u5012\u7f6e\u3002")
        else:
            state = "half_inverted"
            label = zh(r"\u534a\u5012\u7f6e")
            reason = zh(r"\u5012\u7f6e\u9ad8\u5ea6\u57fa\u672c\u6210\u7acb\uff0c\u4f46\u5934\u9888\u7a33\u5b9a\u3001\u80a9\u80cc\u652f\u6491\u6216\u4fa7\u4f4d\u5782\u76f4\u5806\u53e0\u8fd8\u672a\u6ee1\u8db3\u3002")

        return {
            "passed": False,
            "state": state,
            "label": label,
            "reason": reason,
            "metrics": gate_metrics,
        }

    def _shoulderstand_cervical_flag_count(
        self, profile: PoseCompensationProfile, metrics: Dict[str, float]
    ) -> int:
        rule_names = {rule.name for rule in profile.metrics}
        if not any(name.startswith("shoulderstand_") for name in rule_names):
            return 0

        is_side = "shoulderstand_vertical_stack_angle" in rule_names
        support_thr = 12.0 if self.level == "beginner" else 8.0
        head_thr = (1.8 if self.level == "beginner" else 1.4) if is_side else (
            0.50 if self.level == "beginner" else 0.35
        )
        if is_side:
            flags = [
                metrics.get("shoulderstand_shoulder_support_proxy", 0.0) > support_thr,
                metrics.get("shoulderstand_head_offset_ratio", 0.0) > head_thr,
                metrics.get("shoulderstand_vertical_stack_angle", 0.0) > 20.0,
                metrics.get("shoulderstand_hip_height_pct", 0.0) < (-5.0 if self.level == "beginner" else 0.0),
                metrics.get("shoulderstand_lumbar_collapse_proxy", 0.0) > 12.0,
            ]
        else:
            elbow_ratio = metrics.get("shoulderstand_elbow_width_ratio", 1.0)
            flags = [
                metrics.get("shoulderstand_shoulder_support_proxy", 0.0) > support_thr,
                metrics.get("shoulderstand_head_offset_ratio", 0.0) > head_thr,
                metrics.get("shoulderstand_hip_height_pct", 0.0) < (-5.0 if self.level == "beginner" else 0.0),
                elbow_ratio < 0.7 or elbow_ratio > 1.5,
                metrics.get("shoulderstand_midline_offset_pct", 0.0) > 15.0,
                metrics.get("shoulderstand_pelvis_tilt_proxy", 0.0) > 15.0,
            ]
        return sum(1 for flag in flags if flag)

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

        if self._shoulderstand_cervical_flag_count(profile, metrics) >= 2:
            cervical_note = zh(r"\u9888\u690e\u538b\u529b\u98ce\u9669\u5347\u9ad8\uff0c\u8bf7\u9000\u51fa\u6216\u4f7f\u7528\u652f\u6491\u7248\u672c\u3002")
            if cervical_note not in notes:
                notes.insert(0, cervical_note)

        mobile_risk = mobile_sum / mobile_weight if mobile_weight else 0.0
        stiff_risk = stiff_sum / stiff_weight if stiff_weight else 0.0
        overall_risk = (
            mobile_risk * profile.mobile_group_weight + stiff_risk * profile.stiff_group_weight
        ) / (profile.mobile_group_weight + profile.stiff_group_weight)
        return float(overall_risk), float(mobile_risk), float(stiff_risk), notes, metric_scores

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

        metrics = self._compute_metrics(pts)
        gate = self._shoulderstand_gate(profile, metrics)
        if gate is not None and not bool(gate["passed"]):
            detail = {
                "risk_mobile_lock": 0.0,
                "risk_stiff_comp": 0.0,
                "score": 0.0,
                "gate_state": str(gate["state"]),
                "gate_label": str(gate["label"]),
                "gate_reason": str(gate["reason"]),
                "gate_metrics": gate["metrics"],
            }
            return 1.0, 0.0, str(gate["label"]), str(gate["reason"]), metrics, detail, {}

        risk, mobile_risk, stiff_risk, notes, metric_scores = self._score_metrics(profile, metrics)
        score = float(np.clip(100.0 * (1.0 - risk), 0.0, 100.0))
        grade, voice = self._voice_ladder(score, notes, profile)
        detail = {
            "risk_mobile_lock": mobile_risk,
            "risk_stiff_comp": stiff_risk,
            "score": score,
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
        if detail.get("gate_state"):
            report_html = self._build_gate_report_html(profile, grade, voice, detail)
        else:
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
        if detail.get("gate_state"):
            status["neck"] = "issue"
            status["shoulder_l"] = "issue"
            status["shoulder_r"] = "issue"
            status["spine"] = "issue"
            return status
        if detail.get("risk_stiff_comp", 0.0) >= 0.2:
            status["neck"] = "issue"
            status["spine"] = "issue"
            status["pelvis"] = "issue"
        if detail.get("risk_mobile_lock", 0.0) >= 0.2:
            status["shoulder_l"] = "issue"
            status["shoulder_r"] = "issue"
        return status

    def _build_gate_report_html(
        self,
        profile: PoseCompensationProfile,
        grade: str,
        voice: str,
        detail: Dict[str, float],
    ) -> str:
        gate_metrics = detail.get("gate_metrics", {})
        gate_title = zh(r"\u5012\u7f6e\u95e8\u63a7\u68c0\u6d4b")
        phase_label = zh(r"\u5f53\u524d\u9636\u6bb5\uff1a")
        prompt_label = zh(r"\u7cfb\u7edf\u63d0\u793a\uff1a")
        gate_fail = zh(r"\u95e8\u63a7\u672a\u901a\u8fc7\uff0c\u6682\u4e0d\u8fdb\u5165\u80a9\u5012\u7acb\u8bc4\u5206\u3002")
        colon = zh(r"\uff1a")
        metric_lines = [
            (zh(r"\u9acb\u9ad8\u4e8e\u80a9"), gate_metrics.get("hip_over_shoulder", 0.0), "%"),
            (zh(r"\u819d\u9ad8\u4e8e\u9acb"), gate_metrics.get("knee_over_hip", 0.0), "%"),
            (zh(r"\u8e1d\u9ad8\u4e8e\u9acb"), gate_metrics.get("ankle_over_hip", 0.0), "%"),
            (zh(r"\u5934\u9888\u4f4e\u4e8e\u80a9"), gate_metrics.get("head_below_shoulder", 0.0), "%"),
            (zh(r"\u80a9\u80cc\u652f\u6491\u504f\u5dee"), gate_metrics.get("shoulder_support", 0.0), ""),
            (zh(r"\u4fa7\u4f4d\u5782\u76f4\u5806\u53e0"), gate_metrics.get("stack_angle", 0.0), "\u00b0"),
        ]
        items = "".join(
            [
                f"<li style='color:#E2E8F0;'>{label}{colon}{value:.1f}{unit}</li>"
                for label, value, unit in metric_lines
            ]
        )
        return f"""
        <div style='font-size:14px; line-height:1.5;'>
            <h3 style='color:#F59E0B;'>{profile.title}{gate_title}</h3>
            <p><b>{phase_label}</b><span style='color:#F97316;'>{grade}</span></p>
            <p style='color:#FCA5A5;'><b>{prompt_label}</b>{gate_fail}</p>
            <ul>{items}</ul>
            <p style='color:#94A3B8;'>{voice}</p>
        </div>
        """

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
        group_label = zh(r"\u5206\u7ec4\u98ce\u9669\uff1a")
        mobile_label = zh(r"\u7075\u6d3b\u5173\u8282\u9501\u5b9a")
        stiff_label = zh(r"\u975e\u7075\u6d3b\u5173\u8282\u4ee3\u507f")
        voice_label = zh(r"\u8bed\u97f3\u7ea0\u6b63\uff1a")
        return f"""
        <div style='font-size:14px; line-height:1.5;'>
            <h3 style='color: #F59E0B;'>{profile.title}{report_title}</h3>
            <p><b>{drive_label}</b>{drive}{drive_suffix}<b>{grade_label}</b><span style="color:{grade_color};">{grade}</span></p>
            <p><b>{score_label}</b><span style="color:{grade_color};">{score:.0f}</span> / 100
            <span style="color:#94A3B8;">{risk_open} {risk * 100:.0f}%{risk_close}</span></p>
            <p><b>{group_label}</b><span style="color:#94A3B8;">{mobile_label} {detail['risk_mobile_lock'] * 100:.0f}% / {stiff_label} {detail['risk_stiff_comp'] * 100:.0f}%</span></p>
            <ul>{''.join(metric_lines)}</ul>
            <p style='color: #94A3B8;'><b>{voice_label}</b>{voice}</p>
        </div>
        """

