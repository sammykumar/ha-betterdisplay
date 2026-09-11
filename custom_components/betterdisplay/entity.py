"""Shared base entity for BetterDisplay platforms."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Display
from .const import CAP_ASSUMED, CAP_UNSUPPORTED, DOMAIN
from .coordinator import BetterDisplayCoordinator

# EDID vendor ids are three 5-bit letters packed into 16 bits; only the panels
# actually seen on this Mac are spelled out, the rest fall back to the code.
VENDOR_NAMES: dict[int, str] = {
    1552: "Apple",
    4268: "Dell",
    7789: "LG",
    19501: "Samsung",
}


def vendor_name(vendor: str | None) -> str | None:
    """Resolve a numeric EDID vendor code to a manufacturer name."""
    if not vendor:
        return None
    try:
        return VENDOR_NAMES.get(int(vendor), vendor)
    except ValueError:
        return vendor


class BetterDisplayEntity(CoordinatorEntity[BetterDisplayCoordinator]):
    """One feature of one display."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BetterDisplayCoordinator,
        display: Display,
        feature: str,
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._display = display
        self._feature = feature
        # Keyed on UUID rather than tagID: tagID is reassigned per BetterDisplay
        # session and would silently re-point an entity at the other monitor.
        self._attr_unique_id = f"{display.uuid}_{feature}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, display.uuid)},
            name=display.name,
            manufacturer=vendor_name(display.vendor),
            model=display.model,
            serial_number=display.serial,
        )

    @property
    def display_data(self) -> dict[str, Any]:
        """Last polled state for this display."""
        return (self.coordinator.data or {}).get(self._display.uuid, {})

    @property
    def capability(self) -> str:
        """How this entity's feature is handled, as decided by probing."""
        return self.coordinator.capabilities.get(self._display.uuid, {}).get(
            self._feature, CAP_UNSUPPORTED
        )

    @property
    def available(self) -> bool:
        """Whether the Mac is answering and still reports this display."""
        return self.coordinator.reachable and self._display.uuid in (
            self.coordinator.data or {}
        )

    @property
    def assumed_state(self) -> bool:
        """True when state is whatever we last wrote rather than read back."""
        return self.capability == CAP_ASSUMED
