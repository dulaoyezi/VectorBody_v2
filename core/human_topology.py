# -*- coding: utf-8 -*-
"""
Human topology tree helpers for MediaPipe Pose landmarks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

import numpy as np


NodeMap = Mapping[str, np.ndarray]


@dataclass(frozen=True)
class BoneSegment:
    parent: str
    child: str
    vector: np.ndarray
    length: float
    unit: np.ndarray


@dataclass(frozen=True)
class TopologyFrame:
    nodes: Dict[str, np.ndarray]
    bones: Dict[Tuple[str, str], BoneSegment]

    def node(self, name: str) -> np.ndarray:
        return self.nodes[name]

    def bone(self, parent: str, child: str) -> BoneSegment:
        return self.bones[(parent, child)]


class HumanTopologyTree:
    """Pelvis-rooted topology tree built from MediaPipe Pose landmarks."""

    ROOT = "pelvis_center"

    RAW_LANDMARKS: Dict[str, int] = {
        "nose": 0,
        "left_ear": 7,
        "right_ear": 8,
        "left_shoulder": 11,
        "right_shoulder": 12,
        "left_elbow": 13,
        "right_elbow": 14,
        "left_wrist": 15,
        "right_wrist": 16,
        "left_hip": 23,
        "right_hip": 24,
        "left_knee": 25,
        "right_knee": 26,
        "left_ankle": 27,
        "right_ankle": 28,
        "left_heel": 29,
        "right_heel": 30,
        "left_foot_index": 31,
        "right_foot_index": 32,
    }

    EDGES: Tuple[Tuple[str, str], ...] = (
        ("pelvis_center", "shoulder_center"),
        ("shoulder_center", "head_center"),
        ("head_center", "nose"),
        ("head_center", "left_ear"),
        ("head_center", "right_ear"),
        ("shoulder_center", "left_shoulder"),
        ("left_shoulder", "left_elbow"),
        ("left_elbow", "left_wrist"),
        ("shoulder_center", "right_shoulder"),
        ("right_shoulder", "right_elbow"),
        ("right_elbow", "right_wrist"),
        ("pelvis_center", "left_hip"),
        ("left_hip", "left_knee"),
        ("left_knee", "left_ankle"),
        ("left_ankle", "left_heel"),
        ("left_ankle", "left_foot_index"),
        ("pelvis_center", "right_hip"),
        ("right_hip", "right_knee"),
        ("right_knee", "right_ankle"),
        ("right_ankle", "right_heel"),
        ("right_ankle", "right_foot_index"),
    )

    CHAINS: Dict[str, Tuple[str, ...]] = {
        "trunk": ("pelvis_center", "shoulder_center", "head_center"),
        "left_arm": ("shoulder_center", "left_shoulder", "left_elbow", "left_wrist"),
        "right_arm": ("shoulder_center", "right_shoulder", "right_elbow", "right_wrist"),
        "left_leg": ("pelvis_center", "left_hip", "left_knee", "left_ankle", "left_foot_index"),
        "right_leg": ("pelvis_center", "right_hip", "right_knee", "right_ankle", "right_foot_index"),
    }

    @classmethod
    def build(cls, landmarks: np.ndarray) -> TopologyFrame:
        pts = np.asarray(landmarks, dtype=float)
        if pts.shape[0] < 33:
            raise ValueError("landmarks must contain at least 33 points")

        nodes: Dict[str, np.ndarray] = {
            name: pts[index].copy() for name, index in cls.RAW_LANDMARKS.items()
        }
        nodes["pelvis_center"] = cls._mid(nodes, "left_hip", "right_hip")
        nodes["shoulder_center"] = cls._mid(nodes, "left_shoulder", "right_shoulder")
        nodes["head_center"] = cls._mid(nodes, "left_ear", "right_ear")
        nodes["trunk_center"] = (nodes["pelvis_center"] + nodes["shoulder_center"]) / 2.0

        bones = {
            edge: cls._make_bone(nodes, *edge)
            for edge in cls.EDGES
        }
        return TopologyFrame(nodes=nodes, bones=bones)

    @staticmethod
    def _mid(nodes: NodeMap, left: str, right: str) -> np.ndarray:
        return (np.asarray(nodes[left], dtype=float) + np.asarray(nodes[right], dtype=float)) / 2.0

    @staticmethod
    def _make_bone(nodes: NodeMap, parent: str, child: str) -> BoneSegment:
        vector = np.asarray(nodes[child], dtype=float) - np.asarray(nodes[parent], dtype=float)
        length = float(np.linalg.norm(vector))
        unit = vector / (length + 1e-6)
        return BoneSegment(parent=parent, child=child, vector=vector, length=length, unit=unit)
