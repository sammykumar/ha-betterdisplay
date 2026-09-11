"""Binary sensor platform for BetterDisplay."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BetterDisplayConfigEntry
from .const import DOMAIN
from .coordinator import BetterDisplayCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BetterDisplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hub reachability sensor."""
    async_add_entities([BetterDisplayReachableSensor(entry.runtime_data, entry)])


class BetterDisplayReachableSensor(
    CoordinatorEntity[BetterDisplayCoordinator], BinarySensorEntity
):
    """Whether the Mac running BetterDisplay is answering."""

    _attr_has_entity_name = True
    _attr_name = "Mac reachable"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: BetterDisplayCoordinator,
        entry: BetterDisplayConfigEntry,
    ) -> None:
        """Initialise the sensor against the hub's own service device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_reachable"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="BetterDisplay",
            manufacturer="waydabber",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=f"http://{coordinator.client.host}:{coordinator.client.port}",
        )

    @property
    def is_on(self) -> bool:
        """True while the Mac answers on the BetterDisplay port."""
        return self.coordinator.reachable

    @property
    def available(self) -> bool:
        """Always available: this entity is the one reporting availability."""
        return True
