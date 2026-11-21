"""Per-port power on a GL-RM4PE: `glkvm.power` with a `port`.

Each port of a GL-RM4PE has its own rear USB-A socket for an ATX board, and
the unit powers only the active port's socket. So the action switches to the
port, waits for that port's board to appear in /api/atx, checks the port has
not moved, and only then presses anything. The fake's ATX state follows its
active port the same way (FakeClient.atx_by_port).
"""

import asyncio
from dataclasses import replace

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.glkvm import const
from custom_components.glkvm.api import GlkvmConnectionError
from custom_components.glkvm.const import (
    ATTR_ACTION,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_PORT,
    ATTR_WAIT,
    DOMAIN,
    SERVICE_POWER,
    SERVICE_SET_ACTIVE_PORT,
)
from custom_components.glkvm.models import AtxState

from .conftest import RM4PE_SWITCH, setup_entry

BOARD = AtxState(enabled=True, power="off")
NO_BOARD = AtxState(enabled=False, power="off")


@pytest.fixture(autouse=True)
def fast_wait(monkeypatch):
    """A board that never appears fails in a fraction of a second, not 15 s."""
    monkeypatch.setattr(const, "ATX_PORT_TIMEOUT", 0.2)
    monkeypatch.setattr(const, "ATX_PORT_POLL_INTERVAL", 0.01)


@pytest.fixture
def rm4pe(fake_client):
    # Active on port 1; boards on ports 1 and 3 (0-based 0 and 2).
    fake_client.switch = RM4PE_SWITCH
    fake_client.atx_by_port = {0: BOARD, 2: BOARD}
    return fake_client


async def _power(hass, entry, action="on", **extra) -> None:
    await hass.services.async_call(
        DOMAIN,
        SERVICE_POWER,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id, ATTR_ACTION: action, **extra},
        blocking=True,
    )


def _commands(fake) -> list[tuple]:
    return [(name, args, kwargs) for name, args, kwargs in fake.calls]


async def test_switches_to_the_port_then_powers_its_host(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    await _power(hass, config_entry, "on", **{ATTR_PORT: 3})
    assert _commands(rm4pe) == [
        ("switch_set_active", (2,), {}),
        ("atx_power", ("on",), {"wait": True}),
    ]
    # Left on that port: switching back would cut the board's USB power.
    assert rm4pe.switch.active_port == 2


async def test_the_active_port_is_not_switched_again(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    await _power(hass, config_entry, "off_hard", **{ATTR_PORT: 1, ATTR_WAIT: False})
    assert _commands(rm4pe) == [("atx_power", ("off_hard",), {"wait": False})]


async def test_waits_for_the_board_to_enumerate(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    reads = {"n": 0}

    def late_board(fake) -> None:
        # The board on port 3 shows up on the third read after the switch.
        if fake.switch.active_port == 2:
            reads["n"] += 1
            fake.atx_by_port[2] = BOARD if reads["n"] >= 3 else NO_BOARD

    rm4pe.on_get_atx = late_board
    await _power(hass, config_entry, "reset_hard", **{ATTR_PORT: 3})
    assert reads["n"] >= 3
    assert rm4pe.names()[-1] == "atx_power"


async def test_a_port_without_a_board_sends_nothing(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    with pytest.raises(HomeAssistantError, match="no ATX board answered") as err:
        await _power(hass, config_entry, "off_hard", **{ATTR_PORT: 2})
    assert err.value.translation_key == "no_atx_on_port"
    # The call was valid and the KVM switched: a device condition, not a
    # validation error (ServiceValidationError subclasses HomeAssistantError).
    assert not isinstance(err.value, ServiceValidationError)
    assert "atx_power" not in rm4pe.names()
    assert rm4pe.names() == ["switch_set_active"]


async def test_a_port_moved_mid_wait_sends_nothing(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)

    def moved(fake) -> None:
        # Someone switches the unit to port 1 (which also has a board) while
        # the action is waiting for port 3's board.
        fake.switch = replace(fake.switch, active_port=0)

    rm4pe.on_get_atx = moved
    with pytest.raises(HomeAssistantError, match="switched away from port 3") as err:
        await _power(hass, config_entry, "off_hard", **{ATTR_PORT: 3})
    assert err.value.translation_key == "port_moved"
    assert "atx_power" not in rm4pe.names()


async def test_a_switch_that_vanishes_mid_call_sends_nothing(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)

    def gone(fake) -> None:
        fake.switch = None

    rm4pe.atx_by_port = None
    rm4pe.atx = BOARD
    rm4pe.on_get_atx = gone
    with pytest.raises(HomeAssistantError) as err:
        await _power(hass, config_entry, "on", **{ATTR_PORT: 3})
    assert err.value.translation_key == "port_moved"
    assert "atx_power" not in rm4pe.names()


async def test_refuses_a_unit_without_a_switch(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    with pytest.raises(ServiceValidationError) as err:
        await _power(hass, config_entry, "on", **{ATTR_PORT: 1})
    assert err.value.translation_key == "no_switch"
    assert fake_client.calls == []


async def test_refuses_a_port_the_unit_does_not_have(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    with pytest.raises(ServiceValidationError, match="It has 4"):
        await _power(hass, config_entry, "on", **{ATTR_PORT: 5})
    with pytest.raises(vol.Invalid):
        await _power(hass, config_entry, "on", **{ATTR_PORT: 0})
    assert rm4pe.calls == []


async def test_a_failed_switch_is_a_translated_error(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    rm4pe.fail = GlkvmConnectionError("timed out")
    with pytest.raises(HomeAssistantError):
        await _power(hass, config_entry, "on", **{ATTR_PORT: 3})


async def test_without_a_port_the_active_host_is_controlled(hass, rm4pe, config_entry):
    # Unchanged behaviour: no switch, no fresh wait, the active port's board.
    await setup_entry(hass, config_entry)
    await _power(hass, config_entry, "on")
    assert _commands(rm4pe) == [("atx_power", ("on",), {"wait": True})]


async def test_without_a_port_a_missing_board_is_still_refused(
    hass, rm4pe, config_entry
):
    rm4pe.atx_by_port = {2: BOARD}
    await setup_entry(hass, config_entry)
    with pytest.raises(ServiceValidationError) as err:
        await _power(hass, config_entry, "on")
    assert err.value.translation_key == "no_atx"


async def test_set_active_port_waits_for_a_power_action_in_progress(
    hass, rm4pe, config_entry
):
    # Both take the coordinator's port lock, so a switch cannot land between
    # per-port power's switch and its button press.
    await setup_entry(hass, config_entry)
    lock = config_entry.runtime_data.port_lock
    await lock.acquire()
    task = hass.async_create_task(
        hass.services.async_call(
            DOMAIN,
            SERVICE_SET_ACTIVE_PORT,
            {ATTR_CONFIG_ENTRY_ID: config_entry.entry_id, ATTR_PORT: 2},
            blocking=True,
        )
    )
    for _ in range(5):
        await asyncio.sleep(0)
    assert "switch_set_active" not in rm4pe.names()
    lock.release()
    await task
    assert rm4pe.names() == ["switch_set_active"]
