"""The BetterDisplay integration.

Talks to the BetterDisplay app's HTTP integration API on a Mac and exposes each
attached display as a device with brightness, contrast, backlight, colour
temperature and input-source entities.

Capability probing is done once and stored on the config entry: it costs
several requests per display per feature, and the answers only change when
monitors are swapped -- which warrants a reconfigure anyway.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BetterDisplayClient, BetterDisplayError
from .capability import probe_all
from .const import CONF_CAPABILITIES, CONF_TOKEN, DEFAULT_PORT
from .coordinator import BetterDisplayCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
]

type BetterDisplayConfigEntry = ConfigEntry[BetterDisplayCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: BetterDisplayConfigEntry
) -> bool:
    """Set up BetterDisplay from a config entry."""
    client = BetterDisplayClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        entry.data.get(CONF_TOKEN),
    )

    capabilities: dict[str, dict[str, str]] | None = entry.data.get(CONF_CAPABILITIES)
    if not capabilities:
        try:
            capabilities = await probe_all(client, await client.list_displays())
        except BetterDisplayError as err:
            raise ConfigEntryNotReady(f"Could not probe displays: {err}") from err
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_CAPABILITIES: capabilities}
        )

    coordinator = BetterDisplayCoordinator(hass, entry, client, capabilities)
    await coordinator.async_config_entry_first_refresh()
    if not coordinator.data:
        raise ConfigEntryNotReady(
            f"BetterDisplay on {client.host} reported no displays"
        )

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BetterDisplayConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(
    hass: HomeAssistant, entry: BetterDisplayConfigEntry
) -> None:
    """Reload integration on options change."""
    await hass.config_entries.async_reload(entry.entry_id)
