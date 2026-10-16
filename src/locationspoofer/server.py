"""HTTP-API und Auslieferung der Web-UI."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from locationspoofer.device import DeviceError, LocationController

STATIC_DIR = Path(__file__).parent / "static"
TOKEN_COOKIE = "locationspoofer_token"
LOOPBACK_HOSTS = ["127.0.0.1", "localhost"]
FOREIGN_REQUEST = "Anfrage von fremder Seite abgelehnt."
SHUTDOWN_TIMEOUT_SECONDS = 10


class Coordinates(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


def _same_secret(given: str, expected: str) -> bool:
    return secrets.compare_digest(given.encode(), expected.encode())


def create_app(controller: LocationController, token: Optional[str] = None) -> FastAPI:
    """Ohne ``token`` nur über Loopback erreichbar; mit ``token`` (LAN-Modus) braucht die API das Token-Cookie."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        # Beim Beenden den echten Standort zurückgeben statt das iPhone im simulierten Zustand zu lassen.
        # Begrenzt, weil ein laufender Verbindungsaufbau (Pairing-Dialog) das Lock bis zu 60 s halten kann.
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(controller.disconnect(), SHUTDOWN_TIMEOUT_SECONDS)

    app = FastAPI(title="LocationSpoofer", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    # Im Loopback-Modus Schutz gegen DNS-Rebinding; im LAN-Modus übernimmt das der Token.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"] if token else LOOPBACK_HOSTS)

    def authorize(request: Request) -> None:
        # CSRF-Schutz: Browser setzen bei Anfragen fremder Seiten Sec-Fetch-Site bzw. Origin.
        if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
            raise HTTPException(403, FOREIGN_REQUEST)
        origin = request.headers.get("origin")
        if origin is not None and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            raise HTTPException(403, FOREIGN_REQUEST)
        if token is not None and not _same_secret(request.cookies.get(TOKEN_COOKIE, ""), token):
            raise HTTPException(401, "Zugangstoken fehlt. Den beim Start ausgegebenen Link öffnen.")

    @app.exception_handler(DeviceError)
    async def device_error_handler(_request: Request, exc: DeviceError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.get("/api/status", dependencies=[Depends(authorize)])
    async def status() -> dict:
        return await controller.status()

    @app.post("/api/connect", dependencies=[Depends(authorize)])
    async def connect() -> dict:
        await controller.connect()
        return await controller.status()

    @app.post("/api/location", dependencies=[Depends(authorize)])
    async def teleport(coordinates: Coordinates) -> dict:
        await controller.teleport(coordinates.latitude, coordinates.longitude)
        return await controller.status()

    @app.delete("/api/location", dependencies=[Depends(authorize)])
    async def reset() -> dict:
        await controller.reset()
        return await controller.status()

    if token is not None:

        @app.get("/login")
        async def login(token_param: str = Query("", alias="token")) -> RedirectResponse:
            if not _same_secret(token_param, token):
                raise HTTPException(401, "Ungültiger Zugangstoken.")
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(TOKEN_COOKIE, token, httponly=True, samesite="strict")
            return response

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
    return app
