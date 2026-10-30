from __future__ import annotations

from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import PROJECT_ROOT, Settings, get_settings
from .jobs import JobManager


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config.make_directories()
        app.state.settings = config
        app.state.preview_lock = Lock()
        app.state.sample_lock = Lock()
        app.state.jobs = JobManager(config, app.state.preview_lock)
        try:
            yield
        finally:
            app.state.jobs.shutdown()

    app = FastAPI(
        title="Neural Video Studio", version="0.3.2", lifespan=lifespan,
        description="Local web UI for user-provided native DLSS feature-18 binaries."
    )
    app.include_router(router)
    ui = PROJECT_ROOT / "web"
    app.mount("/static", StaticFiles(directory=ui), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ui / "index.html")

    return app


app = create_app()
