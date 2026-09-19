"""Local signaling server for the web app's modular Pipecat voice route.

Run with ``uv run --frozen python server.py``. The Next.js server is the only
browser-facing entry point; provider credentials stay in this process.
"""

import asyncio
from contextlib import asynccontextmanager, suppress
import ipaddress
import logging
import os
import sys
from types import SimpleNamespace
from typing import Annotated, Any, Callable, Literal, Mapping

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from voice_config import ConfigurationError, load_practice_environment, read_config, read_gradium_config
from provider_errors import FailureReporter

PROXY_HEADER = "practice-web"
MAX_BODY_BYTES = 256_000


def error_response(status: int, code: str, message: str, missing=None):
    error: dict[str, Any] = {"code": code, "message": message}
    if missing is not None:
        error["missing"] = list(missing)
    return JSONResponse({"error": error}, status_code=status)


class OfferBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    sdp: Annotated[str, Field(min_length=1, max_length=200_000)]
    type: Literal["offer"]
    pc_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    restart_pc: bool | None = None


class CandidateBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    candidate: Annotated[str, Field(max_length=4096)]
    sdp_mid: Annotated[str, Field(max_length=100)]
    sdp_mline_index: Annotated[int, Field(ge=0, le=100)]


class PatchBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    pc_id: Annotated[str, Field(min_length=1, max_length=200)]
    candidates: Annotated[list[CandidateBody], Field(max_length=64)]


class SessionManager:
    """Serialize signaling and keep at most one billable pipeline alive."""

    def __init__(self, handler, session_factory: Callable):
        self.handler = handler
        self.session_factory = session_factory
        self.session = None
        self.task: asyncio.Task | None = None
        self.active_route = None
        self.lock = asyncio.Lock()

    @property
    def active_sessions(self):
        return int(self.session is not None)

    async def _run(self, session):
        try:
            await session.run()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            reporter = getattr(session, "reporter", None) or FailureReporter()
            reporter.report(SimpleNamespace(error="Session failed", exception=error, processor=None))
        finally:
            with suppress(Exception):
                await session.close()
            if self.session is session:
                self.session = None
                self.task = None
                self.active_route = None

    async def offer(self, body: OfferBody, config, route="pipecat"):
        from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequest

        async with self.lock:
            if self.session is not None and (
                route != self.active_route or body.pc_id != self.session.connection.pc_id
            ):
                raise HTTPException(409)
            if body.pc_id and self.session is None:
                raise HTTPException(404)

            callback_failed = False

            async def connected(connection):
                nonlocal callback_failed
                try:
                    session = self.session_factory(connection, config)
                    self.session = session
                    self.active_route = route
                    self.task = asyncio.create_task(self._run(session), name="practice-voice-session")

                    @connection.event_handler("closed")
                    async def on_closed(_connection):
                        await session.close()
                except Exception:
                    callback_failed = True
                    await connection.disconnect()

            try:
                async with asyncio.timeout(30):
                    answer = await self.handler.handle_web_request(
                        request=SmallWebRTCRequest(**body.model_dump()),
                        webrtc_connection_callback=connected,
                    )
                # The SDK logs and suppresses callback exceptions, so check our
                # own flag before returning an answer for a nonexistent bot.
                if callback_failed or not answer:
                    raise RuntimeError("Pipeline could not be initialized")
                return answer
            except BaseException:
                await self._close_unlocked()
                raise

    async def patch(self, body: PatchBody, route="pipecat"):
        from pipecat.transports.smallwebrtc.request_handler import IceCandidate, SmallWebRTCPatchRequest

        async with self.lock:
            if self.session is None or route != self.active_route or body.pc_id != self.session.connection.pc_id:
                raise HTTPException(404)
            await self.handler.handle_patch_request(SmallWebRTCPatchRequest(
                pc_id=body.pc_id,
                candidates=[IceCandidate(**candidate.model_dump()) for candidate in body.candidates],
            ))

    async def _close_unlocked(self):
        session, task = self.session, self.task
        if session is not None:
            with suppress(Exception):
                async with asyncio.timeout(10):
                    await session.close()
        if task and task is not asyncio.current_task():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
        with suppress(Exception):
            async with asyncio.timeout(10):
                await self.handler.close()
        self.session = None
        self.task = None
        self.active_route = None

    async def close(self):
        async with self.lock:
            await self._close_unlocked()


