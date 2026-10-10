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

def test_reviewer_login_protects_reports_and_supports_logout(app_module, monkeypatch):
    with TestClient(app_module.app) as client:
        assert client.get('/api/reports/unknown').status_code == 401
        assert client.get('/api/reports/unknown/photos/original').status_code == 401
        assert client.post('/api/live/start',json={'student_name':'测试'}).status_code == 401
        invalid=client.post('/api/auth/login',json={
            'email':'huanjiaceshi@163.com','password':'Wrong_password_12345'
        })
        assert invalid.status_code == 401
        cross=client.post('/api/auth/login',headers={'Origin':'https://evil.example'},json={
            'email':'huanjiaceshi@163.com',
            'password':'A_Very_Strong_Demo_Site_Password_123'
        })
        assert cross.status_code == 403
        login(client)
        rid=app_module.save_report('video','warrior2','front','normal',
                                   {'score':81,'grade':'B'},student_name='评委A')
        assert client.get('/api/reports/'+rid).json()['student_name'] == '评委A'
        monkeypatch.setenv('VECTORBODY_SHARED_ALLOW_DELETE','false')
        assert client.delete('/api/reports/'+rid).status_code == 403
        assert client.get('/api/reports/'+rid).status_code == 200
        assert client.post('/api/auth/logout').status_code == 200
        assert client.get('/api/reports').status_code == 401
        assert client.get('/',follow_redirects=False).status_code == 303


def test_name_required_and_report_search_is_exact(app_module):
    with TestClient(app_module.app) as client:
        login(client)
        assert client.post('/api/live/start',json={
            'pose':'warrior2','view':'front','level':'normal'
        }).status_code == 422
        assert client.post('/api/live/start',json={
            'pose':'warrior2','view':'front','level':'normal',
            'student_name':'a'*33
        }).status_code == 422
        assert client.post('/api/analyze-video',data={
            'student_name':'  '
        }).status_code == 422
        r1=app_module.save_report('video','warrior2','front','normal',
                                  {'score':70,'grade':'B'},student_name='评委A')
        r2=app_module.save_report('video','warrior2','front','normal',
                                  {'score':90,'grade':'A'},student_name='评委B')
        result=client.get('/api/reports',params={'student_name':'评委A'}).json()['reports']
        assert [r['id'] for r in result] == [r1]
        result=client.get('/api/reports',params={'student_name':'评委B'}).json()['reports']
        assert [r['id'] for r in result] == [r2]
        report=client.get('/api/reports/'+r2).json()
        assert report['body']['student_name'] == '评委B'
        html=client.get('/').text
        assert 'id="live-student-name"' in html
        assert 'id="video-student-name"' in html
        assert 'id="report-name-filter"' in html
        assert 'id="judge-qr-open"' in html


def test_legacy_sqlite_is_migrated_without_erasing_report(app_module, tmp_path):
    import json
    import sqlite3
    old_db=tmp_path/'original_reports.sqlite3'
    with sqlite3.connect(old_db) as c:
        c.execute("""CREATE TABLE reports(
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, source TEXT NOT NULL,
            pose TEXT NOT NULL, view TEXT NOT NULL, level TEXT NOT NULL,
            score REAL NOT NULL, grade TEXT NOT NULL, body TEXT NOT NULL
        )""")
        c.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?)',(
            'legacy001','2026-01-01T00:00:00+00:00','video','warrior2',
            'front','normal',75.0,'B',json.dumps({'score':75,'grade':'B'})
        ))
    original_db=app_module.DB
    try:
        app_module.DB=old_db
        app_module.init_db()
        app_module.init_db()  # Migration is idempotent.
        with app_module.connect_db() as c:
            columns=[r['name'] for r in c.execute('PRAGMA table_info(reports)')]
            legacy=c.execute('SELECT id,student_name,score,body FROM reports').fetchone()
            assert 'student_name' in columns
            assert legacy['id'] == 'legacy001'
            assert legacy['student_name'] == ''
            assert legacy['score'] == 75
            assert json.loads(legacy['body'])['score'] == 75
    finally:
        app_module.DB=original_db


def test_qr_encodes_only_public_https_login_link(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from shared_access import install_shared_access
    monkeypatch.setenv('VECTORBODY_TEST_PASSWORD','A_Very_Strong_Demo_Site_Password_123')
    monkeypatch.setenv('VECTORBODY_PUBLIC_URL','https://vectorbody.example.test')
    monkeypatch.delenv('VECTORBODY_COOKIE_SECURE',raising=False)
    app=FastAPI()
    install_shared_access(app,tmp_path)
    with TestClient(app,base_url='https://vectorbody.example.test') as client:
        cfg=client.get('/api/auth/config').json()
        assert cfg['email'] == 'huanjiaceshi@163.com'
        assert cfg['public_url'] == 'https://vectorbody.example.test'
        response=client.get('/api/auth/qr')
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('image/png')
        assert response.content.startswith(b'\x89PNG\r\n\x1a\n')
        assert b'A_Very_Strong_Demo_Site_Password_123' not in response.content
        login(client)
        assert client.get('/api/auth/me').json()['shared_account'] is True
