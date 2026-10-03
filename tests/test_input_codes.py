"""Tests for per-display raw input codes.

Both Samsung panels this was built against ignore BetterDisplay's standard
input ids -- the switch reports success and nothing happens -- but obey a raw
`inputSelect` write with the vendor's own number. These pin the option format
and which request a selection turns into.
"""

from __future__ import annotations

import pytest

from custom_components.betterdisplay.config_flow import (
    format_input_codes,
    parse_input_codes,
)
from custom_components.betterdisplay.select import input_options, input_switch

from .conftest import UUID_G95


def test_parse_pairs() -> None:
    """The verified G95NC mapping round-trips into name -> code."""
    assert parse_input_codes("HDMI 1=5, DisplayPort 1=15") == {
        "HDMI 1": 5,
        "DisplayPort 1": 15,
    }


def test_parse_tolerates_whitespace() -> None:
    """Spacing around names, codes and separators is not significant."""
    assert parse_input_codes("  DisplayPort 2 = 9 ,HDMI 1=  6  ") == {
        "DisplayPort 2": 9,
        "HDMI 1": 6,
    }


def test_parse_blank_is_empty() -> None:
    """An empty field clears the display's codes."""
    assert parse_input_codes("") == {}
    assert parse_input_codes("   ") == {}


def test_parse_ignores_trailing_comma() -> None:
    """A stray separator is not an entry."""
    assert parse_input_codes("HDMI 1=5,") == {"HDMI 1": 5}


@pytest.mark.parametrize(
    "text",
    [
        "HDMI 1",
        "HDMI 1=five",
        "HDMI 1=5.5",
        "HDMI 1=",
        "=5",
        "HDMI 1=256",
        "HDMI 1=-1",
        "HDMI 1=5, DisplayPort 1",
    ],
)
def test_parse_rejects_malformed(text: str) -> None:
    """Anything that isn't `name=0..255` is refused rather than half-saved."""
    with pytest.raises(ValueError):
        parse_input_codes(text)


def test_parse_accepts_range_bounds() -> None:
    """A VCP value is one byte."""
    assert parse_input_codes("a=0, b=255") == {"a": 0, "b": 255}


def test_format_renders_back_to_parseable_text() -> None:
    """Stored codes pre-fill the field in the same format the user typed."""
    codes = {"HDMI 1": 5, "DisplayPort 1": 15}
    assert format_input_codes(codes) == "HDMI 1=5, DisplayPort 1=15"
    assert parse_input_codes(format_input_codes(codes)) == codes


def test_options_add_coded_names_after_allowlist() -> None:
    """A name with a raw code is selectable even if BetterDisplay doesn't list it."""
    assert input_options(["HDMI 1"], {"HDMI 1": "3"}, {"HDMI 1": 5, "PC 2": 9}) == [
        "HDMI 1",
        "PC 2",
    ]


def test_options_fall_back_to_reported_list() -> None:
    """Without an allowlist the reported inputs are offered, sorted."""
    assert input_options([], {"HDMI 1": "3", "DisplayPort 1": "1"}, {}) == [
        "DisplayPort 1",
        "HDMI 1",
    ]


def test_options_from_codes_alone() -> None:
    """Codes are enough to make the select usable."""
    assert input_options([], {}, {"HDMI 1": 5}) == ["HDMI 1"]


class RecordingClient:
    """Records which switch method a selection reached."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    async def set_input_code(self, uuid: str, code: int) -> None:
        self.calls.append(("code", uuid, code))

    async def set_input_source(self, uuid: str, source_id: str) -> None:
        self.calls.append(("source", uuid, source_id))


async def test_switch_uses_raw_code_when_configured() -> None:
    """A configured code wins over BetterDisplay's own id for the same name."""
    client = RecordingClient()
    switch = input_switch(client, UUID_G95, "HDMI 1", {"HDMI 1": 5}, {"HDMI 1": "3"})

    assert switch is not None
    await switch()
    assert client.calls == [("code", UUID_G95, 5)]


async def test_switch_falls_back_to_perform() -> None:
    """Inputs without a code still go through `changeInputSource`."""
    client = RecordingClient()
    switch = input_switch(client, UUID_G95, "HDMI 1", {"PC 2": 9}, {"HDMI 1": "3"})

    assert switch is not None
    await switch()
    assert client.calls == [("source", UUID_G95, "3")]


async def test_switch_with_code_needs_no_reported_source() -> None:
    """A coded name BetterDisplay doesn't list is still switchable."""
    client = RecordingClient()
    switch = input_switch(client, UUID_G95, "PC 2", {"PC 2": 9}, {})

    assert switch is not None
    await switch()
    assert client.calls == [("code", UUID_G95, 9)]


def test_switch_unknown_option_is_none() -> None:
    """Neither a code nor a reported id: nothing to send."""
    assert input_switch(RecordingClient(), UUID_G95, "VGA 1", {}, {}) is None
