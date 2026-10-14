"""Verbindung zum iPhone und Standort-Simulation über Apples DVT-Dienst.

Die simulierte Position gilt nur, solange die DVT-Verbindung offen ist. Deshalb hält
das Backend Tunnel, DVT-Kanal und LocationSimulation-Kanal dauerhaft offen, bis
``close()`` aufgerufen wird oder das Gerät verschwindet.
"""

from __future__ import annotations

import asyncio
import logging
import math
from contextlib import AsyncExitStack, suppress
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Optional, Protocol
from urllib.error import URLError

from packaging.version import Version
from pymobiledevice3.exceptions import (
    AlreadyMountedError,
    ConnectionFailedToUsbmuxdError,
    ConnectionTerminatedError,
    CryptexdError,
    DeveloperDiskImageNotFoundError,
    DeveloperModeIsNotEnabledError,
    DeviceNotFoundError,
    NoDeviceConnectedError,
    PairingDialogResponsePendingError,
    PasswordRequiredError,
    TSSError,
    UserDeniedPairingError,
    UserspaceTunnelUnavailableError,
)
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
from pymobiledevice3.services.amfi import AmfiService
from pymobiledevice3.services.cryptexd import fetch_cryptex_ddi
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.mobile_image_mounter import (
    CRYPTEX_IMAGE_MIN_VERSION,
    PERSONALIZED_IMAGE_MIN_VERSION,
    auto_mount,
    fetch_personalized_ddi,
)

logger = logging.getLogger(__name__)

# Der Userspace-Tunnel (ohne Admin-Rechte) braucht den CoreDeviceProxy-Dienst, den es erst ab 17.4 gibt.
MIN_IOS_VERSION = Version("17.4")
PAIR_TIMEOUT_SECONDS = 60
UNEXPECTED_ERROR_PREFIX = "Unerwarteter Fehler"

DEVELOPER_MODE_HINT = (
    "Der Entwicklermodus ist aus. Auf dem iPhone: Einstellungen › Datenschutz & Sicherheit › "
    "Entwicklermodus einschalten, Neustart bestätigen und nach dem Entsperren „Aktivieren“ wählen."
)


class DeviceError(Exception):
    """Fehler, dessen Meldung direkt in der UI angezeigt werden kann."""


@dataclass(frozen=True)
class DeviceInfo:
    udid: str
    name: Optional[str]
    ios_version: str
    product_type: Optional[str]


class Backend(Protocol):
    async def open(self, udid: Optional[str]) -> DeviceInfo: ...

    async def set_location(self, latitude: float, longitude: float) -> None: ...

    async def clear_location(self) -> None: ...

    async def close(self) -> None: ...

    def is_alive(self) -> bool: ...


def _prefetch_developer_disk_image(ios_version: str) -> None:
    """Lädt das passende DDI in den Cache von pymobiledevice3.

    ``auto_mount`` lädt fehlende Images synchron herunter. Läuft das im Event-Loop, steht
    währenddessen auch der Userspace-Tunnel still. Deshalb wird vorher in einem Thread geladen,
    sodass ``auto_mount`` nur noch den Cache liest.
    """
    version = Version(ios_version)
    if version >= CRYPTEX_IMAGE_MIN_VERSION:
        fetch_cryptex_ddi()
    elif version >= PERSONALIZED_IMAGE_MIN_VERSION:
        fetch_personalized_ddi()


