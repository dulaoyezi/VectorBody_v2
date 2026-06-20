# -*- coding: utf-8 -*-
"""
Virtual bone-length consistency checks for monocular pose landmarks.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, Tuple

import numpy as np

from core.human_topology import TopologyFrame


TrackedEdge = Tuple[str, str]


@dataclass(frozen=True)
class BoneLengthStatus:
    frame_count: int
    ready: bool
    valid: bool
    reliable: bool
    quality: float
    max_deviation: float
    updated_reference: bool
    learn_reference: bool
    learning_state: str
    reference_samples: int
    abnormal_edges: Tuple[str, ...]

    def as_detail(self) -> Dict[str, object]:
        return {
            "bone_length_frame_count": self.frame_count,
            "bone_length_ready": self.ready,
            "bone_length_valid": self.valid,
            "bone_length_reliable": self.reliable,
            "bone_length_quality": self.quality,
            "bone_length_max_deviation": self.max_deviation,
            "bone_length_updated_reference": self.updated_reference,
            "bone_length_learn_reference": self.learn_reference,
            "bone_length_learning_state": self.learning_state,
            "bone_length_reference_samples": self.reference_samples,
            "bone_length_abnormal_edges": list(self.abnormal_edges),
        }


class VirtualBoneLengthTracker:
    """Estimate stable relative bone lengths and flag abnormal landmark frames."""

    DEFAULT_TRACKED_EDGES: Tuple[TrackedEdge, ...] = (
        ("pelvis_center", "shoulder_center"),
        ("left_shoulder", "left_elbow"),
        ("left_elbow", "left_wrist"),
        ("right_shoulder", "right_elbow"),
        ("right_elbow", "right_wrist"),
        ("left_hip", "left_knee"),
        ("left_knee", "left_ankle"),
        ("right_hip", "right_knee"),
        ("right_knee", "right_ankle"),
    )

    def __init__(
        self,
        window_frames: int = 30,
        update_interval: int = 5,
        deviation_threshold: float = 0.30,
        min_samples: int = 3,
        tracked_edges: Iterable[TrackedEdge] | None = None,
    ):
        self.update_interval = max(1, int(update_interval))
        self.deviation_threshold = float(deviation_threshold)
        self.min_samples = max(1, int(min_samples))
        sample_window = max(self.min_samples, int(window_frames) // self.update_interval)
        self.tracked_edges = tuple(tracked_edges or self.DEFAULT_TRACKED_EDGES)
        self._history: Dict[TrackedEdge, Deque[float]] = {
            edge: deque(maxlen=sample_window) for edge in self.tracked_edges
        }
        self._frame_count = 0
        self._learn_frame_count = 0

    def reset(self) -> None:
        self._frame_count = 0
        self._learn_frame_count = 0
        for values in self._history.values():
            values.clear()

    def update(self, topology: TopologyFrame, learn_reference: bool = True) -> BoneLengthStatus:
        self._frame_count += 1
        if learn_reference:
            self._learn_frame_count += 1
        current = self._current_lengths(topology)
        ready_before = self._is_ready()
        deviations = self._relative_deviations(current) if ready_before else {}
        max_deviation = max(deviations.values(), default=0.0)
        abnormal_edges = tuple(
            self._edge_label(edge)
            for edge, deviation in deviations.items()
            if deviation > self.deviation_threshold
        )
        valid = not abnormal_edges
        updated = (
            bool(learn_reference)
            and (self._learn_frame_count == 1 or self._learn_frame_count % self.update_interval == 0)
            and (not ready_before or valid)
        )
        if updated:
            for edge, length in current.items():
                if np.isfinite(length) and length > 1e-6:
                    self._history[edge].append(length)
        ready = self._is_ready()
        reliable = ready and valid
        quality = (
            float(np.clip(1.0 - max_deviation / self.deviation_threshold, 0.0, 1.0))
            if ready_before
            else 0.0
        )
        if learn_reference and not ready:
            learning_state = "building"
        elif learn_reference:
            learning_state = "ready"
        elif ready:
            learning_state = "frozen"
        else:
            learning_state = "waiting_hold"
        return BoneLengthStatus(
            frame_count=self._frame_count,
            ready=ready,
            valid=valid,
            reliable=reliable,
            quality=quality,
            max_deviation=float(max_deviation),
            updated_reference=updated,
            learn_reference=bool(learn_reference),
            learning_state=learning_state,
            reference_samples=self._reference_samples(),
            abnormal_edges=abnormal_edges,
        )

    def _current_lengths(self, topology: TopologyFrame) -> Dict[TrackedEdge, float]:
        lengths: Dict[TrackedEdge, float] = {}
        for edge in self.tracked_edges:
            try:
                lengths[edge] = float(topology.bone(*edge).length)
            except KeyError:
                lengths[edge] = float("nan")
        return lengths

    def _is_ready(self) -> bool:
        return all(len(values) >= self.min_samples for values in self._history.values())

    def _reference_samples(self) -> int:
        if not self._history:
            return 0
        return min(len(values) for values in self._history.values())

    def _relative_deviations(self, current: Dict[TrackedEdge, float]) -> Dict[TrackedEdge, float]:
        deviations: Dict[TrackedEdge, float] = {}
        for edge, length in current.items():
            values = self._history.get(edge)
            if not values or not np.isfinite(length) or length <= 1e-6:
                deviations[edge] = 1.0
                continue
            reference = float(np.median(np.asarray(values, dtype=float)))
            deviations[edge] = abs(length - reference) / (reference + 1e-6)
        return deviations

    @staticmethod
    def _edge_label(edge: TrackedEdge) -> str:
        return f"{edge[0]}->{edge[1]}"
