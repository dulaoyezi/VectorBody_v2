# -*- coding: utf-8 -*-
"""
Headless web API adapter for VectorBody_v2.

This service reuses the existing VectorBody core pipeline without PySide6/SAPI:
video -> MediaPipe Pose -> OneEuroFilter -> topology/DLS -> compensation scoring.

It is intended for teaching-demo/reviewer use, not medical diagnosis.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from typing import Literal

import cv2
import mediapipe as mp
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from core.compensation_risk_engine import CompensationRiskEngine
from core.vector_body_stabilizer import VectorBodyStabilizer


POSES = {
    "warrior1": "战士一式",
    "warrior2": "战士二式",
    "tadasana": "山式",
    "sukhasana": "简易坐",
    "uttanasana": "站立前屈式",
    "cobra": "眼镜蛇式",
    "balance": "平衡式",
    "downward": "下犬式",
}

app = FastAPI(
    title="VectorBody Web API",
    version="1.0",
    description="教学辅助用单目视觉瑜伽动作评估接口",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # reviewer demo; tighten to the final frontend domain for production
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "service": "VectorBody Web API", "mode": "teaching_assessment"}


@app.get("/poses")
def poses():
    return {
        "poses": [{"id": k, "name": v} for k, v in POSES.items()],
        "views": ["front", "side"],
        "levels": ["normal", "beginner"],
    }


@app.post("/analyze-video")
def analyze_video(
    file: UploadFile = File(...),
    pose: str = Query("warrior2"),
    view: Literal["front", "side"] = Query("front"),
    level: Literal["normal", "beginner"] = Query("normal"),
    frame_stride: int = Query(2, ge=1, le=8),
    max_frames: int = Query(1800, ge=60, le=6000),
):
    if pose not in POSES:
        raise HTTPException(status_code=400, detail=f"Unsupported pose: {pose}")

    suffix = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    tmp_path = None
    cap = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened():
            raise HTTPException(status_code=400, detail="视频无法打开，请检查格式或编码。")

        mp_pose = mp.solutions.pose
        pose_model = mp_pose.Pose(
            model_complexity=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        stabilizer = VectorBodyStabilizer()
        engine = CompensationRiskEngine(level=level)
        action_tag = f"{pose}_{view}"

        best = None
        processed = 0
        detected = 0
        frame_index = 0

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 1e-6:
            fps = 30.0

        while processed < max_frames:
            ok, frame = cap.read()
            if not ok or frame is None:
                break

            frame_index += 1
            if frame_index % frame_stride != 0:
                continue
            processed += 1

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = pose_model.process(rgb)
            if not result.pose_landmarks:
                continue
            detected += 1

            points = stabilizer.smooth(result.pose_landmarks)
            analysis = engine.analyze(points, action_tag)
            if analysis is None:
                continue

            risk, score, grade, voice, metrics, detail, metric_scores = analysis
            candidate = {
                "score": round(float(score), 2),
                "grade": str(grade),
                "risk": round(float(risk) * 100.0, 2),
                "advice": str(voice),
                "frame_index": int(frame_index),
                "time_sec": round(float(frame_index / fps), 2),
                "dimensions": {
                    "joint_conformity": round(float(detail.get("score_joint_conformity", 0.0)), 2),
                    "topology_stability": round(float(detail.get("score_topology_stability", 0.0)), 2),
                    "force_proxy": round(float(detail.get("score_force_proxy", 0.0)), 2),
                },
                "compensation": {
                    "mobile_lock_risk": round(float(detail.get("risk_mobile_lock", 0.0)) * 100.0, 2),
                    "stiff_comp_risk": round(float(detail.get("risk_stiff_comp", 0.0)) * 100.0, 2),
                },
                "confidence": {
                    "bone_length_ready": bool(detail.get("bone_length_ready", False)),
                    "bone_length_valid": bool(detail.get("bone_length_valid", False)),
                    "bone_length_quality": round(float(detail.get("bone_length_quality", 0.0)) * 100.0, 2),
                    "bone_length_max_deviation": round(float(detail.get("bone_length_max_deviation", 0.0)) * 100.0, 2),
                },
                "topology_ik": {
                    "node_count": int(detail.get("topology_node_count", 0)),
                    "edge_count": int(detail.get("topology_edge_count", 0)),
                    "ik_iterations": int(detail.get("ik_iterations", 0)),
                    "ik_initial_residual": round(float(detail.get("ik_initial_residual", 0.0)), 6),
                    "ik_final_residual": round(float(detail.get("ik_final_residual", 0.0)), 6),
                    "ik_max_length_error": round(float(detail.get("ik_max_length_error", 0.0)) * 100.0, 3),
                    "skeleton_vector_mean_length": round(float(detail.get("skeleton_vector_mean_length", 0.0)), 6),
                    "trunk_chain_length": round(float(detail.get("skeleton_vector_trunk_length", 0.0)), 6),
                    "left_leg_chain_length": round(float(detail.get("skeleton_vector_left_leg_length", 0.0)), 6),
                    "right_leg_chain_length": round(float(detail.get("skeleton_vector_right_leg_length", 0.0)), 6),
                },
                "hold": {
                    "phase": str(detail.get("hold_phase_label", "")),
                    "motion_ratio": round(float(detail.get("hold_motion_ratio", 0.0)), 6),
                },
                "metric_scores": {
                    name: {
                        "value": round(float(item.get("value", 0.0)), 3),
                        "score": round(float(item.get("score", 0.0)), 2),
                        "stability": round(float(item.get("stability", 0.0)), 3),
                        "weight": round(float(item.get("weight", 0.0)), 3),
                    }
                    for name, item in metric_scores.items()
                },
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate

        pose_model.close()

        if best is None:
            raise HTTPException(
                status_code=422,
                detail="未获得有效评分。请确认全身入镜、动作/正侧位选择正确，并保持动作稳定。",
            )

        return {
            "ok": True,
            "engine": "VectorBody_v2",
            "purpose": "teaching_assessment",
            "pose": {"id": pose, "name": POSES[pose], "view": view, "level": level},
            "video": {
                "filename": file.filename,
                "processed_frames": processed,
                "detected_frames": detected,
                "best_frame": best["frame_index"],
                "best_time_sec": best["time_sec"],
            },
            "result": best,
            "notice": "结果用于瑜伽教学辅助与动作学习反馈，不用于疾病诊断或医疗决策。",
        }

    finally:
        if cap is not None:
            cap.release()
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
