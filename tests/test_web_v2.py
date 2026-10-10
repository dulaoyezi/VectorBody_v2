"""Basic smoke tests for a deployment with the full VectorBody dependencies installed."""
from fastapi.testclient import TestClient
from web_v2.app import app


def test_health_and_home():
    with TestClient(app) as client:
        r = client.get('/health')
        assert r.status_code == 200 and r.json()['ok'] is True
        assert client.get('/').status_code == 200
        assert '智瑜镜' in client.get('/').text


def test_poses_are_eight():
    with TestClient(app) as client:
        data = client.get('/poses').json()
        assert len(data['poses']) == 8
        assert data['views'] == ['front', 'side']


def test_no_unsafe_report_path():
    with TestClient(app) as client:
        assert client.get('/api/reports/../frame').status_code in (404, 405)
        assert client.get('/api/reports/bad/frame').status_code == 404
        assert client.get('/api/reports').status_code == 200