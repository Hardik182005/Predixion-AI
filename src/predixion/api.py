"""HTTP API.

Routes are thin: validation and ownership checks here, lifecycle in RunManager,
persistence in Store. Error responses always have the shape
{"error": {"code": ..., "message": ...}} and never include provider payloads.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import Settings, get_settings
from .contracts import (
    MAX_SEED_URLS,
    QUESTION_MAX_CHARS,
    QUESTION_MIN_CHARS,
    RUN_ID_RE,
    ResearchRequest,
    RunEvent,
    RunSummary,
    RunView,
    StartRunResponse,
)
from .fixtures import sample_questions
from .logs import configure_logging, error_location, log
from .render import render_markdown
from .runs import RunError, RunManager
from .store import Store
from .urls import UnsafeURL, validate_public_url

logger = logging.getLogger("predixion.api")

MAX_BODY_BYTES = 64 * 1024
IDEMPOTENCY_KEY_MAX = 128
LOCAL_OWNER = "local"

RUN_ERROR_STATUS = {
    "live_unavailable": 503,
    "idempotency_conflict": 409,
    "capacity": 429,
    "too_many_streams": 429,
    "run_active": 409,
}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


def parse_token_hashes(raw: str | None) -> dict[str, str]:
    """'user:sha256hex,user2:sha256hex' -> {sha256hex: user}."""
    out: dict[str, str] = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        user, _, digest = pair.partition(":")
        digest = digest.strip().lower()
        if user.strip() and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
            out[digest] = user.strip()
    return out


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_owner(request: Request, authorization: Annotated[str | None, Header()] = None) -> str:
    """The user id that scopes every run read and write. Without auth, everything belongs to 'local'."""
    if request.app.state.auth_mode == "none":
        return LOCAL_OWNER
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise APIError(401, "unauthorized", "Missing bearer token.", {"WWW-Authenticate": "Bearer"})
    digest = hash_token(token.strip())
    user = None
    for known, name in request.app.state.token_hashes.items():
        if hmac.compare_digest(known, digest):
            user = name
    if user is None:
        raise APIError(401, "unauthorized", "Invalid token.", {"WWW-Authenticate": "Bearer"})
    return user


Owner = Annotated[str, Depends(current_owner)]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    token_hashes = parse_token_hashes(settings.api_token_hashes.get_secret_value() if settings.api_token_hashes else None)
    if settings.auth_mode == "token" and not token_hashes:
        raise RuntimeError("AUTH_MODE=token requires API_TOKEN_HASHES with at least one user:sha256 entry.")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = Store(settings.db_path)
        manager = RunManager(settings, store)
        await manager.start()
        app.state.store = store
        app.state.manager = manager
        log(logger, logging.INFO, "service started", mode=settings.mode, auth=settings.auth_mode, version=__version__)
        try:
            yield
        finally:
            await manager.shutdown()
            store.close()

    app = FastAPI(
        title="Predixion AI",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.env != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.env != "production" else None,
    )

    # -- middleware -----------------------------------------------------

    @app.middleware("http")
    async def guard(request: Request, call_next):
        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            return _error(413, "body_too_large", "Request body is too large.")
        if length is None and "chunked" in request.headers.get("transfer-encoding", "").lower():
            return _error(411, "length_required", "Send the request body with a Content-Length header.")
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if not request.url.path.startswith("/api/docs"):  # Swagger UI loads its assets from a CDN
            response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.startswith("/api"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
        allow_credentials=False,
        max_age=600,
    )

    # -- errors ---------------------------------------------------------

    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(RunError)
    async def _run_error(_: Request, exc: RunError) -> JSONResponse:
        headers = {"Retry-After": "10"} if RUN_ERROR_STATUS.get(exc.code) == 429 else None
        return _error(RUN_ERROR_STATUS.get(exc.code, 400), exc.code, exc.message, headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = []
        for err in exc.errors()[:5]:
            loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
            problems.append(f"{loc}: {err.get('msg', 'invalid')}" if loc else str(err.get("msg", "invalid")))
        return _error(422, "invalid_request", "; ".join(problems) or "Invalid request.")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail) if exc.status_code != 404 else "Not found.")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Exception text can quote the request body; it is logged only with LOG_CONTENT on.
        log(
            logger,
            logging.ERROR,
            "unhandled error",
            error=type(exc).__name__,
            where=error_location(exc),
            path=request.url.path,
            **({"detail": str(exc)[:500]} if settings.log_content else {}),
        )
        return _error(500, "internal_error", "Internal server error.")

    app.state.auth_mode = settings.auth_mode
    app.state.token_hashes = token_hashes

    def manager(request: Request) -> RunManager:
        return request.app.state.manager

    def store(request: Request) -> Store:
        return request.app.state.store

    def check_run_id(run_id: str) -> str:
        if not RUN_ID_RE.match(run_id):
            raise APIError(404, "not_found", "Run not found.")
        return run_id

    # -- health and config ----------------------------------------------

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request) -> JSONResponse:
        try:
            ok = store(request).ping()
        except Exception:
            ok = False
        return JSONResponse({"status": "ready" if ok else "unavailable"}, status_code=200 if ok else 503)

    @app.get("/api/config")
    async def config(_: Owner) -> dict[str, Any]:
        return {
            "version": __version__,
            "default_mode": settings.mode,
            "live_available": settings.live_available,
            "model": settings.research_model,
            "auth_mode": settings.auth_mode,
            "fault_injection": settings.fault_injection_allowed,
            "limits": {
                "question_min_chars": QUESTION_MIN_CHARS,
                "question_max_chars": QUESTION_MAX_CHARS,
                "max_seed_urls": MAX_SEED_URLS,
                "max_rounds": settings.max_rounds,
                "max_pages_per_run": settings.max_pages_per_run,
                "run_deadline_s": settings.run_deadline_s,
                "max_cost_usd_per_run": settings.max_cost_usd_per_run,
            },
        }

    @app.get("/api/samples")
    async def samples(_: Owner) -> list[dict[str, str]]:
        return sample_questions()

    # -- runs -----------------------------------------------------------

    @app.post("/api/runs", status_code=202)
    async def create_run(
        body: ResearchRequest,
        request: Request,
        user: Owner,
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> StartRunResponse:
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip()
            if not idempotency_key or len(idempotency_key) > IDEMPOTENCY_KEY_MAX or not idempotency_key.isprintable():
                raise APIError(422, "invalid_request", "Idempotency-Key must be 1-128 printable characters.")
        if body.fault is not None and not settings.fault_injection_allowed:
            raise APIError(403, "fault_injection_disabled", "Fault injection is disabled on this server.")
        for url in body.seed_urls:
            try:
                validate_public_url(url)
            except UnsafeURL as exc:
                raise APIError(422, "unsafe_url", f"Seed URL rejected: {exc}") from None
        return manager(request).start_run(body, owner=user, idempotency_key=idempotency_key)

    @app.get("/api/runs")
    async def list_runs(request: Request, user: Owner, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[RunSummary]:
        return store(request).list_runs(user, limit)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str, request: Request, user: Owner) -> RunView:
        view = store(request).get_run(check_run_id(run_id), user)
        if view is None:
            raise APIError(404, "not_found", "Run not found.")
        return view

    @app.get("/api/runs/{run_id}/events")
    async def events(
        run_id: str,
        request: Request,
        user: Owner,
        after: Annotated[int | None, Query(ge=0)] = None,
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> StreamingResponse:
        check_run_id(run_id)
        if store(request).get_status(run_id, user) is None:
            raise APIError(404, "not_found", "Run not found.")
        after_seq = after or 0
        if last_event_id and last_event_id.isdigit():
            after_seq = max(after_seq, int(last_event_id))
        mgr = manager(request)
        slot = mgr.acquire_stream(run_id)

        async def body() -> AsyncIterator[bytes]:
            try:
                yield b"retry: 3000\n\n"
                # On client disconnect Starlette cancels this generator; the finally block releases the slot.
                async for event in mgr.stream(run_id, user, after_seq):
                    yield b": ping\n\n" if event is None else _sse(event)
            finally:
                slot.release()

        # The background task releases the slot even if the body generator is never started (a client
        # that disconnects before the first byte); release is idempotent, so both paths are safe.
        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
            background=BackgroundTask(slot.release),
        )

    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    async def cancel(run_id: str, request: Request, user: Owner) -> dict[str, str]:
        status = manager(request).cancel(check_run_id(run_id), user)
        if status is None:
            raise APIError(404, "not_found", "Run not found.")
        return {"run_id": run_id, "status": status.value}

    @app.get("/api/runs/{run_id}/export")
    async def export(
        run_id: str, request: Request, user: Owner, format: Annotated[Literal["md", "json"], Query()] = "md"
    ) -> Response:
        view = store(request).get_run(check_run_id(run_id), user)
        if view is None:
            raise APIError(404, "not_found", "Run not found.")
        if view.report is None:
            raise APIError(409, "report_not_ready", "The run has not produced a report yet.")
        disposition = f'attachment; filename="predixion-{run_id}.{format}"'
        if format == "json":
            return Response(
                view.report.model_dump_json(indent=2),
                media_type="application/json",
                headers={"Content-Disposition": disposition},
            )
        return PlainTextResponse(
            render_markdown(view.report),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": disposition},
        )

    @app.get("/api/runs/{run_id}/dependencies")
    async def dependencies(
        run_id: str, request: Request, user: Owner, source: Annotated[str, Query(min_length=2, max_length=8)]
    ) -> dict[str, Any]:
        """Offline source-dependency analysis of the stored report; no provider calls."""
        from dataclasses import asdict

        from .dependencies import source_dependencies

        view = store(request).get_run(check_run_id(run_id), user)
        if view is None:
            raise APIError(404, "not_found", "Run not found.")
        if view.report is None:
            raise APIError(409, "report_not_ready", "The run has not produced a report yet.")
        try:
            analysis = source_dependencies(view.report, source)
        except KeyError:
            raise APIError(404, "unknown_source", "No such source in this report.") from None
        return asdict(analysis)

    @app.delete("/api/runs/{run_id}", status_code=204)
    async def delete(run_id: str, request: Request, user: Owner) -> Response:
        if not manager(request).delete(check_run_id(run_id), user):
            raise APIError(404, "not_found", "Run not found.")
        return Response(status_code=204)

    # -- static frontend ------------------------------------------------

    if settings.serve_frontend_dir:
        root = Path(settings.serve_frontend_dir).resolve()
        index = root / "index.html"
        if not index.is_file():
            raise RuntimeError(f"SERVE_FRONTEND_DIR has no index.html: {root}")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> Response:
            if path.startswith("api/"):
                raise APIError(404, "not_found", "Not found.")
            candidate = (root / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(root):
                headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else None
                return FileResponse(candidate, headers=headers)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def _sse(event: RunEvent) -> bytes:
    data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.seq}\nevent: {event.type.value}\ndata: {data}\n\n".encode()
