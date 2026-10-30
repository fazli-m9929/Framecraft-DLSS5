from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from nvs.config import Settings
from nvs.main import create_app
from nvs.schemas import JobView, RenderOptions, Status


def test_completed_render_can_be_sampled_and_downloaded(tmp_path: Path) -> None:
    """Exercise full-result serving and cached FFmpeg browser sample generation.

    Args:
        tmp_path (Path): The isolated temporary directory supplied by pytest.

    Returns:
        None: No value is returned.
    """
    data = tmp_path / "data"
    config = Settings(data_dir=data, runtime_dir=tmp_path / "runtime", preview_dir=tmp_path / "preview")
    output = data / "outputs"
    output.mkdir(parents=True, exist_ok=True)
    video = output / "demo.mp4"
    ffmpeg = config.resolve_command("ffmpeg")
    assert ffmpeg is not None
    proc = subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24:duration=2',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    with TestClient(create_app(config)) as client:
        record = JobView(id="done", upload_id="source", filename="demo.mp4",
                         options=RenderOptions(), status=Status.COMPLETED, output_filename="demo.mp4")
        with client.app.state.jobs.lock:
            client.app.state.jobs.jobs[record.id] = record
        assert client.get('/api/jobs/done/video').status_code == 200
        result = client.get('/api/jobs/done/sample')
        assert result.status_code == 200
        assert result.headers['content-type'].startswith('video/mp4')
        assert result.content[:4] != b''
        assert (data / 'samples' / 'done.mp4').is_file()
        assert client.get('/api/jobs/done/sample').status_code == 200
        assert client.get('/api/jobs/absent/sample').status_code == 404


def test_new_ui_is_english_and_has_viewer_tabs(tmp_path: Path) -> None:
    """Verify the editor page exposes the expected viewer and render controls.

    Args:
        tmp_path (Path): The isolated temporary directory supplied by pytest.

    Returns:
        None: No value is returned.
    """
    config = Settings(data_dir=tmp_path / 'data', runtime_dir=tmp_path / 'runtime',
                      preview_dir=tmp_path / 'preview')
    with TestClient(create_app(config)) as client:
        html = client.get('/').text
        assert '<html lang="en">' in html
        assert 'Framecraft' in html
        assert 'id="resultPlayer"' in html
        assert 'data-tab="deliver"' in html
        assert 'id="renderButton"' in html
        assert client.get('/api/health').json()['version'] == '0.3.2'


def test_recipe_ui_has_all_choices_and_frame_rate_is_outside_custom_panel(tmp_path: Path) -> None:
    """Verify recipe choices and the independent frame-rate control appear in the UI.

    Args:
        tmp_path (Path): The isolated temporary directory supplied by pytest.

    Returns:
        None: No value is returned.
    """
    from fastapi.testclient import TestClient

    from nvs.config import Settings
    from nvs.export_presets import RECIPES
    from nvs.main import create_app
    with TestClient(create_app(Settings(data_dir=tmp_path / "d"))) as client:
        html = client.get("/").text
        for name in RECIPES:
            assert name in html
        assert html.index('id="targetFps"') > html.index('id="customExportFields"')
