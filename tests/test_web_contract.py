"""API contract tests using an explicit deterministic engine stub.

They test routing, archiving and lifecycle, NOT the accuracy of real MediaPipe inference.
"""
from __future__ import annotations

import importlib
import io
import os
import sys
import types

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient


class Landmark:
    def __init__(self, i):
        self.x = .25 + (i % 6) * .08
        self.y = .12 + (i // 6) * .12
        self.z = .01
        self.visibility = .99


class FakePose:
    def __init__(self, **kwargs):
        pass
    def process(self, frame):
        return types.SimpleNamespace(pose_landmarks=types.SimpleNamespace(landmark=[Landmark(i) for i in range(33)]))
    def close(self):
        return None


class FakeSmoother:
    def smooth(self, pose):
        return np.array([[p.x, p.y, p.z] for p in pose.landmark], dtype=float)


class FakeEngine:
    def __init__(self, level='normal'):
        self.level = level
    def reset(self):
        pass
    def analyze(self, points, action_tag):
        detail = {'score_joint_conformity':80, 'score_topology_stability':75,
                  'score_force_proxy':90, 'risk_mobile_lock':.1, 'risk_stiff_comp':.2,
                  'topology_node_count':23, 'topology_edge_count':21,
                  'ik_iterations':3, 'ik_final_residual':.004,
                  'bone_length_ready':True, 'bone_length_valid':True, 'bone_length_quality':.9}
        metrics = {'knee_front_flex':{'value':90,'score':82,'stability':.8,'weight':.2}}
        return (.18, 82, 'B', '保持膝关节对齐。', {}, detail, metrics)


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv('VECTORBODY_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('VECTORBODY_TEST_PASSWORD','A_Very_Strong_Demo_Site_Password_123')
    monkeypatch.setenv('VECTORBODY_COOKIE_SECURE','false')
    monkeypatch.setenv('VECTORBODY_SHARED_ALLOW_DELETE','true')
    monkeypatch.delenv('VECTORBODY_PUBLIC_URL',raising=False)
    mp = types.ModuleType('mediapipe')
    mp.solutions = types.SimpleNamespace(pose=types.SimpleNamespace(Pose=FakePose))
    core = types.ModuleType('core'); core.__path__ = []
    risk = types.ModuleType('core.compensation_risk_engine'); risk.CompensationRiskEngine=FakeEngine
    stabilizer=types.ModuleType('core.vector_body_stabilizer');stabilizer.VectorBodyStabilizer=FakeSmoother
    monkeypatch.setitem(sys.modules,'mediapipe',mp)
    monkeypatch.setitem(sys.modules,'core',core)
    monkeypatch.setitem(sys.modules,'core.compensation_risk_engine',risk)
    monkeypatch.setitem(sys.modules,'core.vector_body_stabilizer',stabilizer)
    sys.modules.pop('web_app',None)
    root = os.path.dirname(os.path.dirname(__file__))
    monkeypatch.syspath_prepend(root)
    module = importlib.import_module('web_app')
    return module


def jpg_frame():
    image=np.full((480,640,3),128,dtype=np.uint8)
    ok, encoded=cv2.imencode('.jpg',image)
    assert ok
    return encoded.tobytes()


def login(client):
    response=client.post('/api/auth/login',json={
        'email':'huanjiaceshi@163.com',
        'password':'A_Very_Strong_Demo_Site_Password_123',
    })
    assert response.status_code == 200, response.text
    assert response.cookies.get('vb_test_session')
    return response


def test_index_health_and_no_fabricated_score(app_module):
    with TestClient(app_module.app) as client:
        assert client.get('/',follow_redirects=False).status_code == 303
        assert client.get('/login').status_code == 200
        assert client.get('/api/reports').status_code == 401
        assert client.get('/api/docs').status_code == 401
        assert client.get('/api/auth/config').json()['email'] == 'huanjiaceshi@163.com'
        login(client)
        assert client.get('/').status_code == 200
        assert 'VectorBody' in client.get('/').text
        assert client.get('/api/health').json()['ok'] is True
        assert len(client.get('/api/poses').json()['poses']) == 8
        assert client.get('/api/reports').json()['reports'] == []


def test_live_session_stabilizes_then_archives(app_module):
    with TestClient(app_module.app) as client:
        login(client)
        started=client.post('/api/live/start',json={'pose':'warrior2','view':'front','level':'beginner','student_name':'评委01'})
        assert started.status_code == 200
        sid=started.json()['session_id']
        result=client.post('/api/live/frame',data={'session_id':sid},files={'frame':('test.jpg',jpg_frame(),'image/jpeg')}).json()
        assert result['result'] is None
        state=app_module._sessions[sid]
        state.stable_since=app_module.time.monotonic()-3
        result=client.post('/api/live/frame',data={'session_id':sid},files={'frame':('test.jpg',jpg_frame(),'image/jpeg')}).json()
        assert result['result']['score'] == 82
        stopped=client.post('/api/live/stop',data={'session_id':sid,'archive':'true'}).json()
        assert stopped['archived'] is True
        rid=stopped['report_id']
        report=client.get('/api/reports/'+rid).json()
        assert report['body']['dimensions']['s1'] == 80
        assert report['source']=='live'
        assert report['student_name'] == '评委01'
        assert report['body']['student_name'] == '评委01'
        assert client.get('/api/reports?student_name='+ '%E8%AF%84%E5%A7%9401').json()['reports'][0]['id'] == rid
        assert client.delete('/api/reports/'+rid).json()['ok'] is True


def test_video_must_have_valid_hold_window(app_module,tmp_path):
    path=tmp_path/'sample.avi'
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),30.0,(640,480))
    if not writer.isOpened(): pytest.skip('video writer codec unavailable')
    for _ in range(110):writer.write(np.full((480,640,3),170,dtype=np.uint8))
    writer.release()
    with TestClient(app_module.app) as client:
        login(client)
        r=client.post('/api/analyze-video',data={'pose':'warrior2','view':'front','level':'normal','student_name':'视频测试学生'}, files={'file':('sample.avi',path.read_bytes(),'video/x-msvideo')})
        assert r.status_code == 200, r.text
        data=r.json()
        assert data['result']['score'] == 82
        assert data['video']['best_time_sec'] >= 2.0
        reports=client.get('/api/reports').json()['reports']
        assert len(reports) == 1
        assert reports[0]['student_name'] == '视频测试学生'

