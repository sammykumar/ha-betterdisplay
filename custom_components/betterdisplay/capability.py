"""Per-display capability probing.

Two displays on the same Mac do not expose the same controls -- one may report
contrast and colour temperature while the other reports neither. Probing once
at setup lets each entity decide whether it can report real state, has to run
optimistically, or should not exist at all.

Probing retries before writing a feature off, since a single failed read is
not proof the display lacks the control.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .api import BetterDisplayClient, BetterDisplayError, Display
from .const import (
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

_LOGGER = logging.getLogger(__name__)


async def _answers(read: Callable[[], Awaitable[Any]]) -> bool:
    """True if a parameter returns a value within the retry budget."""
    for _ in range(CAPABILITY_PROBE_ATTEMPTS):
        try:
            if await read() is not None:
                return True
        except BetterDisplayError:
            return False
    return False


async def probe_display(
    client: BetterDisplayClient, display: Display
) -> dict[str, str]:
    """Decide how each feature of one display should be handled.

    Returns a feature -> CAP_* mapping. CAP_READ means poll the real value,
    CAP_ASSUMED means the control is writable but state is whatever we last
    sent, CAP_UNSUPPORTED means create no entity at all.
    """
    uuid = display.uuid
    caps: dict[str, str] = {}

    caps[FEATURE_BRIGHTNESS] = (
        CAP_READ if await _answers(lambda: client.get_brightness(uuid)) else CAP_ASSUMED
    )
    caps[FEATURE_BACKLIGHT] = (
        CAP_READ if await _answers(lambda: client.get_backlight(uuid)) else CAP_ASSUMED
    )
    caps[FEATURE_CONTRAST] = (
        CAP_READ
        if await _answers(lambda: client.get_contrast(uuid))
        else CAP_UNSUPPORTED
    )
    caps[FEATURE_TEMPERATURE] = (
        CAP_READ
        if await _answers(lambda: client.get_temperature(uuid))
        else CAP_UNSUPPORTED
    )

    # Input switching is write-only in practice: the monitor leaves the Mac as
    # soon as it succeeds, so there is nothing left to read back over.
    sources = await client.list_input_sources(uuid)
    caps[FEATURE_INPUT_SOURCE] = CAP_ASSUMED if sources else CAP_UNSUPPORTED

    _LOGGER.debug("Probed %s (%s): %s", display.name, uuid, caps)
    return caps


async def probe_all(
    client: BetterDisplayClient, displays: list[Display]
) -> dict[str, dict[str, str]]:
    """Probe every display, keyed by UUID."""
    return {display.uuid: await probe_display(client, display) for display in displays}
