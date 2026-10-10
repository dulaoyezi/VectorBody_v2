"""VectorBody Web v2: real algorithms, video upload, camera sessions and reports.

Run from the repository root: python -m uvicorn web_v2.app:app --host 127.0.0.1 --port 8000
The existing core modules are imported unchanged; PySide6 and SAPI are not used.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cv2
import mediapipe as mp
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.compensation_risk_engine import CompensationRiskEngine
from core.vector_body_stabilizer import VectorBodyStabilizer

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).with_name("static")
DATA = Path(os.getenv("VECTORBODY_DATA_DIR", str(ROOT / "reports" / "web"))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "reports.sqlite3"
POSES = {
    "warrior1": "战士一式", "warrior2": "战士二式", "tadasana": "山式",
    "sukhasana": "简易坐", "uttanasana": "站立前屈式", "cobra": "眼镜蛇式",
    "balance": "平衡式", "downward": "下犬式",
}
EDGES = [(11, 13), (13, 15), (12, 14), (14, 16), (11, 12),
         (11, 23), (12, 24), (23, 24), (23, 25), (25, 27),
         (24, 26), (26, 28), (27, 31), (28, 32)]
JOINTS = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
MAX_UPLOAD = 120 * 1024 * 1024
MAX_JPEG = 1024 * 1024
NOTICE = "仅用于瑜伽动作学习辅助，不用于医疗诊断；S3为视觉支撑代理，不代表真实受力。"


def connect_db():
    connection = sqlite3.connect(DB, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with connect_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, source TEXT NOT NULL,
            pose TEXT NOT NULL, view TEXT NOT NULL, level TEXT NOT NULL,
            score REAL NOT NULL, grade TEXT NOT NULL, result_json TEXT NOT NULL
        )""")


init_db()
app = FastAPI(title="智瑜镜 · VectorBody Web", version="2.0", description=NOTICE)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "engine": "VectorBody_v2", "features": ["video", "webcam", "reports"]}


@app.get("/poses")
def poses():
    return {"poses": [{"id": key, "name": value} for key, value in POSES.items()],
            "views": ["front", "side"], "levels": ["normal", "beginner"]}


def validate_choice(pose: str, view: str, level: str):
    if pose not in POSES or view not in ("front", "side") or level not in ("normal", "beginner"):
        raise ValueError("体式、拍摄视角或难度无效")


def paint(frame: np.ndarray, points: list[list[float]]) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    for a, b in EDGES:
        if points[a][3] >= 0.5 and points[b][3] >= 0.5:
            cv2.line(out, (int(points[a][0] * w), int(points[a][1] * h)),
                     (int(points[b][0] * w), int(points[b][1] * h)), (90, 125, 65), 3)
    for x, y, _, vis in points:
        if vis >= 0.5:
            cv2.circle(out, (int(x * w), int(y * h)), 3, (44, 195, 218), -1)
    return out