class PymobiledeviceBackend:
    """Echtes Gerät per USB: Userspace-Tunnel, DDI-Mount, DVT-LocationSimulation."""

    def __init__(self) -> None:
        self._stack: Optional[AsyncExitStack] = None
        self._tunnel: Optional[UserspaceRsdTunnel] = None
        self._location: Optional[LocationSimulation] = None

    async def open(self, udid: Optional[str]) -> DeviceInfo:
        info = await self._inspect(udid)
        await asyncio.to_thread(_prefetch_developer_disk_image, info.ios_version)

        stack = AsyncExitStack()
        try:
            tunnel = UserspaceRsdTunnel(serial=info.udid, autopair=True, remotepairing_fallback=False)
            rsd = await stack.enter_async_context(tunnel)
            try:
                await auto_mount(rsd)
            except AlreadyMountedError:
                logger.info("Developer Disk Image ist bereits gemountet")
            dvt = await stack.enter_async_context(DvtProvider(rsd))
            location = await stack.enter_async_context(LocationSimulation(dvt))
        except BaseException:
            await stack.aclose()
            raise

        self._stack, self._tunnel, self._location = stack, tunnel, location
        return info

    async def _inspect(self, udid: Optional[str]) -> DeviceInfo:
        """Pairing, iOS-Version und Entwicklermodus über eine normale Lockdown-Verbindung prüfen.

        Das passiert vor dem Tunnel, damit diese typischen Einrichtungsprobleme eine
        verständliche Meldung bekommen statt eines Tunnel-Fehlers.
        """
        lockdown = await create_using_usbmux(serial=udid, autopair=True, pair_timeout=PAIR_TIMEOUT_SECONDS)
        try:
            ios_version = lockdown.product_version
            if Version(ios_version) < MIN_IOS_VERSION:
                raise DeviceError(f"iOS {ios_version} wird nicht unterstützt (mindestens iOS {MIN_IOS_VERSION}).")
            if lockdown.has_developer_mode and not await lockdown.get_developer_mode_status():
                # Der Schalter erscheint in den Einstellungen erst, nachdem ein Host ihn freigeschaltet hat.
                with suppress(Exception):
                    await AmfiService(lockdown).reveal_developer_mode_option_in_ui()
                raise DeviceError(DEVELOPER_MODE_HINT)
            return DeviceInfo(
                udid=lockdown.udid,
                name=lockdown.all_values.get("DeviceName"),
                ios_version=ios_version,
                product_type=lockdown.product_type,
            )
        finally:
            await lockdown.close()

    async def set_location(self, latitude: float, longitude: float) -> None:
        if self._location is None:
            raise DeviceError("Keine Verbindung zum iPhone.")
        await self._location.set(latitude, longitude)

    async def clear_location(self) -> None:
        if self._location is None:
            raise DeviceError("Keine Verbindung zum iPhone.")
        await self._location.clear()

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self._tunnel = self._location = None
        if stack is None:
            return
        try:
            await stack.aclose()
        except Exception:
            # Nach einem abgezogenen Kabel scheitert das Aufräumen typischerweise; das Gerät ist ohnehin weg.
            logger.debug("Aufräumen der Geräteverbindung fehlgeschlagen", exc_info=True)

    def is_alive(self) -> bool:
        # Der Tunnel baut sich selbst ab (rsd -> None), sobald der USB-Transport endet.
        return self._tunnel is not None and self._tunnel.rsd is not None


def describe_error(error: BaseException) -> str:
    """Übersetzt Fehler aus pymobiledevice3 in eine Meldung mit konkretem nächsten Schritt."""
    if isinstance(error, DeviceError):
        return str(error)
    if isinstance(error, ConnectionFailedToUsbmuxdError):
        return (
            "Der USB-Dienst für iPhones läuft nicht. Windows: iTunes installieren (bringt den Apple Mobile Device "
            "Service mit). Linux: usbmuxd installieren und starten."
        )
    if isinstance(error, (NoDeviceConnectedError, DeviceNotFoundError)):
        return "Kein iPhone per USB gefunden. Kabel prüfen und das iPhone entsperren."
    if isinstance(error, PairingDialogResponsePendingError):
        return "Auf dem iPhone „Diesem Computer vertrauen?“ mit „Vertrauen“ bestätigen und erneut verbinden."
    if isinstance(error, UserDeniedPairingError):
        return (
            "Das Pairing wurde auf dem iPhone abgelehnt. Kabel kurz trennen und beim nächsten Dialog „Vertrauen“ "
            "wählen."
        )
    if isinstance(error, PasswordRequiredError):
        return "Das iPhone ist gesperrt. Entsperren und erneut verbinden."
    if isinstance(error, DeveloperModeIsNotEnabledError):
        return DEVELOPER_MODE_HINT
    if isinstance(error, UserspaceTunnelUnavailableError):
        return f"Für den Tunnel ohne Admin-Rechte ist mindestens iOS {MIN_IOS_VERSION} nötig."
    if isinstance(error, TSSError):
        return f"Apple hat die Personalisierung des Developer Disk Image abgelehnt ({error})."
    if isinstance(error, (CryptexdError, DeveloperDiskImageNotFoundError)):
        return (
            f"Das Developer Disk Image ließ sich nicht installieren ({error}). pymobiledevice3 aktualisieren und "
            "erneut versuchen."
        )
    if isinstance(error, URLError) or type(error).__module__.startswith("requests"):
        return "Download fehlgeschlagen. Für das Developer Disk Image wird eine Internetverbindung gebraucht."
    if isinstance(error, (ConnectionTerminatedError, ConnectionError)):
        return "Die Verbindung zum iPhone ist abgebrochen. Erneut verbinden."
    return f"{UNEXPECTED_ERROR_PREFIX}: {type(error).__name__}: {error}"


