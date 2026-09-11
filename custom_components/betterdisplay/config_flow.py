"""Config and options flows for the BetterDisplay integration."""

from __future__ import annotations

import re
from typing import Any, Final

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import capability
from .api import (
    BetterDisplayAuthError,
    BetterDisplayClient,
    BetterDisplayError,
    BetterDisplayUnreachableError,
    Display,
)
from .const import (
    CAP_UNSUPPORTED,
    CONF_CAPABILITIES,
    CONF_ENABLE_WOL,
    CONF_INPUT_SOURCES,
    CONF_MAC,
    CONF_TOKEN,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DOMAIN,
    FEATURE_INPUT_SOURCE,
    UPDATE_INTERVAL,
)

SECTION_POLLING: Final = "polling"
SECTION_INPUT_SOURCES: Final = "input_sources"
SECTION_WAKE_ON_LAN: Final = "wake_on_lan"

# No default: this ships publicly, so the field starts blank rather than
# carrying one machine's hardware address.
DEFAULT_MAC: Final = ""

MAC_PATTERN: Final = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")

STEP_USER_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="off")
        ),
        vol.Required(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_TOKEN, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="off")
        ),
    }
)


def _describe(displays: list[Display]) -> str:
    """Render discovered displays as a markdown list for form placeholders."""
    lines: list[str] = []
    for display in displays:
        detail = ", ".join(part for part in (display.vendor, display.model) if part)
        lines.append(f"- {display.name} ({detail})" if detail else f"- {display.name}")
    return "\n".join(lines)


class BetterDisplayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup and reconfiguration of a BetterDisplay host."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._displays: list[Display] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BetterDisplayOptionsFlow:
        """Return the options flow for an existing entry."""
        return BetterDisplayOptionsFlow()

    async def _async_probe(
        self, host: str, port: int, token: str
    ) -> tuple[str | None, list[Display], dict[str, dict[str, str]]]:
        """Connect and probe, returning (error key, displays, capabilities)."""
        client = BetterDisplayClient(
            async_get_clientsession(self.hass), host, port, token or None
        )
        try:
            displays = await client.list_displays()
            if not displays:
                return "no_displays", [], {}
            capabilities = await capability.probe_all(client, displays)
        except BetterDisplayAuthError:
            return "invalid_auth", [], {}
        except BetterDisplayUnreachableError:
            return "cannot_connect", [], {}
        except BetterDisplayError:
            return "unknown", [], {}
        return None, displays, capabilities

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect connection details for the Mac running BetterDisplay."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            port = int(user_input[CONF_PORT])
            token = str(user_input.get(CONF_TOKEN, "")).strip()

            await self.async_set_unique_id(host.lower())
            self._abort_if_unique_id_configured()

            error, displays, capabilities = await self._async_probe(host, port, token)
            if error is None:
                self._displays = displays
                self._data = {
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_TOKEN: token,
                    CONF_CAPABILITIES: capabilities,
                }
                return await self.async_step_confirm()
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show what was found before committing the entry."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"BetterDisplay ({self._data[CONF_HOST]})", data=self._data
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "host": self._data[CONF_HOST],
                "count": str(len(self._displays)),
                "displays": _describe(self._displays),
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host, port or token without losing the entry's entities."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            port = int(user_input[CONF_PORT])
            token = str(user_input.get(CONF_TOKEN, "")).strip()

            # The point of reconfiguring is often to move the Mac to a new
            # address, so the unique id is only re-checked when it changed.
            if host.lower() != entry.unique_id:
                await self.async_set_unique_id(host.lower())
                self._abort_if_unique_id_configured()

            error, _displays, capabilities = await self._async_probe(host, port, token)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_TOKEN: token,
                        CONF_CAPABILITIES: capabilities,
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or entry.data
            ),
            errors=errors,
            description_placeholders={"title": entry.title},
        )


