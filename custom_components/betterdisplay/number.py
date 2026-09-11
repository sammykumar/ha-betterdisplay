"""Number platform for BetterDisplay.

Two configuration numbers per display: contrast and colour temperature.

Contrast follows the same rule as brightness -- read and written through
BetterDisplay's own parameters rather than the DDC register, which was
measured to report values the display was never set to.

Colour temperature is BetterDisplay's own offset, not kelvin and not a
percentage, so it is exposed unconverted and unitless.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterDisplayConfigEntry
from .api import Display
from .const import (
    CAP_READ,
    CAP_UNSUPPORTED,
    FEATURE_CONTRAST,
    FEATURE_TEMPERATURE,
)
from .entity import BetterDisplayEntity

if TYPE_CHECKING:
    from .coordinator import BetterDisplayCoordinator

# BetterDisplay's temperature offset centres on 0 for the panel's native white
# point and runs symmetrically warm and cool. The bounds below are a
# deliberately wide guess -- the API documents no range -- so a display that
# clamps internally is still fully reachable from the UI.
TEMPERATURE_MIN = -100.0
TEMPERATURE_MAX = 100.0
TEMPERATURE_STEP = 1.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BetterDisplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up contrast and colour temperature numbers for every display."""
    coordinator = entry.runtime_data

    entities: list[BetterDisplayEntity] = []
    for display in coordinator.displays.values():
        caps = coordinator.capabilities.get(display.uuid, {})
        if caps.get(FEATURE_CONTRAST) != CAP_UNSUPPORTED:
            entities.append(BetterDisplayContrast(coordinator, display))
        if caps.get(FEATURE_TEMPERATURE) != CAP_UNSUPPORTED:
            entities.append(BetterDisplayTemperature(coordinator, display))

    async_add_entities(entities)


class BetterDisplayContrast(BetterDisplayEntity, NumberEntity):
    """Panel contrast as a percentage."""

    _attr_translation_key = FEATURE_CONTRAST
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: BetterDisplayCoordinator, display: Display) -> None:
        """Initialise the contrast number."""
        super().__init__(coordinator, display, FEATURE_CONTRAST)

    @property
    def native_value(self) -> float | None:
        """Contrast as a percentage."""
        fraction = self.display_data.get(FEATURE_CONTRAST)
        if fraction is None:
            return None
        return fraction * 100

    async def async_set_native_value(self, value: float) -> None:
        """Set contrast."""
        fraction = value / 100
        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_contrast(self._display.uuid, fraction)
        )
        if self.capability != CAP_READ:
            self.coordinator.optimistic_set(
                self._display.uuid, FEATURE_CONTRAST, fraction
            )


class BetterDisplayTemperature(BetterDisplayEntity, NumberEntity):
    """Colour temperature offset on BetterDisplay's own scale.

    The value is not kelvin and not a percentage -- it is the raw offset
    BetterDisplay reports and accepts, passed through unconverted. 0 is the
    panel's native white point; negative is cooler, positive warmer.
    """

    _attr_translation_key = FEATURE_TEMPERATURE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = TEMPERATURE_MIN
    _attr_native_max_value = TEMPERATURE_MAX
    _attr_native_step = TEMPERATURE_STEP
    # A box rather than a slider: the real usable range is unknown, so a
    # slider spanning the guessed bounds would imply a precision we don't have.
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: BetterDisplayCoordinator, display: Display) -> None:
        """Initialise the colour temperature number."""
        super().__init__(coordinator, display, FEATURE_TEMPERATURE)

    @property
    def native_value(self) -> float | None:
        """Raw colour temperature offset."""
        return self.display_data.get(FEATURE_TEMPERATURE)

    async def async_set_native_value(self, value: float) -> None:
        """Set the colour temperature offset."""
        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_temperature(self._display.uuid, value)
        )
        if self.capability != CAP_READ:
            self.coordinator.optimistic_set(
                self._display.uuid, FEATURE_TEMPERATURE, value
            )
