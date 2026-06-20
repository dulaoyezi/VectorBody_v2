# -*- coding: utf-8 -*-
"""
Topology-constrained DLS stabilization for MediaPipe pose landmarks.

This module is intentionally lightweight: it does not claim full clinical
inverse kinematics. It uses a damped least-squares projection to keep observed
landmarks close to MediaPipe while reducing virtual bone-length drift and
single-frame jitter.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Tuple

import numpy as np

from core.human_topology import HumanTopologyTree, TopologyFrame


TrackedEdge = Tuple[str, str]


@dataclass(frozen=True)
class TopologyIKResult:
    landmarks: np.ndarray
    topology: TopologyFrame
    detail: Dict[str, object]


class TopologyIKStabilizer:
    def __init__(
        self,
        history_len: int = 18,
        min_reference_samples: int = 4,
        damping: float = 0.08,
        max_iters: int = 3,
        fit_weight: float = 1.0,
        bone_weight: float = 0.35,
        temporal_weight: float = 0.18,
        correction_clip: float = 0.035,
    ):
        self.history_len = max(4, int(history_len))
        self.min_reference_samples = max(2, int(min_reference_samples))
        self.damping = float(damping)
        self.max_iters = max(1, int(max_iters))
        self.fit_weight = float(fit_weight)
        self.bone_weight = float(bone_weight)
        self.temporal_weight = float(temporal_weight)
        self.correction_clip = float(correction_clip)
        self._length_history: Dict[TrackedEdge, Deque[float]] = {
            edge: deque(maxlen=self.history_len) for edge in HumanTopologyTree.EDGES
        }
        self._prev_nodes: Dict[str, np.ndarray] = {}

    def reset(self) -> None:
        for values in self._length_history.values():
            values.clear()
        self._prev_nodes.clear()

    def stabilize(self, landmarks: np.ndarray, topology: TopologyFrame | None = None) -> TopologyIKResult:
        pts = np.asarray(landmarks, dtype=float)
        if pts.shape[0] < 33:
            raise ValueError("landmarks must contain at least 33 points")
        if topology is None:
            topology = HumanTopologyTree.build(pts)

        dims = min(3, pts.shape[1] if pts.ndim == 2 else 2)
        names = list(topology.nodes.keys())
        name_to_i = {name: i for i, name in enumerate(names)}
        obs = {
            name: np.asarray(topology.nodes[name], dtype=float)[:dims].copy()
            for name in names
        }
        x = np.concatenate([obs[name] for name in names]).astype(float)
        ref_lengths = self._reference_lengths(topology)

        initial_residual = self._rms_residual(x, names, name_to_i, obs, ref_lengths, dims)
        iterations = 0
        for iterations in range(1, self.max_iters + 1):
            residual, jacobian = self._linear_system(x, names, name_to_i, obs, ref_lengths, dims)
            lhs = jacobian.T @ jacobian + (self.damping ** 2) * np.eye(jacobian.shape[1])
            rhs = jacobian.T @ residual
            try:
                delta = -np.linalg.solve(lhs, rhs)
            except np.linalg.LinAlgError:
                delta = -np.linalg.lstsq(lhs, rhs, rcond=None)[0]
            delta_norm = float(np.linalg.norm(delta))
            if delta_norm > self.correction_clip:
                delta *= self.correction_clip / (delta_norm + 1e-6)
            x += delta
            if delta_norm < 1e-5:
                break

        corrected = self._rebuild_landmarks(pts, x, names, dims)
        corrected_topology = HumanTopologyTree.build(corrected)
        self._update_reference(corrected_topology)
        self._prev_nodes = {
            name: np.asarray(corrected_topology.nodes[name], dtype=float)[:dims].copy()
            for name in names
        }

        final_residual = self._rms_residual(x, names, name_to_i, obs, ref_lengths, dims)
        max_length_error = self._max_length_error(corrected_topology)
        detail = {
            "topology_node_count": len(corrected_topology.nodes),
            "topology_edge_count": len(corrected_topology.bones),
            "skeleton_vector_count": len(corrected_topology.bones),
            "skeleton_vector_mean_length": self._mean_bone_length(corrected_topology),
            "skeleton_vector_max_length": self._max_bone_length(corrected_topology),
            "skeleton_vector_trunk_length": self._chain_length(corrected_topology, "trunk"),
            "skeleton_vector_left_leg_length": self._chain_length(corrected_topology, "left_leg"),
            "skeleton_vector_right_leg_length": self._chain_length(corrected_topology, "right_leg"),
            "ik_enabled": True,
            "ik_method": "topology_dls",
            "ik_iterations": iterations,
            "ik_reference_ready": self._reference_ready(),
            "ik_initial_residual": initial_residual,
            "ik_final_residual": final_residual,
            "ik_max_length_error": max_length_error,
        }
        return TopologyIKResult(landmarks=corrected, topology=corrected_topology, detail=detail)

    def _linear_system(
        self,
        x: np.ndarray,
        names: list[str],
        name_to_i: Dict[str, int],
        obs: Dict[str, np.ndarray],
        ref_lengths: Dict[TrackedEdge, float],
        dims: int,
    ) -> Tuple[np.ndarray, np.ndarray]:
        residual_rows = []
        jacobian_rows = []
        var_count = len(names) * dims

        fit_scale = np.sqrt(self.fit_weight)
        for name in names:
            base = name_to_i[name] * dims
            current = x[base:base + dims]
            for d in range(dims):
                row = np.zeros(var_count, dtype=float)
                row[base + d] = fit_scale
                residual_rows.append((current[d] - obs[name][d]) * fit_scale)
                jacobian_rows.append(row)

        if self._prev_nodes:
            temporal_scale = np.sqrt(self.temporal_weight)
            for name in names:
                if name not in self._prev_nodes:
                    continue
                base = name_to_i[name] * dims
                current = x[base:base + dims]
                previous = self._prev_nodes[name]
                for d in range(dims):
                    row = np.zeros(var_count, dtype=float)
                    row[base + d] = temporal_scale
                    residual_rows.append((current[d] - previous[d]) * temporal_scale)
                    jacobian_rows.append(row)

        bone_scale = np.sqrt(self.bone_weight)
        for parent, child in HumanTopologyTree.EDGES:
            pi = name_to_i[parent] * dims
            ci = name_to_i[child] * dims
            p = x[pi:pi + dims]
            c = x[ci:ci + dims]
            vector = c - p
            length = float(np.linalg.norm(vector)) + 1e-6
            unit = vector / length
            row = np.zeros(var_count, dtype=float)
            row[pi:pi + dims] = -unit * bone_scale
            row[ci:ci + dims] = unit * bone_scale
            residual_rows.append((length - ref_lengths[(parent, child)]) * bone_scale)
            jacobian_rows.append(row)

        return np.asarray(residual_rows, dtype=float), np.vstack(jacobian_rows)

    def _reference_lengths(self, topology: TopologyFrame) -> Dict[TrackedEdge, float]:
        refs: Dict[TrackedEdge, float] = {}
        for edge in HumanTopologyTree.EDGES:
            values = self._length_history.get(edge)
            if values and len(values) >= self.min_reference_samples:
                refs[edge] = float(np.median(np.asarray(values, dtype=float)))
            else:
                refs[edge] = float(topology.bone(*edge).length)
        return refs

    def _reference_ready(self) -> bool:
        return all(len(values) >= self.min_reference_samples for values in self._length_history.values())

    def _update_reference(self, topology: TopologyFrame) -> None:
        for edge in HumanTopologyTree.EDGES:
            length = float(topology.bone(*edge).length)
            if np.isfinite(length) and length > 1e-6:
                self._length_history[edge].append(length)

    def _rebuild_landmarks(self, pts: np.ndarray, x: np.ndarray, names: list[str], dims: int) -> np.ndarray:
        corrected = pts.copy()
        name_to_i = {name: i for i, name in enumerate(names)}
        for name, index in HumanTopologyTree.RAW_LANDMARKS.items():
            base = name_to_i[name] * dims
            corrected[index, :dims] = x[base:base + dims]
        return corrected

    def _rms_residual(
        self,
        x: np.ndarray,
        names: list[str],
        name_to_i: Dict[str, int],
        obs: Dict[str, np.ndarray],
        ref_lengths: Dict[TrackedEdge, float],
        dims: int,
    ) -> float:
        residual, _ = self._linear_system(x, names, name_to_i, obs, ref_lengths, dims)
        return float(np.sqrt(np.mean(np.square(residual)))) if residual.size else 0.0

    def _max_length_error(self, topology: TopologyFrame) -> float:
        errors = []
        for edge, values in self._length_history.items():
            if not values:
                continue
            reference = float(np.median(np.asarray(values, dtype=float)))
            current = float(topology.bone(*edge).length)
            errors.append(abs(current - reference) / (reference + 1e-6))
        return float(max(errors, default=0.0))

    @staticmethod
    def _mean_bone_length(topology: TopologyFrame) -> float:
        lengths = [float(bone.length) for bone in topology.bones.values()]
        return float(np.mean(lengths)) if lengths else 0.0

    @staticmethod
    def _max_bone_length(topology: TopologyFrame) -> float:
        lengths = [float(bone.length) for bone in topology.bones.values()]
        return float(max(lengths, default=0.0))

    @staticmethod
    def _chain_length(topology: TopologyFrame, chain_name: str) -> float:
        chain = HumanTopologyTree.CHAINS.get(chain_name, ())
        total = 0.0
        for parent, child in zip(chain, chain[1:]):
            try:
                total += float(topology.bone(parent, child).length)
            except KeyError:
                continue
        return float(total)
