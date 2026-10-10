"""VectorBody Web: FastAPI adapter over the original, stateful algorithm engine.

Run: uvicorn web_app:app --host 0.0.0.0 --port 8000
The core algorithms remain in core/*; the PySide6 desktop application is untouched.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import mediapipe as mp
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from core.compensation_risk_engine import CompensationRiskEngine
from core.vector_body_stabilizer import VectorBodyStabilizer
from report_evidence import build_findings, render_photo, render_skeleton_photo, save_photos, delete_photos, photos_dir

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
DATA = Path(os.environ.get('VECTORBODY_DATA_DIR', str(ROOT / 'web_data')))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'reports.sqlite3'
MAX_UPLOAD_MB = int(os.environ.get('VECTORBODY_MAX_UPLOAD_MB', '120'))
MAX_LIVE_SESSIONS = 4
SESSION_TTL_SEC = 20 * 60
POSES = {
    'warrior1': '战士一式', 'warrior2': '战士二式', 'tadasana': '山式',
    'sukhasana': '简易坐', 'uttanasana': '站立前屈式', 'cobra': '眼镜蛇式',
    'balance': '平衡式', 'downward': '下犬式',
}
ALLOWED_VIDEO = {'.mp4', '.mov', '.avi', '.mkv', '.m4v', '.webm'}

app = FastAPI(title='VectorBody Web', version='1.0.0', docs_url='/api/docs', openapi_url='/api/openapi.json')
allowed = [x.strip() for x in os.getenv('VECTORBODY_CORS_ORIGINS', '').split(',') if x.strip()]
if allowed:
    app.add_middleware(CORSMiddleware, allow_origins=allowed, allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['*'])


def connect_db():
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect_db() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, source TEXT NOT NULL,
            pose TEXT NOT NULL, view TEXT NOT NULL, level TEXT NOT NULL,
            score REAL NOT NULL, grade TEXT NOT NULL, body TEXT NOT NULL)''')


init_db()


def save_report(source: str, pose: str, view: str, level: str, analysis: dict,
                photo: bytes | None = None, skeleton_photo: bytes | None = None) -> str:
    """Save a real assessment and its corresponding best-frame photo as one archive.

    Old reports without images remain readable. No original video is kept.
    """
    report_id = uuid.uuid4().hex[:12]
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    body = dict(analysis)
    try:
        body['media'] = save_photos(DATA, report_id, photo, skeleton_photo)
        with connect_db() as con:
            con.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?)', (
                report_id, stamp, source, pose, view, level,
                float(body['score']), body['grade'], json.dumps(body, ensure_ascii=False),
            ))
    except Exception:
        delete_photos(DATA, report_id)
        raise
    return report_id


def params_ok(pose: str, view: str, level: str) -> None:
    if pose not in POSES or view not in ('front', 'side') or level not in ('normal', 'beginner'):
        raise HTTPException(422, '不支持的体式、视角或难度。')


def new_pipeline(level: str):
    model = mp.solutions.pose.Pose(
        model_complexity=1, min_detection_confidence=0.5, min_tracking_confidence=0.5,
    )
    return model, VectorBodyStabilizer(), CompensationRiskEngine(level=level)


def extract(frame, model):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    rgb.flags.writeable = False
    prediction = model.process(rgb)
    if not prediction.pose_landmarks:
        return None, None
    lms = prediction.pose_landmarks.landmark
    display = [[round(float(p.x), 5), round(float(p.y), 5), round(float(p.visibility), 3)] for p in lms]
    return prediction.pose_landmarks, display


def in_view(display):
    if display is None or len(display) < 33:
        return False
    # Require visible major joints including wrists, knees, ankles and hips.
    ids = (11, 12, 15, 16, 23, 24, 25, 26, 27, 28)
    return all(
        -0.03 <= display[i][0] <= 1.03 and -0.03 <= display[i][1] <= 1.03
        and display[i][2] >= 0.30 for i in ids
    )


def centered(display, width: int, height: int):
    ids = (11, 12, 23, 24)
    x = sum(display[i][0] for i in ids) / 4
    y = sum(display[i][1] for i in ids) / 4
    # Slightly more generous than the desktop's fixed 200px circle.
    radius = 0.43 * min(width, height)
    return np.hypot((x - .5) * width, (y - .5) * height) < radius


def center_point(display):
    return np.array([
        sum(display[i][0] for i in (11, 12, 23, 24)) / 4,
        sum(display[i][1] for i in (11, 12, 23, 24)) / 4,
    ], dtype=float)


def make_result(analysis, display, frame_index=None, time_sec=None, action_tag=None, level="normal"):
    risk, score, grade, voice, metrics, detail, metric_scores = analysis
    def number(value, nd=2):
        return round(float(value), nd)
    return {
        'score': number(score), 'grade': str(grade), 'risk_pct': number(float(risk) * 100),
        'advice': str(voice),
        'dimensions': {
            's1': number(detail.get('score_joint_conformity', 0)),
            's2': number(detail.get('score_topology_stability', 0)),
            's3': number(detail.get('score_force_proxy', 0)),
        },
        'compensation': {
            'mobile_lock_pct': number(float(detail.get('risk_mobile_lock', 0)) * 100),
            'stiff_comp_pct': number(float(detail.get('risk_stiff_comp', 0)) * 100),
        },
        'confidence': {
            'ready': bool(detail.get('bone_length_ready', False)),
            'valid': bool(detail.get('bone_length_valid', False)),
            'quality_pct': number(float(detail.get('bone_length_quality', 0)) * 100),
            'max_deviation_pct': number(float(detail.get('bone_length_max_deviation', 0)) * 100),
        },
        'topology_ik': {
            'nodes': int(detail.get('topology_node_count', 0)),
            'edges': int(detail.get('topology_edge_count', 0)),
            'iterations': int(detail.get('ik_iterations', 0)),
            'initial_residual': number(detail.get('ik_initial_residual', 0), 6),
            'final_residual': number(detail.get('ik_final_residual', 0), 6),
            'max_length_error_pct': number(float(detail.get('ik_max_length_error', 0)) * 100, 3),
        },
        'hold_phase': str(detail.get('hold_phase_label', '')),
        'metrics': {
            k: {name: number(v.get(name, 0), 3) for name in ('value', 'score', 'stability', 'weight')}
            for k, v in metric_scores.items()
        },
        'issue_regions': build_findings(metric_scores, action_tag, level),
        'landmarks': display, 'frame_index': frame_index, 'time_sec': time_sec,
    }


def guidance(pose):
    base = {
        'warrior1': '请双脚前后分开，前膝对准脚尖，躯干直立，双臂上举。',
        'warrior2': '请双脚打开，前膝朝脚尖方向，双臂向两侧水平延展。',
        'tadasana': '请站立并自然延展脊柱，放松肩部，双脚均匀支撑。',
        'sukhasana': '请舒适盘坐，骨盆中正，脊柱向上延展。',
        'uttanasana': '请缓慢从髋部折叠向前屈，保持呼吸自然。',
        'cobra': '请俯卧后缓慢抬起胸口，肩膀远离耳朵，不要强行后仰。',
        'balance': '请站稳并缓慢进入平衡姿态，寻找稳定视点。',
        'downward': '请双手双脚稳定支撑，缓慢抬高骨盆，延展背部。',
    }
    return base.get(pose, '请进入动作并保持稳定。')


class LiveStart(BaseModel):
    pose: str = 'warrior2'
    view: str = 'front'
    level: str = 'normal'


class LiveState:
    def __init__(self, opts: LiveStart):
        self.opts = opts
        self.model, self.smoother, self.engine = new_pipeline(opts.level)
        self.lock = threading.Lock()
        self.phase = 'prepare'
        self.last_center = None
        self.stable_since = None
        self.last_seen = time.monotonic()
        self.best = None
        self.best_photo = None
        self.best_skeleton_photo = None
        self.frame_index = 0
        self.ready_at = None

    def close(self):
        self.model.close()


_sessions: dict[str, LiveState] = {}
_sessions_lock = threading.Lock()


def clean_sessions():
    now = time.monotonic()
    for sid, state in list(_sessions.items()):
        if now - state.last_seen > SESSION_TTL_SEC and state.lock.acquire(blocking=False):
            try:
                _sessions.pop(sid, None)
                state.close()
            finally:
                state.lock.release()


@app.get('/api/health')
def health():
    return {'ok': True, 'engine': 'VectorBody_v2', 'version': app.version}


@app.get('/api/poses')
def poses():
    return {'poses': [{'id': k, 'name': v} for k, v in POSES.items()],
            'views': ['front', 'side'], 'levels': ['normal', 'beginner']}


@app.post('/api/live/start')
def live_start(opts: LiveStart):
    params_ok(opts.pose, opts.view, opts.level)
    with _sessions_lock:
        clean_sessions()
        if len(_sessions) >= MAX_LIVE_SESSIONS:
            raise HTTPException(503, '当前实时评估会话较多，请稍后重试。')
        sid = uuid.uuid4().hex
        try:
            _sessions[sid] = LiveState(opts)
        except Exception as ex:
            raise HTTPException(503, f'姿态引擎初始化失败：{type(ex).__name__}') from ex
    return {'session_id': sid, 'phase': 'prepare', 'voice': guidance(opts.pose),
            'message': '请按语音引导进入动作，确保全身入镜。'}


@app.post('/api/live/frame')
async def live_frame(session_id: str = Form(...), frame: UploadFile = File(...)):
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(404, '会话失效，请重新开启实时评估。')
    with state.lock:
        state.last_seen = time.monotonic()
        data = await frame.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(413, '实时画面过大。')
        array = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(400, '无法解析实时画面。')
        height, width = img.shape[:2]
        if width > 1920 or height > 1080:
            img = cv2.resize(img, (min(width, 1280), min(height, 720)))
        state.frame_index += 1
        pose_data, display = extract(img, state.model)
        response = {'phase': state.phase, 'message': '正在识别动作', 'voice': None,
                    'landmarks': display, 'result': None, 'best': state.best}
        if pose_data is None or not in_view(display):
            if state.phase == 'hold':
                state.phase = 'prepare'
                state.engine.reset()
                state.smoother = VectorBodyStabilizer()
            state.stable_since = None
            state.last_center = None
            response.update(phase='framing', message='请确保全身入镜，关节不要被遮挡。')
            return response
        if not centered(display, width, height):
            if state.phase == 'hold':
                state.phase = 'prepare'
                state.engine.reset()
                state.smoother = VectorBodyStabilizer()
            state.stable_since = None
            state.last_center = None
            response.update(phase='centering', message='请移动到检测区域中央。')
            return response
        now = time.monotonic()
        current = center_point(display)
        if state.phase == 'prepare':
            if state.last_center is None or float(np.linalg.norm(current - state.last_center)) >= 0.012:
                state.stable_since = now
            state.last_center = current
            elapsed = now - (state.stable_since or now)
            if elapsed < 2.0:
                response.update(phase='stabilizing', message=f'请保持动作稳定 {min(elapsed, 2):.1f}/2.0 秒')
                return response
            state.phase = 'hold'
            state.ready_at = now
            response['voice'] = '动作稳定，开始评估。'
        state.last_center = current
        smooth = state.smoother.smooth(pose_data)
        analyzed = state.engine.analyze(smooth, f'{state.opts.pose}_{state.opts.view}')
        if analyzed is not None:
            result = make_result(analyzed, display, state.frame_index, round(now - (state.ready_at or now), 2),
                                 f'{state.opts.pose}_{state.opts.view}', state.opts.level)
            response['result'] = result
            if state.best is None or result['score'] > state.best['score']:
                state.best = result
                state.best_photo = render_photo(img)
                state.best_skeleton_photo = render_skeleton_photo(img, display, result['issue_regions'])
        response.update(phase='hold', message='正在检测 · 调整后继续保持即可重新评价', best=state.best)
        return response


@app.post('/api/live/stop')
def live_stop(session_id: str = Form(...), archive: bool = Form(True)):
    with _sessions_lock:
        state = _sessions.pop(session_id, None)
    if state is None:
        return {'ok': True, 'archived': False}
    with state.lock:
        try:
            rid = save_report('live', state.opts.pose, state.opts.view, state.opts.level, state.best,
                              state.best_photo, state.best_skeleton_photo) if archive and state.best else None
            return {'ok': True, 'archived': bool(rid), 'report_id': rid, 'best': state.best}
        finally:
            state.close()


def _analyze_video_file(path: str, pose: str, view: str, level: str):
    """CPU-heavy inference runs off the FastAPI event loop."""
    cap = None
    model = None
    try:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise HTTPException(422, '视频无法解码，建议转成H.264编码的MP4。')
        model, smoother, engine = new_pipeline(level)
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or fps < 1:
            fps = 30.0
        idx = good = processed = 0
        best = None
        best_photo = None
        best_skeleton_photo = None
        last_center = None
        stable_from = None
        stride = 2
        max_processed = 1800
        while processed < max_processed:
            ok, img = cap.read()
            if not ok or img is None:
                break
            idx += 1
            if idx % stride:
                continue
            processed += 1
            pose_data, display = extract(img, model)
            h, w = img.shape[:2]
            if pose_data is None or not in_view(display) or not centered(display, w, h):
                stable_from = None
                last_center = None
                continue
            current = center_point(display)
            t = idx / fps
            if last_center is None or np.linalg.norm(current - last_center) >= .012:
                stable_from = t
            last_center = current
            if stable_from is None or t - stable_from < 2.0:
                continue
            smooth = smoother.smooth(pose_data)
            analyzed = engine.analyze(smooth, f'{pose}_{view}')
            if analyzed is None:
                continue
            good += 1
            result = make_result(analyzed, display, idx, round(t, 2), f'{pose}_{view}', level)
            if best is None or result['score'] > best['score']:
                best = result
                best_photo = render_photo(img)
                best_skeleton_photo = render_skeleton_photo(img, display, result['issue_regions'])
        if best is None:
            raise HTTPException(422, '未找到稳定2秒以上的有效姿态。请确认全身入镜、正侧位和动作选择正确。')
        rid = save_report('video', pose, view, level, best, best_photo, best_skeleton_photo)
        return {'ok': True, 'report_id': rid,
                'pose': {'id': pose, 'name': POSES[pose], 'view': view, 'level': level},
                'result': best,
                'video': {'processed_frames': processed, 'evaluated_frames': good,
                          'best_frame': best['frame_index'], 'best_time_sec': best['time_sec']},
                'notice': '仅用于教学辅助，不替代教师判断或医疗诊断。'}
    finally:
        if cap is not None:
            cap.release()
        if model is not None:
            model.close()


@app.post('/api/analyze-video')
async def analyze_video(
    file: UploadFile = File(...), pose: str = Form('warrior2'),
    view: str = Form('front'), level: str = Form('normal'),
):
    params_ok(pose, view, level)
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in ALLOWED_VIDEO:
        raise HTTPException(415, '视频格式不支持，请选择MP4、MOV、AVI、MKV或WebM。')
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as out:
            path = out.name
            total = 0
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(413, f'文件不能超过{MAX_UPLOAD_MB}MB。')
                out.write(chunk)
        return await run_in_threadpool(_analyze_video_file, path, pose, view, level)
    finally:
        if path and os.path.exists(path):
            os.remove(path)
        await file.close()


@app.get('/api/reports')
def list_reports():
    with connect_db() as con:
        rows = con.execute('SELECT id,created_at,source,pose,view,level,score,grade FROM reports ORDER BY created_at DESC LIMIT 100').fetchall()
    return {'reports': [dict(r) | {'has_photo': (photos_dir(DATA, r['id']) / 'original.jpg').is_file()} for r in rows]}


@app.get('/api/reports/{report_id}')
def get_report(report_id: str):
    with connect_db() as con:
        row = con.execute('SELECT * FROM reports WHERE id=?', (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, '记录不存在')
    obj = dict(row)
    obj['body'] = json.loads(obj['body'])
    return obj


@app.delete('/api/reports/{report_id}')
def delete_report(report_id: str):
    with connect_db() as con:
        cur = con.execute('DELETE FROM reports WHERE id=?', (report_id,))
    if cur.rowcount:
        delete_photos(DATA, report_id)
    return {'ok': cur.rowcount > 0}


@app.get('/api/reports/{report_id}/photos/{kind}')
def report_photo(report_id: str, kind: str):
    if kind not in ('original', 'skeleton'):
        raise HTTPException(404, '照片类型不存在')
    with connect_db() as con:
        report = con.execute('SELECT id FROM reports WHERE id=?', (report_id,)).fetchone()
    if not report:
        raise HTTPException(404, '报告不存在')
    try:
        path = photos_dir(DATA, report_id) / f'{kind}.jpg'
    except ValueError:
        raise HTTPException(404, '报告不存在')
    if not path.is_file():
        raise HTTPException(404, '该报告没有保存对应照片')
    return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control': 'private, no-store',
                                                               'X-Content-Type-Options': 'nosniff'})


@app.get('/api/anatomy/{orientation}/{layer}')
def anatomy_image(orientation: str, layer: str):
    if orientation not in ('front', 'back') or layer not in ('skeleton', 'muscle'):
        raise HTTPException(404, '解剖视图不存在')
    path = ROOT / 'assets' / f'{orientation}_{layer}.png'
    if not path.is_file():
        raise HTTPException(404, '原始解剖示意图文件不存在')
    return FileResponse(path, media_type='image/png')


@app.get('/')
def index():
    return FileResponse(WEB / 'index.html')


@app.get('/web/{asset_path:path}')
def web_asset(asset_path: str):
    path = (WEB / asset_path).resolve()
    if WEB.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)