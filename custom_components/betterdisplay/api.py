"""Async client for the BetterDisplay HTTP integration API.

API reference: https://github.com/waydabber/BetterDisplay/wiki/Integration-features,-CLI

Three behaviours of that API shape this module:

* `/get?identifiers` answers with comma-separated JSON objects that are not
  wrapped in an array, so the body is not a valid JSON document on its own.
* Some parameters are flags carrying no value (`identifiers`, `hardwareBacklight`)
  and must be sent as an empty string rather than omitted.
* Failures arrive as the body `Failed.` inside an HTTP 200.

State is read from BetterDisplay's own parameters rather than from raw DDC
registers. Driving one display from 100% to 40% to 70% and back, `brightness`
tracked every step while the DDC luminance register reported 100, 100, 0 and
40 -- noise, not state. `hardwareBrightness` is no better: it lags exactly one
write behind, reading 0.0 after a write of 0.4 and 0.4 after a write of 0.7.

Displays are addressed by UUID. BetterDisplay also accepts `tagID`, but that
is assigned per session (observed as 4 and 1019 on the development machine),
so keying on it would silently re-point entities at the wrong monitor after a
reconnect.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

FAILED_SENTINEL = "Failed."


class BetterDisplayError(Exception):
    """The BetterDisplay API returned an error or could not be reached."""


class BetterDisplayUnreachableError(BetterDisplayError):
    """The Mac is not answering -- asleep, off, or off the network."""


class BetterDisplayAuthError(BetterDisplayError):
    """The integration token was missing or rejected."""


@dataclass(frozen=True)
class Display:
    """A display as reported by `/get?identifiers`."""

    uuid: str
    name: str
    tag_id: str
    model: str | None = None
    serial: str | None = None
    vendor: str | None = None
    year: str | None = None

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> Display:
        """Build a Display from one identifiers object."""
        return cls(
            uuid=raw["UUID"],
            name=raw.get("name") or raw.get("productName") or raw["UUID"],
            tag_id=str(raw.get("tagID", "")),
            model=raw.get("model"),
            serial=raw.get("alphanumericSerial") or raw.get("serial"),
            vendor=raw.get("vendor"),
            year=raw.get("yearOfManufacture"),
        )


class BetterDisplayClient:
    """Thin async wrapper over BetterDisplay's HTTP endpoints."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        port: int,
        token: str | None = None,
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._token = token
        self._base = f"http://{host}:{port}"

    @property
    def host(self) -> str:
        """Host this client talks to."""
        return self._host

    @property
    def port(self) -> int:
        """Port this client talks to."""
        return self._port

    def _params(self, **kwargs: Any) -> dict[str, str]:
        """Build a query string, rendering None as a valueless flag."""
        params = {k: ("" if v is None else str(v)) for k, v in kwargs.items()}
        if self._token:
            params["token"] = self._token
        return params

    async def _request(self, path: str, **params: Any) -> str:
        """Issue a request and return the trimmed body."""
        try:
            async with self._session.get(
                f"{self._base}/{path}",
                params=self._params(**params),
                timeout=ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                body = (await resp.text()).strip()
                if resp.status in (401, 403):
                    raise BetterDisplayAuthError(body or f"HTTP {resp.status}")
                if resp.status != 200:
                    raise BetterDisplayError(body or f"HTTP {resp.status}")
                return body
        except (ClientError, TimeoutError, OSError) as err:
            raise BetterDisplayUnreachableError(str(err)) from err

    async def _get(self, **params: Any) -> str | None:
        """Read a value, returning None when BetterDisplay reports failure."""
        body = await self._request("get", **params)
        if body == FAILED_SENTINEL or not body:
            return None
        return body

    async def _set(self, **params: Any) -> None:
        """Write a value, raising when BetterDisplay reports failure."""
        body = await self._request("set", **params)
        if body == FAILED_SENTINEL:
            raise BetterDisplayError(f"BetterDisplay rejected set with {params!r}")

    async def list_displays(self) -> list[Display]:
        """Enumerate connected displays."""
        raw = await self._request("get", identifiers=None)
        try:
            payload = json.loads(f"[{raw}]")
        except json.JSONDecodeError as err:
            raise BetterDisplayError(
                f"unexpected identifiers payload: {raw[:200]!r}"
            ) from err
        return [
            Display.from_payload(item)
            for item in payload
            if item.get("deviceType") == "Display" and item.get("UUID")
        ]

    async def get_brightness(self, uuid: str) -> float | None:
        """Brightness as a 0.0-1.0 fraction, or None if unsupported."""
        return await self._get_float(uuid, "brightness")

    async def set_brightness(self, uuid: str, fraction: float) -> None:
        """Set brightness from a 0.0-1.0 fraction."""
        await self._set(UUID=uuid, brightness=max(0.0, min(1.0, fraction)))

    async def _get_float(self, uuid: str, parameter: str) -> float | None:
        """Read a parameter that answers with a bare float."""
        raw = await self._get(UUID=uuid, **{parameter: None})
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            _LOGGER.debug("Non-numeric %s read for %s: %r", parameter, uuid, raw)
            return None

    async def get_backlight(self, uuid: str) -> bool | None:
        """Hardware backlight state, or None if the display has no such control."""
        raw = await self._get(UUID=uuid, hardwareBacklight=None)
        if raw not in ("on", "off"):
            return None
        return raw == "on"

    async def set_backlight(self, uuid: str, on: bool) -> None:
        """Turn the panel on or off."""
        await self._set(UUID=uuid, hardwareBacklight="on" if on else "off")

    async def get_contrast(self, uuid: str) -> float | None:
        """Contrast as a 0.0-1.0 fraction, or None if unsupported."""
        return await self._get_float(uuid, "hardwareContrast")

    async def set_contrast(self, uuid: str, fraction: float) -> None:
        """Set contrast from a 0.0-1.0 fraction."""
        await self._set(UUID=uuid, hardwareContrast=max(0.0, min(1.0, fraction)))

    async def get_temperature(self, uuid: str) -> float | None:
        """Colour temperature offset, or None if unsupported."""
        return await self._get_float(uuid, "temperature")

    async def set_temperature(self, uuid: str, value: float) -> None:
        """Set the colour temperature offset."""
        await self._set(UUID=uuid, temperature=value)

    async def list_input_sources(self, uuid: str) -> dict[str, str]:
        """Map input name -> DDC id.

        BetterDisplay returns every DDC-addressable input (`3 - HDMI 1
        [DDCController]`), not the ports the panel actually has, so callers are
        expected to narrow this with a user-configured allowlist.
        """
        raw = await self._get(UUID=uuid, inputSourceList=None)
        if raw is None:
            return {}
        sources: dict[str, str] = {}
        for line in raw.splitlines():
            source_id, _, rest = line.partition(" - ")
            name = rest.split(" [")[0].strip()
            if source_id.strip().isdigit() and name:
                sources[name] = source_id.strip()
        return sources

    async def set_input_source(self, uuid: str, source_id: str) -> None:
        """Switch the display to a DDC input id."""
        await self._set(UUID=uuid, changeInputSource=source_id)