class BetterDisplayOptionsFlow(OptionsFlow):
    """Tune polling, per-display input lists and wake-on-LAN."""

    def __init__(self) -> None:
        self._choices: dict[str, tuple[str, list[str]]] | None = None
        self._summary: str = ""

    async def _async_input_choices(self) -> dict[str, tuple[str, list[str]]]:
        """Map form field -> (display UUID, selectable input names).

        Cached so the submit pass reuses the mapping the form was drawn with
        instead of re-probing, which would drop the user's picks if the Mac
        went to sleep between rendering and saving.
        """
        if self._choices is not None:
            return self._choices

        entry = self.config_entry
        capabilities: dict[str, dict[str, str]] = entry.data.get(CONF_CAPABILITIES, {})
        client = BetterDisplayClient(
            async_get_clientsession(self.hass),
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
            entry.data.get(CONF_TOKEN) or None,
        )

        choices: dict[str, tuple[str, list[str]]] = {}
        try:
            displays = await client.list_displays()
            for display in displays:
                caps = capabilities.get(display.uuid, {})
                if caps.get(FEATURE_INPUT_SOURCE, CAP_UNSUPPORTED) == CAP_UNSUPPORTED:
                    continue
                names = sorted(await client.list_input_sources(display.uuid))
                if not names:
                    continue
                field = display.name
                if field in choices:
                    field = f"{display.name} ({display.uuid[:8]})"
                choices[field] = (display.uuid, names)
            self._summary = _describe(displays)
        except BetterDisplayError:
            # Unreachable Mac: draw the form without the input section rather
            # than with an empty one, and leave the stored mapping untouched.
            choices = {}

        self._choices = choices
        return choices

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the options form."""
        options = self.config_entry.options
        choices = await self._async_input_choices()
        errors: dict[str, str] = {}

        if user_input is not None:
            polling = user_input.get(SECTION_POLLING, {})
            wol = user_input.get(SECTION_WAKE_ON_LAN, {})
            selected = user_input.get(SECTION_INPUT_SOURCES, {})

            enable_wol = bool(wol.get(CONF_ENABLE_WOL, False))
            mac = str(wol.get(CONF_MAC, "")).strip()
            if enable_wol and not MAC_PATTERN.match(mac):
                errors["base"] = "invalid_mac"
            else:
                input_sources: dict[str, list[str]] = dict(
                    options.get(CONF_INPUT_SOURCES, {})
                )
                for field, (uuid, _names) in choices.items():
                    input_sources[uuid] = list(selected.get(field, []))

                return self.async_create_entry(
                    data={
                        CONF_SCAN_INTERVAL: int(
                            polling.get(CONF_SCAN_INTERVAL, UPDATE_INTERVAL)
                        ),
                        CONF_INPUT_SOURCES: input_sources,
                        CONF_ENABLE_WOL: enable_wol,
                        CONF_MAC: mac,
                    },
                )

        stored_sources: dict[str, list[str]] = options.get(CONF_INPUT_SOURCES, {})
        schema: dict[Any, Any] = {
            vol.Required(SECTION_POLLING): section(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_SCAN_INTERVAL,
                            default=options.get(CONF_SCAN_INTERVAL, UPDATE_INTERVAL),
                        ): NumberSelector(
                            NumberSelectorConfig(
                                min=1,
                                max=3600,
                                step=1,
                                unit_of_measurement="s",
                                mode=NumberSelectorMode.BOX,
                            )
                        )
                    }
                ),
                {"collapsed": False},
            )
        }

        if choices:
            schema[vol.Required(SECTION_INPUT_SOURCES)] = section(
                vol.Schema(
                    {
                        vol.Optional(
                            field,
                            default=[
                                name
                                for name in stored_sources.get(uuid, [])
                                if name in names
                            ],
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=names,
                                multiple=True,
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        )
                        for field, (uuid, names) in choices.items()
                    }
                ),
                {"collapsed": False},
            )

        schema[vol.Required(SECTION_WAKE_ON_LAN)] = section(
            vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLE_WOL,
                        default=options.get(CONF_ENABLE_WOL, False),
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_MAC, default=options.get(CONF_MAC) or DEFAULT_MAC
                    ): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT, autocomplete="off"
                        )
                    ),
                }
            ),
            {"collapsed": True},
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "host": self.config_entry.data[CONF_HOST],
                "displays": self._summary or "none (the Mac did not answer)",
            },
        )
