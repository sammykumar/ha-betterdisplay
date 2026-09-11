"""Select platform for BetterDisplay.

One input-source select per display.

This control is one-way. Switching a monitor's input sends it away from the
Mac, and BetterDisplay only talks to the Mac -- so once the display is showing
another machine there is no path back and nothing in Home Assistant can switch
it again. Selecting an input is effectively "hand the monitor over"; getting it
back is a job for the monitor's own buttons.

Because of that, state is write-only: `current_option` is the last option this
entity sent, and None before it has sent anything.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterDisplayConfigEntry
from .api import Display
from .const import CAP_UNSUPPORTED, CONF_INPUT_SOURCES, FEATURE_INPUT_SOURCE
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

    entities: list[BetterDisplayInputSource] = []
    for display in coordinator.displays.values():
        caps = coordinator.capabilities.get(display.uuid, {})
        if caps.get(FEATURE_INPUT_SOURCE) == CAP_UNSUPPORTED:
            continue

        # BetterDisplay reports all twelve DDC-addressable inputs, including
        # DVI and VGA ports the panel does not physically have. The user's
        # allowlist is the only thing that knows which are real; the full list
        # is a last resort so the entity is usable before it's configured.
        allowed = allowlists.get(display.uuid)
        options = allowed or sorted(coordinator.input_sources.get(display.uuid, {}))
        if not options:
            continue

        entities.append(BetterDisplayInputSource(coordinator, display, options))

    async_add_entities(entities)


class BetterDisplayInputSource(BetterDisplayEntity, SelectEntity):
    """Input source for one display, write-only."""

    _attr_translation_key = FEATURE_INPUT_SOURCE
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: BetterDisplayCoordinator,
        display: Display,
        options: list[str],
    ) -> None:
        """Initialise the input-source select."""
        super().__init__(coordinator, display, FEATURE_INPUT_SOURCE)
        self._attr_options = options
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
        sources = self.coordinator.input_sources.get(self._display.uuid, {})
        source_id = sources.get(option)
        if source_id is None:
            raise HomeAssistantError(
                f"{self._display.name} does not report an input source named {option!r}"
            )

        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_input_source(
                self._display.uuid, source_id
            )
        )
        self._selected = option
        self.coordinator.optimistic_set(
            self._display.uuid, FEATURE_INPUT_SOURCE, option
        )
