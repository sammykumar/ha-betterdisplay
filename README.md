# ha-betterdisplay

Home Assistant custom integration for controlling Mac-attached displays through [BetterDisplay](https://github.com/waydabber/BetterDisplay)'s HTTP integration API. Point it at a Mac running BetterDisplay and every display that Mac can see becomes controllable from HA — brightness, panel power, contrast, colour temperature, input source.

Local polling, no cloud, no vendor account. The Mac is the only thing that talks to the monitors.

## Entities

One device per display, plus one connectivity sensor for the Mac itself.

| Entity | Platform | What it does |
| --- | --- | --- |
| Display | `light` | Brightness, and on/off mapped to the panel's hardware backlight |
| Contrast | `number` | BetterDisplay's `hardwareContrast`, where the display answers for it |
| Colour temperature | `number` | BetterDisplay's temperature offset |
| Input source | `select` | Switches the panel's DDC input (write-only — see below) |
| Connected | `binary_sensor` | Whether the Mac is answering on the BetterDisplay port |

Not every display gets every entity. Which ones appear depends on what the panel answered during capability probing.

## Prerequisite: turn on BetterDisplay's HTTP server

It is **off by default**. In BetterDisplay: gear icon → **Settings** → **Application** → **Integration** → enable **"Enable integrated HTTP server"**. The port defaults to `55777`.

**Set a token.** The server binds all interfaces and authentication is optional, so leaving the token blank means anything on your LAN can drive your monitors. Set one in the same panel and give it to the config flow.

The HTTP server and DDC control are both **free features** of BetterDisplay. You do not need a Pro licence for any of this.

## Install

### HACS (recommended)

1. HACS → three-dot menu → **Custom repositories**.
2. Repository: `https://github.com/sammykumar/ha-betterdisplay`, Type: **Integration**.
3. Install **BetterDisplay**, restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → BetterDisplay**.

### Manual

Copy `custom_components/betterdisplay/` into your HA config directory's `custom_components/`, restart, then add the integration from the UI.

## Why this does not trust raw DDC registers

This is the single most important thing to know about the integration, and it is why brightness works at all.

Brightness state comes from BetterDisplay's own `brightness` parameter. The panel's DDC luminance register — the obvious-looking "ground truth" — is the thing that turned out to be untrustworthy.

A write-and-restore test on the Odyssey G95NC drove brightness 100% → 40% → 70% → 100%, sampling every candidate source at each step:

| Step | DDC value | DDC max | `brightness` | `hardwareBrightness` |
| --- | --- | --- | --- | --- |
| before | 100 | 50 | 1.0 | 1.0 |
| set 0.4 | 100 | — | 0.4 | 0.0 |
| set 0.7 | 0 | — | 0.7 | 0.4 |
| set 1.0 | 40 | — | 1.0 | 1.0 |

Three things fall out of that run, all measured rather than inferred:

- **`get?brightness` tracked every commanded change exactly.** It is the correct and trustworthy state source.
- **The DDC luminance register is the unreliable one.** It read 100, 100, 0, 40 while real brightness moved 100/40/70/100 — and reported a value of 100 against a maximum of 50. Noise, not state.
- **`hardwareBrightness` lags exactly one write behind.** It read 0.0 after a write of 0.4 and 0.4 after a write of 0.7, so it is unusable as state.

An earlier reading of this hardware concluded the opposite — that `get?brightness` ignored the panel — on the strength of a single anomalous DDC luminance sample (`15` of max `50`). The write-and-restore run above disproved it.

So the integration does not touch raw DDC at all. State and writes both go through BetterDisplay's own parameters: `brightness`, `hardwareContrast`, `temperature`, `hardwareBacklight` and `changeInputSource`. A display that doesn't answer a given parameter doesn't get a fabricated number — it gets an assumed-state entity reporting whatever was last written, or no entity at all.

## Other API quirks

### `/get?identifiers` isn't valid JSON

It returns JSON objects separated by commas with no array brackets around them. The body has to be wrapped in `[...]` before it will parse.

### `Failed.` comes back as HTTP 200

Errors are not signalled by status code. A refused read, an unknown UUID and an unsupported feature all return `200 OK` with the body `Failed.`, so the body is the error channel.

### Reading a DDC value with its max means different things on different registers

On luminance, separate reads of value and max were stable at `100` and `50` across five consecutive samples, and the combined `--value --max` form returned `100,50` — so there it really is (value, max). On `inputSelect` the same form returned `15,3`, which matches neither ordering against the panel's 1–12 input list. The pair is register-dependent and was only pinned down on one display, so nothing here depends on it; the integration reads no DDC registers.

### `inputSourceList` lists inputs the panel doesn't have

It returns all 12 DDC-addressable input codes, not the ports physically on the monitor. There is no way to tell from the API which of the 12 are real. That is why input options are **user-configured** during setup rather than discovered — you pick the inputs your monitor actually has.

### `tagID` is per-session

BetterDisplay assigns `tagID` fresh each session (observed as `4` and `1019` on the same machine). Entities are keyed on `UUID`, which is stable — keying on `tagID` would silently re-point entities at the wrong monitor after a reconnect. `UUID=` targeting was verified to work against both displays, and a bogus UUID correctly comes back `Failed.`

## Capability probing

Displays on the same Mac do not expose the same controls. One panel may answer for contrast and colour temperature while the panel next to it answers for neither.

Each display is probed once at setup — by asking whether each of `brightness`, `hardwareBacklight`, `hardwareContrast`, `temperature` and `inputSourceList` answers for it — and the result is stored on the config entry. Every feature lands in one of three buckets:

| Bucket | Meaning |
| --- | --- |
| **read** | The parameter answers, so the entity polls and reports real state |
| **assumed** | The control accepts writes but can't be read back, so the entity reports what was last sent |
| **unsupported** | No entity is created |

Probing retries rather than trusting a single read. That matters more than it sounds: a single read is exactly what produced the wrong brightness conclusion above. To re-probe after changing your setup, reload the integration.

## Sleeping Macs

A laptop with a closed lid stops answering, and a poll every ten seconds against a machine that's asleep for eight hours is a lot of nothing.

The coordinator gates every update cycle on a TCP connect probe rather than an HTTP request. A TCP probe is used because ICMP is unreliable here — a Bonjour Sleep Proxy will happily answer pings on the Mac's behalf while the HTTP server is down.

When the probe fails, the integration keeps its last known state, marks entities unavailable, backs the poll interval off from 10s to 60s, and logs **one** warning on the transition rather than one per poll.

**Wake-on-LAN** is available as an off-by-default option (it needs the Mac's MAC address). It sends the magic packet and then retries the pending command while the network stack comes back up. It is **untested against an actually sleeping machine** — treat it as unverified.

## Not implemented

- **Volume and mute.** BetterDisplay exposes them; nothing here uses them yet.
- **Per-channel gain and black level.** Same.
- **Reading back the current input source.** DDC input select is write-only in practice, and switching a monitor's input sends it away from the Mac — at which point nothing in Home Assistant can switch it back, because the Mac is no longer the thing on the other end of the cable. Switch away with care.

## Licence

MIT. See [LICENSE](LICENSE).
