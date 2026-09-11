"""Constants for the BetterDisplay integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "betterdisplay"

DEFAULT_PORT: Final = 55777
# No host default: this ships publicly, so the field starts blank rather than
# carrying one machine's hostname.
DEFAULT_HOST: Final = ""

CONF_TOKEN: Final = "token"
CONF_ENABLE_WOL: Final = "enable_wake_on_lan"
CONF_MAC: Final = "mac_address"
CONF_INPUT_SOURCES: Final = "input_sources"
CONF_CAPABILITIES: Final = "capabilities"

# Polling backs off while the Mac is asleep so a closed lid doesn't cost a
# request every ten seconds for hours.
UPDATE_INTERVAL: Final = 10
UPDATE_INTERVAL_UNREACHABLE: Final = 60

# A TCP connect is the honest liveness signal: ICMP can be answered by a
# Bonjour Sleep Proxy on the Mac's behalf while the HTTP server is down.
REACHABILITY_TIMEOUT: Final = 1.0
REQUEST_TIMEOUT: Final = 5.0

# Wake-on-LAN: send, then retry the command while the Mac boots its network
# stack back up. Off by default and unverified against a sleeping machine.
WOL_RETRY_ATTEMPTS: Final = 6
WOL_RETRY_DELAY: Final = 5.0

FEATURE_BRIGHTNESS: Final = "brightness"
FEATURE_CONTRAST: Final = "contrast"
FEATURE_INPUT_SOURCE: Final = "input_source"
FEATURE_BACKLIGHT: Final = "backlight"
FEATURE_TEMPERATURE: Final = "temperature"

# How a feature's state is determined, decided once by capability probing.
CAP_READ: Final = "read"
CAP_ASSUMED: Final = "assumed"
CAP_UNSUPPORTED: Final = "unsupported"

# A parameter failing once doesn't prove the display lacks it, so probing
# retries before writing a feature off.
CAPABILITY_PROBE_ATTEMPTS: Final = 3
