import asyncio

import pytest
from pymobiledevice3.exceptions import PyMobileDevice3Exception

from locationspoofer import device
from locationspoofer.device import DeviceError, PymobiledeviceBackend


class FakeLockdown:
    def __init__(self, developer_mode: bool) -> None:
        self.product_version = "27.0"
        self.has_developer_mode = True
        self.udid = "00008150-TEST"
        self.product_type = "iPhone18,2"
        self.all_values = {"DeviceName": "Test-iPhone"}
        self.developer_mode = developer_mode
        self.closed = False

    async def get_developer_mode_status(self) -> bool:
        return self.developer_mode

    async def close(self) -> None:
        self.closed = True


def install_fakes(monkeypatch, lockdown, reveal_error=None):
    async def create_using_usbmux(**_kwargs):
        return lockdown

    class FakeAmfi:
        revealed = False

        def __init__(self, _lockdown) -> None:
            pass

        async def reveal_developer_mode_option_in_ui(self) -> None:
            if reveal_error is not None:
                raise reveal_error
            FakeAmfi.revealed = True

    monkeypatch.setattr(device, "create_using_usbmux", create_using_usbmux)
    monkeypatch.setattr(device, "AmfiService", FakeAmfi)
    return FakeAmfi


def test_developer_mode_off_reveals_toggle(monkeypatch):
    lockdown = FakeLockdown(developer_mode=False)
    amfi = install_fakes(monkeypatch, lockdown)

    with pytest.raises(DeviceError, match="gerade freigeschaltet"):
        asyncio.run(PymobiledeviceBackend()._inspect(None))

    assert amfi.revealed
    assert lockdown.closed


def test_failed_reveal_is_reported_not_swallowed(monkeypatch):
    lockdown = FakeLockdown(developer_mode=False)
    install_fakes(monkeypatch, lockdown, reveal_error=PyMobileDevice3Exception("denied by policy"))

    with pytest.raises(DeviceError, match="denied by policy"):
        asyncio.run(PymobiledeviceBackend()._inspect(None))

    assert lockdown.closed


def test_developer_mode_on_returns_device_info(monkeypatch):
    install_fakes(monkeypatch, FakeLockdown(developer_mode=True))

    info = asyncio.run(PymobiledeviceBackend()._inspect(None))

    assert info.name == "Test-iPhone"
    assert info.ios_version == "27.0"
