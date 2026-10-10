"""Evidence snapshots and non-clinical anatomical issue localization for VectorBody Web.

Finding labels are derived from the original, pose-specific scoring rules. A single
monocular view cannot identify precise injury or infer actual muscle force.
"""
from __future__ import annotations

from pathlib import Path
import shutil

import cv2


# Aggregate regions; intentionally no left/right anatomical diagnosis is inferred.
REGION_RULES = {
    'knee': 'knees', 'ankle': 'ankles', 'heel': 'ankles', 'weight_center': 'pelvis',
    'shoulder': 'shoulders', 'thoracic': 'spine', 'spine': 'spine',
    'lumbar': 'spine', 'head': 'neck', 'cervical': 'neck', 'neck': 'neck',
    'pelvis': 'pelvis', 'hip': 'pelvis', 'core': 'spine',
    'arm': 'shoulders', 'balance': 'pelvis',
}
REGION_LABELS = {
    'knees': '膝关节', 'ankles': '踝足支撑', 'shoulders': '肩部',
    'spine': '躯干与脊柱轴线', 'neck': '头颈部', 'pelvis': '骨盆与髋部',
}


def finding_region(metric_key: str) -> str:
    for key, region in REGION_RULES.items():
        if key in metric_key:
            return region
    return 'spine'


def build_findings(metric_scores: dict, action_tag: str | None, level: str = 'normal', limit: int = 5) -> list[dict]:
    """Find poor individual-rule scores, not fabricated diagnoses.

    The labels and corrective notes, when available, come from PoseCompensationProfile.
    """
    try:
        from core.compensation_risk_engine import CompensationRiskEngine
        profile = CompensationRiskEngine.POSE_PROFILES.get(action_tag or '')
        rules = {r.name: r for r in profile.metrics} if profile else {}
    except (AttributeError, ImportError):
        rules = {}
    ranked = []
    for name, item in (metric_scores or {}).items():
        score = float(item.get('score', 100))
        if score >= 85:
            continue
        rule = rules.get(name)
        region = finding_region(name)
        ranked.append({
            'metric': name,
            'label': str(getattr(rule, 'label', name.replace('_', ' '))),
            'region': region,
            'region_label': REGION_LABELS[region],
            'severity': 'high' if score < 55 else 'medium' if score < 75 else 'attention',
            'score': round(score, 1),
            'value': round(float(item.get('value', 0)), 2),
            'weight': round(float(item.get('weight', 0)), 3),
            'advice': str(getattr(rule, 'note', '建议核对拍摄视角及动作要领，并由教师复核。')),
        })
    ranked.sort(key=lambda x: (x['score'], -x['weight']))
    return ranked[:limit]


# MediaPipe Pose convention; same joint connectivity used in the browser preview.
EDGES = ((11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
         (11, 23), (12, 24), (23, 24), (23, 25), (25, 27),
         (24, 26), (26, 28), (27, 29), (28, 30), (29, 31), (30, 32))
REGION_JOINTS = {
    'knees': (25, 26), 'ankles': (27, 28), 'shoulders': (11, 12),
    'spine': (11, 12, 23, 24), 'neck': (0, 11, 12), 'pelvis': (23, 24),
}


def render_photo(frame, max_side: int = 1280) -> bytes:
    img = frame
    height, width = img.shape[:2]
    if max(height, width) > max_side:
        scale = max_side / max(height, width)
        img = cv2.resize(img, (round(width * scale), round(height * scale)))
    ok, encoded = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
    if not ok:
        raise ValueError('无法编码评估照片')
    return encoded.tobytes()


def render_skeleton_photo(frame, landmarks: list, findings: list[dict]) -> bytes:
    img = frame.copy()
    height, width = img.shape[:2]
    def pt(i):
        x, y, visibility = landmarks[i]
        return (int(x * width), int(y * height)), float(visibility)
    for start, end in EDGES:
        a, va = pt(start); b, vb = pt(end)
        if min(va, vb) >= 0.30:
            cv2.line(img, a, b, (150, 207, 166), 3, cv2.LINE_AA)
    for i in set(v for pair in EDGES for v in pair):
        xy, confidence = pt(i)
        if confidence >= 0.30:
            cv2.circle(img, xy, 5, (75, 182, 232), -1, cv2.LINE_AA)
            cv2.circle(img, xy, 5, (40, 75, 45), 1, cv2.LINE_AA)
    for finding in findings[:3]:
        joints = REGION_JOINTS.get(finding['region'], ())
        visible = [pt(j)[0] for j in joints if pt(j)[1] >= 0.30]
        if not visible:
            continue
        x = sum(p[0] for p in visible) // len(visible)
        y = sum(p[1] for p in visible) // len(visible)
        tint = (46, 95, 217) if finding['severity'] == 'high' else (62, 165, 223)
        cv2.circle(img, (x, y), max(19, min(height, width) // 30), tint, 3, cv2.LINE_AA)
    return render_photo(img)


def photos_dir(data_dir: Path, report_id: str) -> Path:
    if len(report_id) != 12 or not all(c in '0123456789abcdef' for c in report_id):
        raise ValueError('无效报告编号')
    return data_dir / 'report_photos' / report_id


def save_photos(data_dir: Path, report_id: str, original: bytes | None, skeleton: bytes | None) -> dict:
    if not original:
        return {}
    directory = photos_dir(data_dir, report_id)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'original.jpg').write_bytes(original)
    if skeleton:
        (directory / 'skeleton.jpg').write_bytes(skeleton)
    return {
        'original': f'/api/reports/{report_id}/photos/original',
        'skeleton': f'/api/reports/{report_id}/photos/skeleton' if skeleton else None,
    }


def delete_photos(data_dir: Path, report_id: str) -> None:
    shutil.rmtree(photos_dir(data_dir, report_id), ignore_errors=True)
