import asyncio

import pytest
from pymobiledevice3.exceptions import (
    ConnectionFailedToUsbmuxdError,
    ConnectionTerminatedError,
    PairingDialogResponsePendingError,
)

from locationspoofer.device import DeviceError, State, describe_error, validate_coordinates


def run(coro):
    return asyncio.run(coro)


def test_teleport_connects_on_demand_and_sets_location(controller, pool):
    run(controller.teleport(48.137, 11.575))

    assert pool.last.calls == [("open", None), ("set", 48.137, 11.575)]
    status = run(controller.status())
    assert status["state"] == "connected"
    assert status["location"] == {"latitude": 48.137, "longitude": 11.575}
    assert status["device"]["name"] == "Test-iPhone"


def test_second_teleport_reuses_connection(controller, pool):
    run(controller.teleport(1.0, 2.0))
    run(controller.teleport(3.0, 4.0))

    assert len(pool.created) == 1
    assert pool.last.calls[-1] == ("set", 3.0, 4.0)


def test_reset_clears_and_reconnects_when_needed(controller, pool):
    run(controller.reset())

    assert pool.last.calls == [("open", None), ("clear",)]
    assert run(controller.status())["location"] is None


def test_connect_failure_reports_actionable_message(controller, pool):
    pool.open_error = ConnectionFailedToUsbmuxdError()

    with pytest.raises(DeviceError, match="USB-Dienst"):
        run(controller.connect())

    status = run(controller.status())
    assert status["state"] == "disconnected"
    assert "USB-Dienst" in status["error"]
    assert pool.last.calls[-1] == ("close",)


def test_failed_set_drops_connection_so_next_call_reconnects(controller, pool):
    run(controller.teleport(1.0, 2.0))
    first = pool.last
    first.fail_next_set = ConnectionTerminatedError()

    with pytest.raises(DeviceError):
        run(controller.teleport(3.0, 4.0))

    assert first.calls[-1] == ("close",)
    assert run(controller.status())["state"] == "disconnected"

    run(controller.teleport(5.0, 6.0))
    assert len(pool.created) == 2
    assert pool.last.calls == [("open", None), ("set", 5.0, 6.0)]


def test_status_detects_lost_device(controller, pool):
    run(controller.teleport(1.0, 2.0))
    pool.last.alive = False  # z. B. Kabel gezogen: der Tunnel hat sich selbst abgebaut

    status = run(controller.status())

    assert status["state"] == State.DISCONNECTED.value
    assert status["location"] is None
    assert "verloren" in status["error"]


def test_disconnect_restores_real_location(controller, pool):
    run(controller.teleport(1.0, 2.0))
    backend = pool.last

    run(controller.disconnect())

    assert backend.calls[-2:] == [("clear",), ("close",)]
    assert run(controller.status())["state"] == "disconnected"


def test_disconnect_without_simulation_does_not_clear(controller, pool):
    run(controller.connect())
    backend = pool.last

    run(controller.disconnect())

    assert ("clear",) not in backend.calls


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91, 0), (-91, 0), (0, 181), (0, -181), (float("nan"), 0), (0, float("inf"))],
)
def test_validate_coordinates_rejects_out_of_range(latitude, longitude):
    with pytest.raises(ValueError):
        validate_coordinates(latitude, longitude)


def test_describe_error_pairing_hint():
    assert "Vertrauen" in describe_error(PairingDialogResponsePendingError())
