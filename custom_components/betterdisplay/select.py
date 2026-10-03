"""Select platform for BetterDisplay.

One input-source select per display.

Switching away from the Mac may be one-way, depending on the monitor. Some
panels stop answering DDC on an inactive input, and then nothing in Home
Assistant can switch them back. Others keep listening: both Samsung panels this
was built against can be switched back by the Mac while they show another
machine.

Some panels also ignore BetterDisplay's standard input ids -- the switch
reports success and nothing happens -- but obey a raw `inputSelect` write with
the vendor's own number. Inputs with a raw code configured in the options flow
are switched that way; everything else goes through `changeInputSource`.

DDC input select can't be read back reliably, so state is write-only:
`current_option` is the last option this entity sent, and None before it has
sent anything.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterDisplayConfigEntry
from .api import BetterDisplayClient, Display
from .const import (
    CAP_UNSUPPORTED,
    CONF_INPUT_CODES,
    CONF_INPUT_SOURCES,
    FEATURE_INPUT_SOURCE,
)
from .entity import BetterDisplayEntity

if TYPE_CHECKING:
    from .coordinator import BetterDisplayCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BetterDisplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one input-source select per display that has any inputs."""
    coordinator = entry.runtime_data
    allowlists: dict[str, list[str]] = entry.options.get(CONF_INPUT_SOURCES, {})
    all_codes: dict[str, dict[str, int]] = entry.options.get(CONF_INPUT_CODES, {})

    entities: list[BetterDisplayInputSource] = []
    for display in coordinator.displays.values():
        caps = coordinator.capabilities.get(display.uuid, {})
        if caps.get(FEATURE_INPUT_SOURCE) == CAP_UNSUPPORTED:
            continue

        # BetterDisplay reports all twelve DDC-addressable inputs, including
        # DVI and VGA ports the panel does not physically have. The user's
        # allowlist is the only thing that knows which are real; the full list
        # is a last resort so the entity is usable before it's configured.
        codes = all_codes.get(display.uuid, {})
        options = input_options(
            allowlists.get(display.uuid, []),
            coordinator.input_sources.get(display.uuid, {}),
            codes,
        )
        if not options:
            continue

        entities.append(BetterDisplayInputSource(coordinator, display, options, codes))

    async_add_entities(entities)


def input_options(
    allowed: list[str], sources: dict[str, str], codes: dict[str, int]
) -> list[str]:
    """Selectable inputs: the allowlist, else every reported input, plus coded ones.

    A name with a raw code is offered even when BetterDisplay doesn't report it,
    since the code alone is enough to switch to it.
    """
    options = list(allowed or sorted(sources))
    options.extend(name for name in codes if name not in options)
    return options


def input_switch(
    client: BetterDisplayClient,
    uuid: str,
    option: str,
    codes: dict[str, int],
    sources: dict[str, str],
) -> Callable[[], Awaitable[None]] | None:
    """The write that switches to `option`, or None if there is no way to."""
    code = codes.get(option)
    if code is not None:
        return lambda: client.set_input_code(uuid, code)
    source_id = sources.get(option)
    if source_id is None:
        return None
    return lambda: client.set_input_source(uuid, source_id)


class BetterDisplayInputSource(BetterDisplayEntity, SelectEntity):
    """Input source for one display, write-only."""

    _attr_translation_key = FEATURE_INPUT_SOURCE
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: BetterDisplayCoordinator,
        display: Display,
        options: list[str],
        codes: dict[str, int],
    ) -> None:
        """Initialise the input-source select."""
        super().__init__(coordinator, display, FEATURE_INPUT_SOURCE)
        self._attr_options = options
        self._codes = codes
        self._selected: str | None = None

    @property
    def current_option(self) -> str | None:
        """The input this entity last selected, if any.

        Held here as well as in the coordinator because the poll rebuilds each
        display's state from the readable features only, which drops any key
        it doesn't itself populate.
        """
        selected = self.display_data.get(FEATURE_INPUT_SOURCE, self._selected)
        if selected not in self._attr_options:
            return None
        return selected

    async def async_select_option(self, option: str) -> None:
        """Switch the display to the chosen input."""
        switch = input_switch(
            self.coordinator.client,
            self._display.uuid,
            option,
            self._codes,
            self.coordinator.input_sources.get(self._display.uuid, {}),
        )
        if switch is None:
            raise HomeAssistantError(
                f"{self._display.name} has no input source or raw code named {option!r}"
            )

        await self.coordinator.async_command(switch)
        self._selected = option
        self.coordinator.optimistic_set(
            self._display.uuid, FEATURE_INPUT_SOURCE, option
        )
