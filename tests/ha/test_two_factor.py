"""The two-factor (TOTP) secret: asked for, checked, stored, kept secret.

The client is a fake here, so what is checked is what the flow and setup
hand the client and what the entry stores; tests/test_api.py and
tests/test_totp.py cover the header the real client builds from it.
"""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType

from custom_components.glkvm.const import CONF_ADVANCED, CONF_TOTP_SECRET, DOMAIN
from custom_components.glkvm.diagnostics import async_get_config_entry_diagnostics

from .conftest import ENTRY_DATA, HOST, SERIAL
from .frontend_form import frontend_submission
from .test_config_flow import _advanced, _discover, _field

SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
# The same secret the way a setup screen or an authenticator app shows it.
SECRET_AS_SHOWN = "gezd gnbv gy3t qojq gezd gnbv gy3t qojq"


def _not_echoed(result) -> None:
    """The secret goes to the browser neither as a default nor a suggestion."""
    key = _field(_advanced(result).schema, CONF_TOTP_SECRET)
    assert (key.description or {}).get("suggested_value") in (None, "")


async def _user_form(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def test_setup_checks_the_login_with_the_secret_and_stores_it_normalised(
    hass, fake_client
):
    result = await _user_form(hass)
    sent = frontend_submission(result, {CONF_HOST: HOST, CONF_PASSWORD: "secret"})
    sent[CONF_ADVANCED][CONF_TOTP_SECRET] = SECRET_AS_SHOWN
    done = await hass.config_entries.flow.async_configure(result["flow_id"], sent)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"][CONF_TOTP_SECRET] == SECRET
    # The client that validated the login was given the secret.
    assert fake_client.constructed[-1]["totp_secret"] == SECRET
    assert fake_client.reads[:2] == ["check_auth", "system"]


async def test_setup_without_a_secret_stores_none(hass, fake_client):
    result = await _user_form(hass)
    sent = frontend_submission(result, {CONF_HOST: HOST, CONF_PASSWORD: "secret"})
    sent[CONF_ADVANCED][CONF_TOTP_SECRET] = "   "
    done = await hass.config_entries.flow.async_configure(result["flow_id"], sent)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_TOTP_SECRET not in done["data"]
    assert fake_client.constructed[-1]["totp_secret"] is None


async def test_a_secret_that_is_not_base32_is_refused_before_the_unit_is_asked(
    hass, fake_client
):
    result = await _user_form(hass)
    sent = frontend_submission(result, {CONF_HOST: HOST, CONF_PASSWORD: "secret"})
    sent[CONF_ADVANCED][CONF_TOTP_SECRET] = "not base32!"
    shown = await hass.config_entries.flow.async_configure(result["flow_id"], sent)
    assert shown["type"] is FlowResultType.FORM
    assert shown["errors"] == {"base": "invalid_totp_secret"}
    assert fake_client.reads == []
    # Advanced opens so the field can be corrected, and the bad value is not
    # sent back: it is a secret, even when it is a wrong one.
    assert _advanced(shown).options["collapsed"] is False
    _not_echoed(shown)

    sent = frontend_submission(shown, {CONF_PASSWORD: "secret"})
    sent[CONF_ADVANCED][CONF_TOTP_SECRET] = SECRET
    done = await hass.config_entries.flow.async_configure(shown["flow_id"], sent)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"][CONF_TOTP_SECRET] == SECRET


async def test_a_discovered_unit_takes_the_secret_too(hass, fake_client):
    result = await _discover(hass)
    _not_echoed(result)
    sent = frontend_submission(result, {CONF_PASSWORD: "secret"})
    sent[CONF_ADVANCED][CONF_TOTP_SECRET] = SECRET_AS_SHOWN
    done = await hass.config_entries.flow.async_configure(result["flow_id"], sent)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["result"].unique_id == SERIAL
    assert done["data"][CONF_TOTP_SECRET] == SECRET
    assert fake_client.constructed[-1]["totp_secret"] == SECRET


async def _entry_with_secret(hass, config_entry):
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_TOTP_SECRET: SECRET}
    )


async def _setup_with_secret(hass, config_entry):
    await _entry_with_secret(hass, config_entry)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_the_entry_hands_its_secret_to_the_client(
    hass, fake_client, config_entry
):
    await _setup_with_secret(hass, config_entry)
    assert fake_client.constructed[0]["totp_secret"] == SECRET
    assert fake_client.constructed[0]["password"] == "secret"


async def _reconfigure(hass, config_entry, data=None):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": config_entry.entry_id},
        data=data,
    )


async def test_reconfigure_does_not_send_the_stored_secret_to_the_browser(
    hass, fake_client, config_entry
):
    await _entry_with_secret(hass, config_entry)
    result = await _reconfigure(hass, config_entry)
    key = _field(result["data_schema"], CONF_TOTP_SECRET)
    assert (key.description or {}).get("suggested_value") in (None, "")


async def test_reconfigure_with_a_blank_secret_keeps_the_stored_one(
    hass, fake_client, config_entry
):
    await _entry_with_secret(hass, config_entry)
    done = await _reconfigure(
        hass, config_entry, {**ENTRY_DATA, CONF_HOST: "192.0.2.16"}
    )
    assert done["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_TOTP_SECRET] == SECRET
    assert fake_client.constructed[0]["totp_secret"] == SECRET
    await hass.async_block_till_done()


async def test_reconfigure_with_a_new_secret_replaces_it(
    hass, fake_client, config_entry
):
    await _entry_with_secret(hass, config_entry)
    other = "JBSWY3DPEHPK3PXP"
    done = await _reconfigure(
        hass, config_entry, {**ENTRY_DATA, CONF_TOTP_SECRET: other.lower()}
    )
    assert done["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_TOTP_SECRET] == other
    await hass.async_block_till_done()


async def test_reconfigure_refuses_a_malformed_secret(hass, fake_client, config_entry):
    await _entry_with_secret(hass, config_entry)
    shown = await _reconfigure(
        hass, config_entry, {**ENTRY_DATA, CONF_TOTP_SECRET: "0189"}
    )
    assert shown["type"] is FlowResultType.FORM
    assert shown["errors"] == {"base": "invalid_totp_secret"}
    assert config_entry.data[CONF_TOTP_SECRET] == SECRET
    key = _field(shown["data_schema"], CONF_TOTP_SECRET)
    assert (key.description or {}).get("suggested_value") in (None, "")


async def test_reauth_with_a_blank_secret_removes_it(hass, fake_client, config_entry):
    # Two-factor turned off on the unit: the stored secret now fails every
    # login, and reauthentication is where it is cleared.
    await _entry_with_secret(hass, config_entry)
    result = await config_entry.start_reauth_flow(hass)
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "secret"}
    )
    assert done["reason"] == "reauth_successful"
    assert CONF_TOTP_SECRET not in config_entry.data
    await hass.async_block_till_done()


async def test_reauth_takes_a_new_secret(hass, fake_client, config_entry):
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "secret",
            CONF_TOTP_SECRET: SECRET_AS_SHOWN,
        },
    )
    assert done["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOTP_SECRET] == SECRET
    assert fake_client.constructed[-1]["totp_secret"] == SECRET
    await hass.async_block_till_done()


async def test_diagnostics_redact_the_secret(hass, fake_client, config_entry):
    await _setup_with_secret(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diag["config"][CONF_TOTP_SECRET] == "**REDACTED**"
    assert SECRET not in repr(diag)
