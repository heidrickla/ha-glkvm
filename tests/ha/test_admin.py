"""Only an administrator operates the host or reconfigures the unit.

Every action and every command entity types into, powers, boots or wakes
another machine, or changes the unit's own settings. An administrator's call
is sent, a call with no user (an automation, a script) is sent, and a
non-administrator's call is refused before anything reaches the unit.

The first user Home Assistant creates is the owner, and the owner is an
administrator, so the owner is created first; the member of `system-users`
created after it is the non-administrator the refusals are checked against.
"""

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized

from custom_components.glkvm.const import (
    ATTR_ACTION,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_KEYS,
    ATTR_MAC,
    ATTR_TEXT,
    DOMAIN,
    SERVICE_POWER,
    SERVICE_SEND_KEYS,
    SERVICE_TYPE_TEXT,
    SERVICE_WAKE,
)

from .conftest import setup_entry

ACTIONS = {
    SERVICE_TYPE_TEXT: ({ATTR_TEXT: "echo hi"}, "hid_type_text"),
    SERVICE_SEND_KEYS: ({ATTR_KEYS: ["ControlLeft", "Delete"]}, "hid_send_shortcut"),
    SERVICE_WAKE: ({ATTR_MAC: "02:00:00:00:00:02"}, "wol_wake"),
    SERVICE_POWER: ({ATTR_ACTION: "off_hard"}, "atx_power"),
}

# (platform, service, entity id, extra data, the client command it sends)
ENTITY_COMMANDS = [
    ("switch", "turn_on", "switch.kvm_host_power", {}, "atx_power"),
    ("switch", "turn_off", "switch.kvm_host_power", {}, "atx_power"),
    ("switch", "turn_on", "switch.kvm_virtual_media_attached", {}, "msd_set_connected"),
    ("switch", "turn_on", "switch.kvm_mouse_jiggler", {}, "hid_set_jiggler"),
    ("switch", "turn_on", "switch.kvm_relay", {}, "gpio_switch"),
    ("button", "press", "button.kvm_power_button", {}, "atx_click"),
    ("button", "press", "button.kvm_hold_power_button", {}, "atx_click"),
    ("button", "press", "button.kvm_reset", {}, "atx_click"),
    ("button", "press", "button.kvm_reset_keyboard_and_mouse", {}, "hid_reset"),
    ("button", "press", "button.kvm_demo_button", {}, "gpio_pulse"),
    ("button", "press", "button.kvm_wake_lab_server", {}, "wol_wake"),
    (
        "select",
        "select_option",
        "select.kvm_virtual_media_image",
        {"option": "rescue.iso"},
        "msd_select_image",
    ),
    (
        "select",
        "select_option",
        "select.kvm_mouse_mode",
        {"option": "usb_rel"},
        "hid_set_mouse_output",
    ),
]


async def _users(hass):
    owner = await hass.auth.async_create_user("Owner", group_ids=["system-admin"])
    member = await hass.auth.async_create_user("Member", group_ids=["system-users"])
    assert owner.is_admin
    assert not member.is_admin
    return owner, member


@pytest.mark.parametrize("service", sorted(ACTIONS))
async def test_actions_are_for_administrators(hass, fake_client, config_entry, service):
    await setup_entry(hass, config_entry)
    owner, member = await _users(hass)
    fields, command = ACTIONS[service]
    data = {ATTR_CONFIG_ENTRY_ID: config_entry.entry_id, **fields}

    await hass.services.async_call(
        DOMAIN, service, data, blocking=True, context=Context(user_id=owner.id)
    )
    assert fake_client.names() == [command]

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN, service, data, blocking=True, context=Context(user_id=member.id)
        )
    assert fake_client.names() == [command]

    # An automation or a script carries no user.
    await hass.services.async_call(DOMAIN, service, data, blocking=True)
    assert fake_client.names() == [command, command]


@pytest.mark.parametrize(
    ("platform", "service", "entity_id", "extra", "command"),
    ENTITY_COMMANDS,
    ids=[f"{c[2]}.{c[1]}" for c in ENTITY_COMMANDS],
)
async def test_command_entities_are_for_administrators(
    hass, fake_client, config_entry, platform, service, entity_id, extra, command
):
    await setup_entry(hass, config_entry)
    owner, member = await _users(hass)
    data = {"entity_id": entity_id, **extra}

    await hass.services.async_call(
        platform, service, data, blocking=True, context=Context(user_id=owner.id)
    )
    assert fake_client.names() == [command]

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            platform, service, data, blocking=True, context=Context(user_id=member.id)
        )
    assert fake_client.names() == [command]

    await hass.services.async_call(platform, service, data, blocking=True)
    assert fake_client.names() == [command, command]
