"""Polling coordinator for BetterDisplay.

The Mac this talks to is a laptop, so "not answering" is the normal case for
most of the day rather than an error. An unreachable poll therefore backs the
interval off and returns the last known data instead of failing the update --
raising UpdateFailed every sixty seconds through a night of closed lid is what
fills the log with noise nobody acts on.

Writes go through `async_command` so that a single place owns the wake, retry
and error-translation policy.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BetterDisplayClient,
    BetterDisplayError,
    BetterDisplayUnreachableError,
    Display,
)
from .const import (
    CAP_ASSUMED,
    CAP_READ,
    CONF_ENABLE_WOL,
    CONF_MAC,
    DOMAIN,
    FEATURE_BACKLIGHT,
    FEATURE_BRIGHTNESS,
    FEATURE_CONTRAST,
    FEATURE_TEMPERATURE,
    REACHABILITY_TIMEOUT,
    UPDATE_INTERVAL,
    UPDATE_INTERVAL_UNREACHABLE,
    WOL_RETRY_ATTEMPTS,
    WOL_RETRY_DELAY,
)

_LOGGER = logging.getLogger(__name__)

WOL_PORT = 9
UNREACHABLE_MESSAGE = "MacBook Pro is not reachable"


def _poll_interval(entry: ConfigEntry) -> timedelta:
    """Poll interval chosen in the options flow, or the shipped default."""
    return timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, UPDATE_INTERVAL))


def _send_magic_packet(mac: str) -> None:
    """Broadcast a wake-on-LAN frame for one MAC address."""
    raw = bytes.fromhex(mac.replace(":", "").replace("-", "").replace(".", ""))
    if len(raw) != 6:
        raise ValueError(f"not a MAC address: {mac!r}")
    packet = b"\xff" * 6 + raw * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, ("255.255.255.255", WOL_PORT))


class BetterDisplayCoordinator(DataUpdateCoordinator[dict[str, dict]]):
    """Poll BetterDisplay and serialise writes back to it."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: BetterDisplayClient,
        capabilities: dict[str, dict[str, str]],
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=_poll_interval(entry),
        )
        self.client = client
        self.capabilities = capabilities
        self.displays: dict[str, Display] = {}
        self.input_sources: dict[str, dict[str, str]] = {}
        self.reachable = True

    @property
    def _wol_enabled(self) -> bool:
        """True when the user opted in to waking the Mac for writes."""
        return bool(
            self.config_entry.options.get(
                CONF_ENABLE_WOL, self.config_entry.data.get(CONF_ENABLE_WOL, False)
            )
        )

    @property
    def _mac(self) -> str | None:
        """Configured MAC address, if any."""
        return self.config_entry.options.get(
            CONF_MAC, self.config_entry.data.get(CONF_MAC)
        )

    async def async_command(self, func: Callable[[], Awaitable[None]]) -> None:
        """Run a write against BetterDisplay, waking the Mac first if allowed."""
        if self.reachable:
            try:
                await func()
            except BetterDisplayError as err:
                raise HomeAssistantError(str(err)) from err
            await self.async_request_refresh()
            return

        if not self._wol_enabled or not self._mac:
            raise HomeAssistantError(UNREACHABLE_MESSAGE)

        await self._async_wake()

        last_error: BetterDisplayError | None = None
        for _ in range(WOL_RETRY_ATTEMPTS):
            await asyncio.sleep(WOL_RETRY_DELAY)
            try:
                await func()
            except BetterDisplayError as err:
                last_error = err
                continue
            await self.async_request_refresh()
            return

        raise HomeAssistantError(
            f"{UNREACHABLE_MESSAGE} and did not wake in time: {last_error}"
        )

    def optimistic_set(self, uuid: str, key: str, value: Any) -> None:
        """Record a value we wrote but cannot read back."""
        data = self.data or {}
        data.setdefault(uuid, {})[key] = value
        self.async_set_updated_data(data)

    async def _async_wake(self) -> None:
        """Send the magic packet for the configured MAC."""
        mac = self._mac
        assert mac is not None
        try:
            await self.hass.async_add_executor_job(_send_magic_packet, mac)
        except (OSError, ValueError) as err:
            raise HomeAssistantError(
                f"Could not send wake-on-LAN packet: {err}"
            ) from err

    async def _async_can_connect(self) -> bool:
        """True when the BetterDisplay HTTP port accepts a TCP connection."""
        try:
            async with asyncio.timeout(REACHABILITY_TIMEOUT):
                _, writer = await asyncio.open_connection(
                    self.client.host, self.client.port
                )
        except (TimeoutError, OSError):
            return False
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        return True

    def _mark_unreachable(self) -> dict[str, dict]:
        """Back off polling and keep serving the last known state."""
        if self.reachable:
            _LOGGER.warning(
                "BetterDisplay at %s:%s stopped answering; polling every %ss"
                " until it returns",
                self.client.host,
                self.client.port,
                UPDATE_INTERVAL_UNREACHABLE,
            )
        else:
            _LOGGER.debug(
                "BetterDisplay at %s:%s still not answering",
                self.client.host,
                self.client.port,
            )
        self.reachable = False
        self.update_interval = timedelta(seconds=UPDATE_INTERVAL_UNREACHABLE)
        return self.data or {}

    async def _async_update_data(self) -> dict[str, dict]:
        """Poll every display, or note that the Mac is away."""
        if not await self._async_can_connect():
            return self._mark_unreachable()

        if not self.reachable:
            _LOGGER.info(
                "BetterDisplay at %s:%s is answering again",
                self.client.host,
                self.client.port,
            )
            self.update_interval = _poll_interval(self.config_entry)
        self.reachable = True

        previous = self.data or {}
        try:
            displays = await self.client.list_displays()
            self.displays = {display.uuid: display for display in displays}

            data: dict[str, dict] = {}
            for uuid, display in self.displays.items():
                data[uuid] = await self._async_read_display(
                    display, previous.get(uuid, {})
                )
                if uuid not in self.input_sources:
                    self.input_sources[uuid] = await self.client.list_input_sources(
                        uuid
                    )
        except BetterDisplayUnreachableError:
            return self._mark_unreachable()
        except BetterDisplayError as err:
            raise UpdateFailed(str(err)) from err

        return data

    async def _async_read_display(
        self, display: Display, previous: dict[str, Any]
    ) -> dict[str, Any]:
        """Read the readable features of one display."""
        uuid = display.uuid
        caps = self.capabilities.get(uuid, {})
        state: dict[str, Any] = {
            FEATURE_BRIGHTNESS: None,
            FEATURE_CONTRAST: None,
            FEATURE_BACKLIGHT: None,
            FEATURE_TEMPERATURE: None,
        }

        # Every assumed feature is carried over, not just the four read above:
        # input_source is never readable, so a poll that dropped it would undo
        # the select entity's optimistic write on the next tick.
        for feature, cap in caps.items():
            if cap == CAP_ASSUMED and feature in previous:
                state[feature] = previous[feature]

        if caps.get(FEATURE_BRIGHTNESS) == CAP_READ:
            state[FEATURE_BRIGHTNESS] = await self.client.get_brightness(uuid)
        if caps.get(FEATURE_CONTRAST) == CAP_READ:
            state[FEATURE_CONTRAST] = await self.client.get_contrast(uuid)
        if caps.get(FEATURE_BACKLIGHT) == CAP_READ:
            state[FEATURE_BACKLIGHT] = await self.client.get_backlight(uuid)
        if caps.get(FEATURE_TEMPERATURE) == CAP_READ:
            state[FEATURE_TEMPERATURE] = await self.client.get_temperature(uuid)

        return state
