
import time
from pathlib import Path

from fastapi.testclient import TestClient

from nvs.config import Settings
from nvs.main import create_app


def test_server_endpoints(tmp_path: Path) -> None:
    """Exercise uploads, queue failures, and API responses without a native runtime.

    Args:
        tmp_path (Path): The isolated temporary directory supplied by pytest.

    Returns:
        None: No value is returned.
    """
    cfg = Settings(
        data_dir=tmp_path / "data", runtime_dir=tmp_path / "runtime",
            preview_dir=tmp_path / "preview"
        )
    with TestClient(create_app(cfg)) as client:
        health = client.get('/api/health')
        assert health.status_code == 200 and health.json()['ok']
        assert client.get('/').status_code == 200
        assert client.get('/static/styles.css').status_code == 200
        assert len(client.get('/api/presets').json()) == 4
        caps = client.get('/api/capabilities').json()
        assert caps['render_available'] is False
        assert client.get('/api/jobs').json() == []

        bad = client.post('/api/uploads', files={'file': ('x.txt', b'hello')})
        assert bad.status_code == 400
        uploaded = client.post('/api/uploads', files={'file': ('example.mp4', b'fake video bytes')})
        assert uploaded.status_code == 201
        upload_id = uploaded.json()['id']
        assert len(upload_id) == 32
        assert client.get('/api/uploads/' + upload_id + '/source').status_code == 200
        queued = client.post('/api/jobs', json={'upload_id': upload_id, 'options': {'profile': 'Natural'}})
        assert queued.status_code == 201
        job_id = queued.json()['id']
        assert client.get('/api/jobs/' + job_id).status_code == 200
        for _ in range(50):
            job = client.get('/api/jobs/' + job_id).json()
            if job['status'] not in ('queued', 'running'):
                break
            time.sleep(.02)
        assert job['status'] == 'failed'  # no GPU/runtime in CI; no fake successes
        assert client.get('/api/jobs/' + job_id + '/download').status_code == 409
        assert client.post('/api/preview', json={'upload_id':upload_id}).status_code == 409
        assert client.get('/api/jobs/missing').status_code == 404