class Pipeline:
    """A stateful algorithm instance per video or per WebSocket connection."""
    def __init__(self, pose: str, view: str, level: str):
        validate_choice(pose, view, level)
        self.pose_name, self.view, self.level = pose, view, level
        self.model = mp.solutions.pose.Pose(model_complexity=1,
            min_detection_confidence=0.5, min_tracking_confidence=0.5)
        self.filter = VectorBodyStabilizer()
        self.engine = CompensationRiskEngine(level=level)
        self.last_points = None
        self.valid_count = 0

    def close(self):
        self.model.close()

    def process(self, frame: np.ndarray) -> dict:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.model.process(rgb)
        if not result.pose_landmarks:
            self.last_points = None
            return {"valid": False, "reason": "未识别到人体，请站入画面", "landmarks": []}
        lm = result.pose_landmarks.landmark
        points = [[float(p.x), float(p.y), float(p.z), float(p.visibility)] for p in lm]
        coords = np.asarray(points)
        visible = float(np.mean(coords[list(JOINTS), 3]))
        valid = (len(points) == 33 and visible >= 0.60
                 and np.all(coords[list(JOINTS), :2] >= 0.025)
                 and np.all(coords[list(JOINTS), :2] <= 0.975))
        if not valid:
            self.last_points = None
            return {"valid": False, "reason": "请确保全身入镜、无遮挡并保持距离", "landmarks": points,
                    "visibility": round(visible, 3)}
        movement = 0.0 if self.last_points is None else float(np.mean(
            np.linalg.norm(coords[list(JOINTS), :2] - self.last_points, axis=1)))
        self.last_points = coords[list(JOINTS), :2].copy()
        self.valid_count += 1
        stabilized = self.filter.smooth(result.pose_landmarks)
        raw = self.engine.analyze(stabilized, f"{self.pose_name}_{self.view}")
        if raw is None:
            return {"valid": False, "reason": "当前动作无法进行有效评估", "landmarks": points}
        risk, score, grade, voice, metrics, detail, metric_scores = raw
        bone_ready = bool(detail.get("bone_length_ready", False))
        bone_valid = bool(detail.get("bone_length_valid", False))
        # Insufficient bone reference is explicitly marked; an invalid established reference cannot score.
        reliable = not (bone_ready and not bone_valid)
        return {
            "valid": reliable, "reason": "" if reliable else "虚拟骨长一致性异常，请重新入镜",
            "landmarks": points, "visibility": round(visible, 3), "movement": movement,
            "score": round(float(score), 2), "grade": str(grade),
            "risk": round(float(risk) * 100, 2), "advice": str(voice),
            "dimensions": {
                "joint_conformity": round(float(detail["score_joint_conformity"]), 2),
                "topology_stability": round(float(detail["score_topology_stability"]), 2),
                "force_proxy": round(float(detail["score_force_proxy"]), 2),
            },
            "compensation": {
                "mobile_lock_risk": round(float(detail["risk_mobile_lock"]) * 100, 2),
                "stiff_comp_risk": round(float(detail["risk_stiff_comp"]) * 100, 2),
            },
            "confidence": {"landmark_visibility": round(visible * 100, 1),
                "bone_length_ready": bone_ready, "bone_length_valid": bone_valid,
                "bone_length_quality": round(float(detail.get("bone_length_quality", 0)) * 100, 2)},
            "topology_ik": {"node_count": int(detail.get("topology_node_count", 0)),
                "edge_count": int(detail.get("topology_edge_count", 0)),
                "iterations": int(detail.get("ik_iterations", 0)),
                "final_residual": round(float(detail.get("ik_final_residual", 0)), 7)},
            "hold": {"ready": bool(detail.get("hold_ready", False)),
                     "phase": str(detail.get("hold_phase", "")),
                     "label": str(detail.get("hold_phase_label", ""))},
            "metric_scores": {key: {name: round(float(v), 4) for name, v in item.items()}
                              for key, item in metric_scores.items()},
        }


def archive(source: str, pose: str, view: str, level: str, result: dict, frame: np.ndarray) -> dict:
    report_id = uuid4().hex
    image_path = DATA / f"{report_id}.jpg"
    if not cv2.imwrite(str(image_path), frame):
        raise RuntimeError("最佳帧图片写入失败")
    created_at = datetime.now(timezone.utc).isoformat()
    stored = {"id": report_id, "created_at": created_at, "source": source,
              "pose": {"id": pose, "name": POSES[pose], "view": view, "level": level},
              "result": result, "best_frame_url": f"/api/reports/{report_id}/frame", "notice": NOTICE}
    with connect_db() as conn:
        conn.execute("INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?)", (
            report_id, created_at, source, pose, view, level,
            result["score"], result["grade"], json.dumps(stored, ensure_ascii=False)))
    return stored


@app.get("/api/reports")
def reports(limit: int = Query(50, ge=1, le=100)):
    with connect_db() as conn:
        rows = conn.execute("SELECT result_json FROM reports ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"items": [json.loads(row["result_json"]) for row in rows]}


@app.get("/api/reports/{report_id}")
def report(report_id: str):
    with connect_db() as conn:
        row = conn.execute("SELECT result_json FROM reports WHERE id=?", (report_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "报告不存在")
    return json.loads(row["result_json"])


@app.get("/api/reports/{report_id}/frame")
def report_frame(report_id: str):
    if len(report_id) != 32 or any(c not in "0123456789abcdef" for c in report_id):
        raise HTTPException(404, "图片不存在")
    path = DATA / f"{report_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "图片不存在")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=60"})


