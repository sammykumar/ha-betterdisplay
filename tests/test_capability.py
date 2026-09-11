"""Tests for capability probing.

The two displays this was built against behave differently, and the whole
read / assumed / unsupported split exists to keep a display that cannot report
a value from showing a confidently wrong one.
"""

from __future__ import annotations

import pytest

from custom_components.betterdisplay.api import BetterDisplayError, Display
from custom_components.betterdisplay.capability import probe_all, probe_display
from custom_components.betterdisplay.const import (
    CAP_ASSUMED,
    CAP_READ,
    CAP_UNSUPPORTED,
    CAPABILITY_PROBE_ATTEMPTS,
    FEATURE_BACKLIGHT,
    FEATURE_BRIGHTNESS,
    FEATURE_CONTRAST,
    FEATURE_INPUT_SOURCE,
    FEATURE_TEMPERATURE,
)

from .conftest import INPUT_SOURCE_LIST, UUID_C49, UUID_G95

DISPLAY = Display(uuid=UUID_G95, name="Odyssey G95NC", tag_id="1019")
OTHER = Display(uuid=UUID_C49, name="C49RG9x", tag_id="4")


class StubClient:
    """A client whose every read can be told what to do."""

    def __init__(self, **answers) -> None:
        self.answers = {
            "brightness": 1.0,
            "backlight": True,
            "contrast": 0.75,
            "temperature": 0.0,
            "input_sources": {"HDMI 1": "3"},
            **answers,
        }
        self.calls: list[str] = []

    async def _answer(self, name: str):
        self.calls.append(name)
        value = self.answers[name]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, list):
            return value.pop(0)
        return value

    async def get_brightness(self, uuid):
        return await self._answer("brightness")

    async def get_backlight(self, uuid):
        return await self._answer("backlight")

    async def get_contrast(self, uuid):
        return await self._answer("contrast")

    async def get_temperature(self, uuid):
        return await self._answer("temperature")

    async def list_input_sources(self, uuid):
        return await self._answer("input_sources")


async def test_fully_capable_display_reads_everything() -> None:
    """A display answering every parameter should report real state."""
    caps = await probe_display(StubClient(), DISPLAY)

    assert caps[FEATURE_BRIGHTNESS] == CAP_READ
    assert caps[FEATURE_BACKLIGHT] == CAP_READ
    assert caps[FEATURE_CONTRAST] == CAP_READ
    assert caps[FEATURE_TEMPERATURE] == CAP_READ


async def test_unreadable_brightness_falls_back_to_assumed() -> None:
    """Brightness always gets an entity, because writes still work."""
    caps = await probe_display(StubClient(brightness=None), DISPLAY)

    assert caps[FEATURE_BRIGHTNESS] == CAP_ASSUMED


async def test_unreadable_backlight_falls_back_to_assumed() -> None:
    """Panel power is still commandable without a readback."""
    caps = await probe_display(StubClient(backlight=None), DISPLAY)

    assert caps[FEATURE_BACKLIGHT] == CAP_ASSUMED


async def test_unreadable_contrast_is_unsupported() -> None:
    """Contrast has no blind-write story worth an entity."""
    caps = await probe_display(StubClient(contrast=None), DISPLAY)

    assert caps[FEATURE_CONTRAST] == CAP_UNSUPPORTED


async def test_unreadable_temperature_is_unsupported() -> None:
    """Same reasoning as contrast."""
    caps = await probe_display(StubClient(temperature=None), DISPLAY)

    assert caps[FEATURE_TEMPERATURE] == CAP_UNSUPPORTED


async def test_input_source_is_always_assumed() -> None:
    """The monitor leaves the Mac on success, so there is nothing to read."""
    caps = await probe_display(StubClient(), DISPLAY)

    assert caps[FEATURE_INPUT_SOURCE] == CAP_ASSUMED


async def test_no_input_sources_means_no_entity() -> None:
    """An empty dropdown is worse than no dropdown."""
    caps = await probe_display(StubClient(input_sources={}), DISPLAY)

    assert caps[FEATURE_INPUT_SOURCE] == CAP_UNSUPPORTED


async def test_probe_retries_before_giving_up() -> None:
    """One failed read is not proof a display lacks the control."""
    # Fails twice, then answers -- within the retry budget.
    client = StubClient(brightness=[None, None, 0.5])
    caps = await probe_display(client, DISPLAY)

    assert caps[FEATURE_BRIGHTNESS] == CAP_READ
    assert client.calls.count("brightness") == CAPABILITY_PROBE_ATTEMPTS


async def test_probe_gives_up_after_the_budget() -> None:
    """Retrying forever would stall setup on a display that cannot answer."""
    client = StubClient(brightness=[None] * CAPABILITY_PROBE_ATTEMPTS)
    caps = await probe_display(client, DISPLAY)

    assert caps[FEATURE_BRIGHTNESS] == CAP_ASSUMED
    assert client.calls.count("brightness") == CAPABILITY_PROBE_ATTEMPTS


async def test_api_error_stops_retrying_immediately() -> None:
    """A real error is not a flaky read and should not be retried."""
    client = StubClient(brightness=BetterDisplayError("boom"))
    caps = await probe_display(client, DISPLAY)

    assert caps[FEATURE_BRIGHTNESS] == CAP_ASSUMED
    assert client.calls.count("brightness") == 1


async def test_probe_all_keys_on_uuid() -> None:
    """tagID would re-point these at the wrong monitor after a reconnect."""
    caps = await probe_all(StubClient(), [DISPLAY, OTHER])

    assert set(caps) == {UUID_G95, UUID_C49}


async def test_input_source_list_is_not_narrowed_by_probing(
    fake_server, make_client
) -> None:
    """Narrowing is the user's job in the options flow, not the probe's."""
    fake_server.respond(INPUT_SOURCE_LIST)
    sources = await make_client().list_input_sources(UUID_G95)

    assert len(sources) == 40


@pytest.mark.parametrize(
    "feature",
    [
        FEATURE_BRIGHTNESS,
        FEATURE_BACKLIGHT,
        FEATURE_CONTRAST,
        FEATURE_TEMPERATURE,
        FEATURE_INPUT_SOURCE,
    ],
)
async def test_every_feature_is_classified(feature: str) -> None:
    """A missing key would make entity setup raise instead of skip."""
    caps = await probe_display(StubClient(), DISPLAY)

    assert feature in caps


async def test_cached_positives_are_trusted() -> None:
    """A fully-positive cache should not trigger a re-probe."""
    from custom_components.betterdisplay import _has_unsupported

    cached = {UUID_G95: {FEATURE_BRIGHTNESS: CAP_READ, FEATURE_CONTRAST: CAP_ASSUMED}}

    assert _has_unsupported(cached) is False


async def test_cached_negative_triggers_reprobe() -> None:
    """A transient failure must not withhold an entity forever."""
    from custom_components.betterdisplay import _has_unsupported

    cached = {
        UUID_G95: {FEATURE_BRIGHTNESS: CAP_READ},
        UUID_C49: {FEATURE_CONTRAST: CAP_UNSUPPORTED},
    }

    assert _has_unsupported(cached) is True
