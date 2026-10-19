import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from . import __version__
from .db import now
from .models import Policy, RestoreConfirm, RestorePreview, Schedule, Settings, Source
from .schedules import upcoming
from .events import EventRejected, IntakeUnavailable, verify_signature
from .models import TriggerEvent
from .service import Service
from .vault import public


STATIC = Path(__file__).parent / "static"


def create_app(directory=None, adapter=None, worker=True):
    service = Service(directory or os.environ.get("SIMAX_DATA_DIR", "data"), adapter)

    @asynccontextmanager
    async def lifespan(app):
        if worker:
            service.start()
        yield
        service.close()

    app = FastAPI(title="SimaX Database Backup", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.state.service = service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if request.headers.get("x-simax-request") != "1" or (
                origin and urlsplit(origin).netloc != request.headers.get("host")
            ):
                return JSONResponse({"detail": "Same-origin SimaX request required."}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(LookupError)
    async def missing(request, error):
        return JSONResponse({"detail": "Record not found."}, status_code=404)

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request, error):
        return JSONResponse({"detail": "That name already exists or a referenced record is unavailable."}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def validation(request, error):
        # Do not echo submitted fields (a user may accidentally submit a secret).
        messages = [f"{'.'.join(str(v) for v in e['loc'][1:]) or 'Request'}: {e['msg']}" for e in error.errors()]
        return JSONResponse({"detail": "; ".join(messages)}, status_code=422)

    @app.get("/api/state")
    def state():
        return {"version": __version__, "time": now(),
                "runtime": "degraded" if service.runtime_error else "running" if service.thread and service.thread.is_alive() else "stopped",
                "runtime_error": service.runtime_error, "tools": service.adapter.availability(),
                "data_directory": str(service.directory),
                **{key: public(service.store.all(key)) for key in ["sources", "policies", "runs", "artifacts", "audit", "trigger_state"]},
                "settings": service.store.get("settings", "general")}

    @app.post("/api/sources", status_code=201)
    def add_source(body: Source):
        return public(service.save_source(body.model_dump()))

    @app.put("/api/sources/{key}")
    def edit_source(key: str, body: Source):
        return public(service.save_source(body.model_dump(), key))

    @app.post("/api/sources/{key}/preflight")
    def preflight(key: str):
        return service.preflight(key)

    @app.post("/api/schedules/preview")
    def schedule_preview(body: Schedule):
        return {"timezone": body.timezone, "occurrences": upcoming(body.model_dump()),
                "horizon_years": 8}

    @app.post("/api/triggers/webhook/{key}")
    async def webhook(key: str, request: Request):
        policy = await run_in_threadpool(service.store.get, "policies", key)
        if policy["trigger"] != "webhook":
            return JSONResponse({"detail": "Webhook policy not found."}, status_code=404)
        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > 4096:
                return JSONResponse({"detail": "Event body exceeds 4096 bytes."}, status_code=413)
            payload.extend(chunk)
        try:
            timestamp_text = request.headers.get("x-simax-timestamp", "")
            if not timestamp_text.isascii() or not timestamp_text.isdigit() or len(timestamp_text) > 12:
                raise EventRejected("Invalid event timestamp.")
            signature = request.headers.get("x-simax-signature", "")
            verify_signature(policy, int(timestamp_text), signature, bytes(payload))
        except (ValueError, TypeError):
            return JSONResponse({"detail": "Event authentication failed. Check signature, timestamp and configured secret."}, status_code=401)
        try:
            event = TriggerEvent.model_validate_json(payload)
        except ValueError:
            return JSONResponse({"detail": "Expected only an event_id (1–128 letters, digits, dot, underscore, colon or hyphen)."}, status_code=422)
        try:
            result = await run_in_threadpool(service.events.receive, policy, event.event_id, "webhook")
        except EventRejected as error:
            return JSONResponse({"detail": str(error)}, status_code=409)
        except IntakeUnavailable:
            return JSONResponse({"detail": "Event intake is full. Retry later with the same event ID."}, status_code=503)
        return JSONResponse(result, status_code=409 if result["status"] == "duplicate" else 202)

    @app.post("/api/policies", status_code=201)
    def add_policy(body: Policy):
        return public(service.save_policy(body.model_dump()))

    @app.put("/api/policies/{key}")
    def edit_policy(key: str, body: Policy):
        return public(service.save_policy(body.model_dump(), key))

    @app.post("/api/policies/{key}/run", status_code=202)
    def run(key: str):
        return public(service.enqueue(key))

    @app.post("/api/runs/{key}/cancel")
    def cancel(key: str):
        return public(service.cancel(key))

    @app.post("/api/restore/preview")
    def restore_preview(body: RestorePreview):
        return public(service.preview_restore(body.artifact_id, body.target_id))

    @app.post("/api/restore/confirm", status_code=202)
    def restore_confirm(body: RestoreConfirm):
        return public(service.confirm_restore(body.token, body.target_name, body.acknowledge_code))

    @app.put("/api/settings")
    def settings(body: Settings):
        with service.store.connect() as db:
            result = service.store.put("settings", {"id": "general", **body.model_dump()}, db)
            service.store.audit("Display and freshness settings updated", "Settings", db=db)
        return result

    @app.get("/api/audit/export")
    def audit_export():
        return JSONResponse(service.store.all("audit"), headers={"Content-Disposition": 'attachment; filename="simax-audit.json"'})

    @app.get("/api/artifacts/{key}/manifest")
    def manifest(key: str):
        artifact = service.store.get("artifacts", key)
        artifact.pop("relative_path", None)
        return JSONResponse(artifact, headers={"Content-Disposition": f'attachment; filename="{artifact["id"]}.json"'})

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