@app.post("/analyze-video")
def analyze_video(file: UploadFile = File(...), pose: str = Query("warrior2"),
                  view: str = Query("front"), level: str = Query("normal"),
                  max_frames: int = Query(2400, ge=60, le=12000)):
    try:
        validate_choice(pose, view, level)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    suffix = Path(file.filename or "video.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".avi", ".mkv", ".m4v"}:
        raise HTTPException(415, "仅支持 MP4/MOV/AVI/MKV/M4V 文件")
    temp_path = None
    cap = None
    pipeline = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = Path(tmp.name)
            count = 0
            while chunk := file.file.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_UPLOAD:
                    raise HTTPException(413, "视频文件超过120MB限制")
                tmp.write(chunk)
        cap = cv2.VideoCapture(str(temp_path))
        if not cap.isOpened():
            raise HTTPException(422, "视频无法打开，请检查视频编码")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30)
        fps = fps if 1 <= fps <= 240 else 30.0
        pipeline = Pipeline(pose, view, level)
        best, best_image, timeline = None, None, []
        processed, detected, first_stable = 0, 0, None
        stable_prev = None
        while processed < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            processed += 1  # true frame-by-frame traversal, no frame_stride
            item = pipeline.process(frame)
            if not item["valid"]:
                first_stable, stable_prev = None, None
                continue
            detected += 1
            if stable_prev is not None and item["movement"] > 0.025:
                first_stable = None
            if first_stable is None:
                first_stable = processed
            stable_prev = processed
            stable_sec = (processed - first_stable) / fps
            if stable_sec < 2.0:
                continue
            if len(timeline) < 300:
                timeline.append({"time_sec": round(processed / fps, 2), "score": item["score"]})
            if best is None or item["score"] > best["score"]:
                best = {key: value for key, value in item.items() if key not in ("landmarks", "movement")}
                best["frame_index"] = processed
                best["time_sec"] = round(processed / fps, 2)
                best_image = paint(frame, item["landmarks"])
        if best is None or best_image is None:
            raise HTTPException(422, "未找到连续稳定2秒且可可靠评分的全身动作，请检查入镜范围和动作选择")
        saved = archive("video", pose, view, level, best, best_image)
        saved["video"] = {"filename": Path(file.filename or "video").name,
                          "processed_frames": processed, "detected_frames": detected,
                          "duration_processed_sec": round(processed / fps, 2), "timeline": timeline}
        return saved
    finally:
        if pipeline:
            pipeline.close()
        if cap:
            cap.release()
        if temp_path:
            temp_path.unlink(missing_ok=True)
        file.file.close()


@app.websocket("/ws/assess")
async def assess(ws: WebSocket):
    await ws.accept()
    pipeline = None
    best = best_image = None
    try:
        options = await ws.receive_json()
        pose, view, level = (options.get("pose"), options.get("view"), options.get("level"))
        try:
            validate_choice(pose, view, level)
        except ValueError:
            await ws.send_json({"error": "无效的动作、视角或难度"})
            await ws.close(code=1008)
            return
        pipeline = Pipeline(pose, view, level)
        phase, stable_since, advice_until, last_message = "guide", None, 0, 0
        last_frame = 0
        await ws.send_json({"phase": phase, "message": f"请准备{POSES[pose]}，调整摄像头使全身入镜"})
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            raw = message.get("bytes")
            if raw is None:
                continue
            if len(raw) > MAX_JPEG:
                await ws.send_json({"phase": "framing", "message": "单帧数据过大"})
                continue
            now = time.monotonic()
            if now - last_frame < 0.14:
                continue
            last_frame = now
            arr = np.frombuffer(raw, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                await ws.send_json({"phase": "framing", "message": "无法解码摄像头画面"})
                continue
            item = await asyncio.to_thread(pipeline.process, frame)
            phase = "framing" if phase == "guide" else phase
            if not item["valid"]:
                stable_since = None
                phase = "framing"
                await ws.send_json({"phase": phase, "message": item["reason"], "landmarks": item["landmarks"]})
                continue
            if phase == "advice" and now < advice_until:
                await ws.send_json({"phase": phase, "message": "根据纠正建议调整后再测", "landmarks": item["landmarks"]})
                continue
            if phase == "advice" and now >= advice_until:
                phase, stable_since = "reassess", None
                await ws.send_json({"phase": phase, "message": "开始再次评估，请保持动作稳定",
                                    "landmarks": item["landmarks"]})
                continue
            if item["movement"] > 0.025:
                stable_since = None
            if stable_since is None:
                stable_since = now
            held = now - stable_since
            phase = "stabilizing"
            if held < 2.0:
                await ws.send_json({"phase": phase, "message": f"保持动作稳定 {held:.1f}/2.0秒",
                                    "landmarks": item["landmarks"], "progress": min(1.0, held / 2)})
                continue
            phase = "scoring"
            await ws.send_json({"phase": phase, "message": "正在评估", "landmarks": item["landmarks"]})
            result = {key: value for key, value in item.items() if key not in ("landmarks", "movement")}
            best = result if best is None or result["score"] > best["score"] else best
            if best is result:
                best_image = paint(frame, item["landmarks"])
            phase, stable_since, advice_until = "advice", None, now + 4.0
            await ws.send_json({"phase": phase, "message": "评估完成，请根据建议调整", "result": result,
                                "landmarks": item["landmarks"]})
    except WebSocketDisconnect:
        pass
    except Exception:
        # Avoid leaking implementation details to a public WebSocket client.
        try:
            await ws.send_json({"error": "实时分析发生错误，请检查服务日志"})
        except Exception:
            pass
        raise
    finally:
        if pipeline:
            pipeline.close()
        if best is not None and best_image is not None:
            archive("camera", pose, view, level, best, best_image)