def _log_failure(context: str, error: Exception) -> str:
    """Loggt knapp; den Traceback nur bei unbekannten Fehlern oder mit ``-v``."""
    message = describe_error(error)
    verbose = message.startswith(UNEXPECTED_ERROR_PREFIX) or logger.isEnabledFor(logging.DEBUG)
    logger.warning("%s: %s", context, message, exc_info=error if verbose else None)
    return message


class State(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


def validate_coordinates(latitude: float, longitude: float) -> None:
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ValueError("Koordinaten müssen endliche Zahlen sein.")
    if not -90 <= latitude <= 90:
        raise ValueError("Breitengrad muss zwischen -90 und 90 liegen.")
    if not -180 <= longitude <= 180:
        raise ValueError("Längengrad muss zwischen -180 und 180 liegen.")


class LocationController:
    """Zustand und Ablaufsteuerung; serialisiert alle Gerätezugriffe über ein Lock."""

    def __init__(self, backend_factory: Callable[[], Backend], udid: Optional[str] = None) -> None:
        self._backend_factory = backend_factory
        self._udid = udid
        self._backend: Optional[Backend] = None
        self._lock = asyncio.Lock()
        self.state = State.DISCONNECTED
        self.device: Optional[DeviceInfo] = None
        self.location: Optional[tuple[float, float]] = None
        self.error: Optional[str] = None

    async def connect(self) -> None:
        async with self._lock:
            await self._ensure_connected()

    async def teleport(self, latitude: float, longitude: float) -> None:
        validate_coordinates(latitude, longitude)
        async with self._lock:
            await self._ensure_connected()
            await self._run(self._backend.set_location(latitude, longitude))
            self.location = (latitude, longitude)

    async def reset(self) -> None:
        # Verbindet bei Bedarf neu: Nach einem Absturz soll sich der echte Standort trotzdem zurückholen lassen.
        async with self._lock:
            await self._ensure_connected()
            await self._run(self._backend.clear_location())
            self.location = None

    async def disconnect(self) -> None:
        async with self._lock:
            if self._backend is not None and self.location is not None:
                with suppress(Exception):
                    await self._backend.clear_location()
            await self._drop()
            self.error = None

    async def status(self) -> dict[str, Any]:
        if self.state is State.CONNECTED and not self._lock.locked() and not self._backend.is_alive():
            async with self._lock:
                if self.state is State.CONNECTED and not self._backend.is_alive():
                    await self._drop()
                    self.error = "Verbindung zum iPhone verloren (Kabel getrennt?). Erneut verbinden."
        return {
            "state": self.state.value,
            "device": asdict(self.device) if self.device else None,
            "location": {"latitude": self.location[0], "longitude": self.location[1]} if self.location else None,
            "error": self.error,
        }

    async def _ensure_connected(self) -> None:
        if self.state is State.CONNECTED and self._backend.is_alive():
            return
        await self._drop()
        self.state = State.CONNECTING
        self.error = None
        backend = self._backend_factory()
        try:
            self.device = await backend.open(self._udid)
        except BaseException as e:
            await backend.close()
            self.state = State.DISCONNECTED
            self.device = None
            if not isinstance(e, Exception):
                raise
            self.error = _log_failure("Verbinden fehlgeschlagen", e)
            raise DeviceError(self.error) from e
        self._backend = backend
        self.state = State.CONNECTED

    async def _run(self, operation: Any) -> None:
        try:
            await operation
        except Exception as e:
            # Ein fehlgeschlagener DVT-Aufruf heißt fast immer: Kanal tot. Sauber abbauen, damit der nächste
            # Versuch neu verbindet statt auf einer toten Verbindung zu hängen.
            message = _log_failure("Gerätezugriff fehlgeschlagen", e)
            await self._drop()
            self.error = message
            raise DeviceError(self.error) from e

    async def _drop(self) -> None:
        backend, self._backend = self._backend, None
        self.state = State.DISCONNECTED
        self.device = None
        self.location = None
        if backend is not None:
            await backend.close()
