from __future__ import annotations

from typing import Optional

import pytest

from locationspoofer.device import DeviceInfo, LocationController

DEVICE = DeviceInfo(udid="00008150-TEST", name="Test-iPhone", ios_version="27.0", product_type="iPhone18,2")


class FakeBackend:
    """Verhält sich wie PymobiledeviceBackend, protokolliert aber nur die Aufrufe."""

    def __init__(self, open_error: Optional[Exception] = None) -> None:
        self.open_error = open_error
        self.calls: list[tuple] = []
        self.alive = False
        self.fail_next_set: Optional[Exception] = None

    async def open(self, udid: Optional[str]) -> DeviceInfo:
        self.calls.append(("open", udid))
        if self.open_error is not None:
            raise self.open_error
        self.alive = True
        return DEVICE

    async def set_location(self, latitude: float, longitude: float) -> None:
        self.calls.append(("set", latitude, longitude))
        if self.fail_next_set is not None:
            error, self.fail_next_set = self.fail_next_set, None
            raise error

    async def clear_location(self) -> None:
        self.calls.append(("clear",))

    async def close(self) -> None:
        self.calls.append(("close",))
        self.alive = False

    def is_alive(self) -> bool:
        return self.alive


class BackendPool:
    """Factory, die jede erzeugte FakeBackend-Instanz für Assertions aufhebt."""

    def __init__(self) -> None:
        self.created: list[FakeBackend] = []
        self.open_error: Optional[Exception] = None

    def __call__(self) -> FakeBackend:
        backend = FakeBackend(self.open_error)
        self.created.append(backend)
        return backend

    @property
    def last(self) -> FakeBackend:
        return self.created[-1]


@pytest.fixture
def pool() -> BackendPool:
    return BackendPool()


@pytest.fixture
def controller(pool: BackendPool) -> LocationController:
    return LocationController(pool, udid=None)
