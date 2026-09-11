"""Light platform for BetterDisplay.

Each display becomes one brightness-only light. "On" means the panel's
backlight is lit, which is a separate control from brightness: a display can
sit at 80% brightness with the backlight off.

Brightness goes through BetterDisplay's own `brightness` parameter, never the
raw DDC luminance register. Driving one display from 100% to 40% to 70% and
back to 100%, the register read back 100, 100, 0 and 40 -- noise rather than
state -- while `brightness` tracked every step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterDisplayConfigEntry
from .api import Display
from .const import (
    CAP_READ,
    CAP_UNSUPPORTED,
    FEATURE_BACKLIGHT,
    FEATURE_BRIGHTNESS,
)
from .entity import BetterDisplayEntity

if TYPE_CHECKING:
    from .coordinator import BetterDisplayCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BetterDisplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one light per display that supports brightness."""
    coordinator = entry.runtime_data
    async_add_entities(
        BetterDisplayLight(coordinator, display)
        for display in coordinator.displays.values()
        if coordinator.capabilities.get(display.uuid, {}).get(FEATURE_BRIGHTNESS)
        != CAP_UNSUPPORTED
    )


class BetterDisplayLight(BetterDisplayEntity, LightEntity):
    """Backlight and brightness control for one display."""

    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_name = None

    def __init__(self, coordinator: BetterDisplayCoordinator, display: Display) -> None:
        """Initialise the light."""
        super().__init__(coordinator, display, FEATURE_BRIGHTNESS)

    @property
    def _backlight_capability(self) -> str:
        """How the backlight state is known, which is not the light's feature."""
        return self.coordinator.capabilities.get(self._display.uuid, {}).get(
            FEATURE_BACKLIGHT, CAP_UNSUPPORTED
        )

    @property
    def brightness(self) -> int | None:
        """Brightness on HA's 0-255 scale."""
        fraction = self.display_data.get(FEATURE_BRIGHTNESS)
        if fraction is None:
            return None
        return round(fraction * 255)

    @property
    def is_on(self) -> bool | None:
        """Whether the panel is lit."""
        if self._backlight_capability == CAP_READ:
            return self.display_data.get(FEATURE_BACKLIGHT)
        brightness = self.display_data.get(FEATURE_BRIGHTNESS)
        if brightness is None:
            return None
        return brightness > 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Light the panel, optionally setting brightness in the same wake."""
        fraction: float | None = None
        if ATTR_BRIGHTNESS in kwargs:
            fraction = kwargs[ATTR_BRIGHTNESS] / 255

        await self.coordinator.async_command(lambda: self._async_turn_on(fraction))

        if self._backlight_capability != CAP_READ:
            self.coordinator.optimistic_set(self._display.uuid, FEATURE_BACKLIGHT, True)
        if fraction is not None and self.capability != CAP_READ:
            self.coordinator.optimistic_set(
                self._display.uuid, FEATURE_BRIGHTNESS, fraction
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the panel off without touching the brightness setting."""
        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_backlight(self._display.uuid, False)
        )
        if self._backlight_capability != CAP_READ:
            self.coordinator.optimistic_set(
                self._display.uuid, FEATURE_BACKLIGHT, False
            )

    async def _async_turn_on(self, fraction: float | None) -> None:
        """Raise the backlight first so the brightness write lands on a lit panel."""
        await self.coordinator.client.set_backlight(self._display.uuid, True)
        if fraction is not None:
            await self.coordinator.client.set_brightness(self._display.uuid, fraction)