def test_new_reports_have_best_frame_photos_and_findings(app_module):
    with TestClient(app_module.app) as client:
        login(client)
        started = client.post('/api/live/start', json={'pose':'warrior2','view':'front','level':'normal','student_name':'照片测试'}).json()
        sid = started['session_id']
        client.post('/api/live/frame', data={'session_id':sid}, files={'frame':('frame.jpg',jpg_frame(),'image/jpeg')})
        state = app_module._sessions[sid]
        state.stable_since = app_module.time.monotonic() - 3
        scored = client.post('/api/live/frame', data={'session_id':sid}, files={'frame':('frame.jpg',jpg_frame(),'image/jpeg')}).json()['result']
        assert scored['issue_regions'][0]['region'] == 'knees'
        stopped = client.post('/api/live/stop', data={'session_id':sid,'archive':'true'}).json()
        rid = stopped['report_id']
        report = client.get(f'/api/reports/{rid}').json()
        assert report['body']['media']['original'].endswith('/original')
        assert report['body']['media']['skeleton'].endswith('/skeleton')
        for kind in ('original','skeleton'):
            res = client.get(f'/api/reports/{rid}/photos/{kind}')
            assert res.status_code == 200
            assert res.headers['content-type'].startswith('image/jpeg')
            assert len(res.content) > 1000
        assert client.get('/api/reports').json()['reports'][0]['has_photo']
        assert client.delete(f'/api/reports/{rid}').status_code == 200
        assert not app_module.photos_dir(app_module.DATA, rid).exists()
        assert client.get(f'/api/reports/{rid}/photos/original').status_code == 404


def test_old_reports_without_photos_remain_readable(app_module):
    with TestClient(app_module.app) as client:
        login(client)
        rid = app_module.save_report('video', 'warrior2','front','normal', {'score':72,'grade':'B'})
        report = client.get(f'/api/reports/{rid}').json()
        assert report['body']['media'] == {}
        assert client.get('/api/reports').json()['reports'][0]['has_photo'] is False
        assert client.get(f'/api/reports/{rid}/photos/original').status_code == 404
        assert client.get('/api/anatomy/side/skeleton').status_code == 404
