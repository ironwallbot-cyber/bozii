"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from bozii import __version__
from bozii.api import (
    artifacts,
    auth,
    capabilities,
    dashboard,
    employees,
    providers,
    settings as settings_api,
    stream,
    teams,
    tasks,
    tools,
)
from bozii.api.deps import ApiError
from bozii.config import get_settings
from bozii.db import dispose_engine, init_db
from bozii.logging import setup_logging

logger = logging.getLogger("bozii.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    settings.ensure_dirs()
    await init_db()
    from bozii.db import get_session_factory
    from bozii.engine.queue import TaskQueue, set_queue

    queue = TaskQueue(get_session_factory())
    set_queue(queue)
    await queue.start()
    recovered = await queue.recover_interrupted()
    logger.info("Bozii API ready (recovered %d interrupted task(s))", recovered)
    yield
    await queue.stop()
    set_queue(None)
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Bozii API",
        description="Autonomous AI workforce platform - REST API",
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error": exc.message, "code": exc.code, "detail": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for err in exc.errors()[:20]:
            loc = ".".join(str(part) for part in err.get("loc", []) if part != "body")
            errors.append({"field": loc, "message": err.get("msg", "invalid")})
        return JSONResponse(
            status_code=422,
            content={"error": "Validation failed", "code": "validation", "detail": errors},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "code": "internal", "detail": None},
        )

    app.include_router(auth.router)
    app.include_router(employees.router)
    app.include_router(tasks.router)
    app.include_router(teams.router)
    app.include_router(tools.router)
    app.include_router(capabilities.router)
    app.include_router(artifacts.router)
    app.include_router(dashboard.router)
    app.include_router(providers.router)
    app.include_router(settings_api.router)
    app.include_router(stream.router)

    @app.get("/api", tags=["meta"])
    async def api_index() -> dict:
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "environment": settings.environment,
        }

    return app


app = create_app()

__all__ = ["app", "create_app"]
