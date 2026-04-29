import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import knowledge, reports, runs, settings as settings_api, templates
from app.config import get_settings


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    _configure_logging(s.log_level)
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    s.reports_dir.mkdir(parents=True, exist_ok=True)
    s.pdfs_dir.mkdir(parents=True, exist_ok=True)
    s.outlines_dir.mkdir(parents=True, exist_ok=True)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Insights Collect",
        version="0.1.0",
        description="Multi-agent expert-viewpoint collection & deep-analysis platform",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.frontend_url, "http://localhost:3000", "http://localhost:3001"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok", "app": s.app_name, "env": s.app_env}

    app.include_router(reports.router)
    app.include_router(templates.router)
    app.include_router(settings_api.router)
    app.include_router(runs.router)
    app.include_router(knowledge.router)
    return app


app = create_app()
