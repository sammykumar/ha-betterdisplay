"""Tests for the BetterDisplay HTTP client.

These pin the behaviours that are easy to regress because the API does not
behave the way an HTTP API normally does: a non-JSON identifiers payload, an
error string inside a 200, and valueless flag parameters.
"""

from __future__ import annotations

import pytest

from custom_components.betterdisplay.api import (
    BetterDisplayAuthError,
    BetterDisplayError,
    BetterDisplayUnreachableError,
)

from .conftest import (
    IDENTIFIERS_PAYLOAD,
    INPUT_SOURCE_LIST,
    UUID_C49,
    UUID_G95,
)


async def test_list_displays_parses_unwrapped_objects(fake_server, make_client) -> None:
    """The identifiers body is not valid JSON on its own."""
    fake_server.respond(IDENTIFIERS_PAYLOAD)
    displays = await make_client().list_displays()

    assert [d.name for d in displays] == ["C49RG9x", "Odyssey G95NC"]
    assert displays[0].uuid == UUID_C49
    assert displays[1].uuid == UUID_G95


async def test_list_displays_filters_non_displays(fake_server, make_client) -> None:
    """A DisplayGroup shares the payload but is not a display."""
    fake_server.respond(IDENTIFIERS_PAYLOAD)
    displays = await make_client().list_displays()

    assert "Default Group" not in [d.name for d in displays]
    assert len(displays) == 2


async def test_display_carries_identity_fields(fake_server, make_client) -> None:
    """Device registry entries are built from these."""
    fake_server.respond(IDENTIFIERS_PAYLOAD)
    displays = await make_client().list_displays()

    g95 = displays[1]
    assert g95.serial == "HNTWC00000"
    assert g95.year == "2023"
    assert g95.tag_id == "1019"


async def test_list_displays_rejects_unparseable_body(fake_server, make_client) -> None:
    """A body that isn't objects at all should surface as an error."""
    fake_server.respond("not json")
    with pytest.raises(BetterDisplayError):
        await make_client().list_displays()


async def test_failed_sentinel_reads_as_none(fake_server, make_client) -> None:
    """`Failed.` arrives as the body of an HTTP 200, not as a status code."""
    fake_server.respond("Failed.")
    assert await make_client().get_brightness(UUID_C49) is None


async def test_failed_sentinel_on_write_raises(fake_server, make_client) -> None:
    """A rejected write must not look like a success."""
    fake_server.respond("Failed.")
    with pytest.raises(BetterDisplayError):
        await make_client().set_brightness(UUID_C49, 0.5)


async def test_flag_parameters_sent_as_empty_value(fake_server, make_client) -> None:
    """Flag-style parameters must be present with an empty value, not dropped."""
    fake_server.respond("0.4")
    await make_client().get_brightness(UUID_G95)

    assert fake_server.last_query["brightness"] == ""


async def test_token_is_attached_to_every_request(fake_server, make_client) -> None:
    """Token auth is optional in BetterDisplay but must be sent when set."""
    fake_server.respond("1.0")
    await make_client(token="s3cret").get_brightness(UUID_G95)

    assert fake_server.last_query["token"] == "s3cret"


async def test_no_token_parameter_when_unset(fake_server, make_client) -> None:
    """An empty token must not be sent as a blank one."""
    fake_server.respond("1.0")
    await make_client().get_brightness(UUID_G95)

    assert "token" not in fake_server.last_query


async def test_displays_are_targeted_by_uuid_not_tagid(
    fake_server, make_client
) -> None:
    """tagID is session-assigned, so it must never appear in a request."""
    fake_server.respond("1.0")
    await make_client().get_brightness(UUID_G95)

    assert fake_server.last_query["UUID"] == UUID_G95
    assert "tagID" not in fake_server.last_query


async def test_brightness_read_as_fraction(fake_server, make_client) -> None:
    """Brightness comes back as a 0.0-1.0 float."""
    fake_server.respond("0.4")
    assert await make_client().get_brightness(UUID_G95) == 0.4


async def test_brightness_write_is_clamped(fake_server, make_client) -> None:
    """Out-of-range values would be rejected by BetterDisplay."""
    fake_server.respond("")
    await make_client().set_brightness(UUID_G95, 4.2)

    assert fake_server.last_query["brightness"] == "1.0"


async def test_backlight_parses_on_off(fake_server, make_client) -> None:
    """hardwareBacklight answers with words, not booleans."""
    client = make_client()

    fake_server.respond("on")
    assert await client.get_backlight(UUID_G95) is True

    fake_server.respond("off")
    assert await client.get_backlight(UUID_G95) is False


async def test_backlight_unsupported_reads_as_none(fake_server, make_client) -> None:
    """Anything that isn't on/off means the display has no such control."""
    fake_server.respond("Failed.")
    assert await make_client().get_backlight(UUID_C49) is None


async def test_input_source_list_is_parsed(fake_server, make_client) -> None:
    """Lines look like `3 - HDMI 1 [DDCController]`."""
    fake_server.respond(INPUT_SOURCE_LIST)
    sources = await make_client().list_input_sources(UUID_G95)

    assert sources["HDMI 1"] == "3"
    assert sources["USB-C / TB 1"] == "6"
    # The full list is every DDC-addressable input, which is why the
    # integration makes the user narrow it rather than offering all of them.
    assert len(sources) == 12


async def test_input_source_list_empty_when_unsupported(
    fake_server, make_client
) -> None:
    """No list means no select entity, rather than an empty dropdown."""
    fake_server.respond("Failed.")
    assert await make_client().list_input_sources(UUID_C49) == {}


async def test_non_numeric_read_is_none_not_an_exception(
    fake_server, make_client
) -> None:
    """A junk float shouldn't take down a whole coordinator refresh."""
    fake_server.respond("warm")
    assert await make_client().get_temperature(UUID_G95) is None


async def test_rejected_token_is_auth_error(fake_server, make_client) -> None:
    """A bad token should not be reported as the Mac being asleep."""
    fake_server.respond("forbidden", status=403)
    with pytest.raises(BetterDisplayAuthError):
        await make_client(token="wrong").get_brightness(UUID_G95)


async def test_server_error_is_not_unreachable(fake_server, make_client) -> None:
    """A 500 is the app misbehaving, not the Mac being away."""
    fake_server.respond("boom", status=500)
    with pytest.raises(BetterDisplayError) as excinfo:
        await make_client().get_brightness(UUID_G95)

    assert not isinstance(excinfo.value, BetterDisplayUnreachableError)


async def test_connection_refused_is_unreachable(session) -> None:
    """A sleeping Mac must be distinguishable from an API error."""
    from custom_components.betterdisplay.api import BetterDisplayClient

    # Port 1 is reserved and nothing listens on it.
    client = BetterDisplayClient(session, "127.0.0.1", 1)
    with pytest.raises(BetterDisplayUnreachableError):
        await client.get_brightness(UUID_G95)
