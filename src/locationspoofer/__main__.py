"""Startet den lokalen Server: ``python -m locationspoofer`` bzw. ``locationspoofer``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import secrets
import socket
import sys
import threading
import webbrowser
from typing import Optional

import uvicorn

from locationspoofer.device import LocationController, PymobiledeviceBackend
from locationspoofer.server import create_app

DEFAULT_PORT = 8765


def _lan_address() -> Optional[str]:
    # Verbindet einen UDP-Socket nur, um die Adresse der Standardroute zu erfahren; es wird nichts gesendet.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            return probe.getsockname()[0]
    except OSError:
        return None


def _event_loop_factory() -> asyncio.AbstractEventLoop:
    # Unter Windows bricht die Proactor-Loop (uvicorns Standard) den DTX-SSL-Handshake von pymobiledevice3,
    # siehe https://github.com/doronz88/pymobiledevice3/issues/1217.
    return asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="locationspoofer", description="Web-UI zum Simulieren des Standorts eines per USB verbundenen iPhones."
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP-Port (Standard: {DEFAULT_PORT})")
    parser.add_argument("--udid", help="UDID des iPhones, falls mehrere angeschlossen sind")
    parser.add_argument(
        "--lan",
        action="store_true",
        help="im lokalen Netz erreichbar machen (z. B. Steuerung aus Safari auf dem iPhone); nur mit Zugangstoken",
    )
    parser.add_argument("--no-browser", action="store_true", help="Browser nicht automatisch öffnen")
    parser.add_argument("-v", "--verbose", action="store_true", help="ausführliches Logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    token = secrets.token_urlsafe(16) if args.lan else None
    app = create_app(LocationController(PymobiledeviceBackend, udid=args.udid), token=token)

    local_url = f"http://127.0.0.1:{args.port}/"
    if token is not None:
        local_url = f"{local_url}login?token={token}"
        lan_address = _lan_address()
        print("LAN-Modus: Wer diesen Link kennt, kann den Standort des iPhones setzen.")
        if lan_address:
            print(f"  Im Netzwerk: http://{lan_address}:{args.port}/login?token={token}")
    print(f"  Lokal:       {local_url}")
    print("Beenden mit Strg+C (setzt den echten Standort zurück).")

    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(local_url,)).start()

    config = uvicorn.Config(
        app, host="0.0.0.0" if args.lan else "127.0.0.1", port=args.port, log_level="warning", loop="none"
    )
    try:
        with asyncio.Runner(loop_factory=_event_loop_factory) as runner:
            runner.run(uvicorn.Server(config).serve())
    except KeyboardInterrupt:
        # uvicorn löst das Signal nach dem geordneten Shutdown erneut aus; wie uvicorn.run() hier still beenden.
        pass


if __name__ == "__main__":
    main()