def create_app(*, environment: Mapping[str, str] | None = None, handler=None, session_factory=None):
    if environment is None:
        environment = os.environ
    if handler is None:
        from pipecat.transports.smallwebrtc.request_handler import ConnectionMode, SmallWebRTCRequestHandler

        handler = SmallWebRTCRequestHandler(connection_mode=ConnectionMode.SINGLE)
    if session_factory is None:
        # Import while starting the server, not during an offer request.
        from voice_pipeline import VoiceSession

        session_factory = VoiceSession
    manager = SessionManager(handler, session_factory)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await manager.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sessions = manager

    @app.middleware("http")
    async def local_proxy_only(request: Request, call_next):
        try:
            loopback = bool(request.client) and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            loopback = False
        if (
            not loopback
            or request.headers.get("x-pipecat-proxy") != PROXY_HEADER
            or request.headers.get("origin") is not None
        ):
            response = error_response(403, "FORBIDDEN", "Use the voice practice web app to access this service.")
        elif request.method in ("POST", "PATCH"):
            if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
                response = error_response(415, "INVALID_REQUEST", "A JSON request body is required.")
            else:
                # Enforce the bound while reading, including chunked bodies.
                parts, total = [], 0
                async for part in request.stream():
                    total += len(part)
                    if total > MAX_BODY_BYTES:
                        break
                    parts.append(part)
                if total > MAX_BODY_BYTES:
                    response = error_response(413, "INVALID_REQUEST", "The signaling request is too large.")
                else:
                    request._body = b"".join(parts)
                    response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_body(_request, _error):
        # FastAPI's default validation response echoes the rejected input.
        return error_response(400, "INVALID_REQUEST", "The signaling request is invalid.")

    def route_health(config_reader):
        result = {
            "status": "ok",
            "configured": True,
            "missing": [],
            "activeSessions": manager.active_sessions,
        }
        try:
            config_reader(environment)
        except ConfigurationError as error:
            result["configured"] = False
            result["missing"] = list(error.missing)
            result["configError"] = not bool(error.missing)
        return result

    @app.get("/health")
    async def health():
        return route_health(read_config)

    @app.get("/gradium/health")
    async def gradium_health():
        return route_health(read_gradium_config)

    async def route_offer(body, route):
        try:
            config = read_gradium_config(environment) if route == "gradium" else read_config(environment)
        except ConfigurationError as error:
            if error.missing:
                return error_response(503, "MISSING_CONFIG", str(error), error.missing)
            hint = "Check GENERALCOMPUTE_BASE_URL, GRADIUM_REGION, and PROVIDER_TIMEOUT_MS." if route == "gradium" else "Check SAMBANOVA_BASE_URL and PROVIDER_TIMEOUT_MS."
            return error_response(503, "INVALID_CONFIG", hint)
        try:
            return await manager.offer(body, config, route)
        except HTTPException as error:
            if error.status_code == 409:
                return error_response(409, "SESSION_BUSY", "End the existing modular voice session before starting another.")
            if error.status_code == 404:
                return error_response(404, "SESSION_NOT_FOUND", "The voice session ended. Start a new session.")
            return error_response(400, "INVALID_REQUEST", "The signaling request could not be accepted.")
        except Exception:
            return error_response(502, "CONNECTION_FAILED", "The modular voice session could not start. Check the local server and provider configuration.")

    @app.post("/api/offer")
    async def offer(body: OfferBody):
        return await route_offer(body, "pipecat")

    @app.post("/api/gradium/offer")
    async def gradium_offer(body: OfferBody):
        return await route_offer(body, "gradium")

    async def route_patch(body, route):
        try:
            await manager.patch(body, route)
            return {"status": "success"}
        except HTTPException:
            return error_response(404, "SESSION_NOT_FOUND", "The voice session ended. Start a new session.")
        except Exception:
            return error_response(502, "CONNECTION_FAILED", "The WebRTC connection could not be updated.")

    @app.patch("/api/offer")
    async def patch(body: PatchBody):
        return await route_patch(body, "pipecat")

    @app.patch("/api/gradium/offer")
    async def gradium_patch(body: PatchBody):
        return await route_patch(body, "gradium")

    return app


def configure_safe_logging():
    # Pipecat providers can log raw response bodies, transcripts, and exceptions.
    # Only fixed application status messages are admitted in this local runner.
    logger.remove()
    logger.add(
        sys.stderr,
        filter=lambda record: record["extra"].get("practice_status") is True,
        format="{time:HH:mm:ss} | {level} | {message}",
        backtrace=False,
        diagnose=False,
    )
    logging.disable(logging.CRITICAL)


def run_local_server(app):
    import uvicorn

    class PracticeServer(uvicorn.Server):
        def _log_started_message(self, listeners):
            # Uvicorn invokes this only after the listening socket binds.
            print(
                "Pipecat backend is ready at http://127.0.0.1:7860. Keep this terminal running; "
                "open the Next.js web app to connect. Press Ctrl+C to stop.", flush=True,
            )

    server = PracticeServer(uvicorn.Config(app, host="127.0.0.1", port=7860, access_log=False, log_level="warning"))
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    if not server.started:
        raise SystemExit(3)


def main():
    configure_safe_logging()
    try:
        load_practice_environment()
        print("Initializing the local Pipecat backend…", flush=True)
        app = create_app()
        run_local_server(app)
        print("Pipecat backend stopped. Run 'npm run dev:pipecat' from practice to start it again.", flush=True)
    except SystemExit as error:
        if error.code not in (None, 0):
            print(
                "Pipecat could not start on 127.0.0.1:7860. Check whether another process is using port 7860 "
                "and whether this terminal is allowed to open a local listening socket.",
                file=sys.stderr, flush=True,
            )
        raise
    except Exception:
        print(
            "Pipecat could not initialize. Run 'uv sync --frozen --cache-dir .cache/uv' in pipecat-readiness, "
            "check the environment file, and restart the backend. Provider exception details are omitted.",
            file=sys.stderr, flush=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
