"""Tests for which devices the user may delete.

A cable swap gave the G95NC a new UUID and left its old device behind with no
entities, and HA refused to delete it because the integration never said
removal was allowed. Only devices with no live display behind them qualify.
"""

from __future__ import annotations

from custom_components.betterdisplay import is_stale_device
from custom_components.betterdisplay.const import DOMAIN

ENTRY_ID = "01M416JE5W8QBKQV5K3YF05AN1"
LIVE = "C923F476-4763-4AC0-8EFD-279734232152"
OLD = "711AB070-01BD-4906-84F3-E907E4BDE416"


def test_display_no_longer_reported_is_stale() -> None:
    """The old UUID left behind by a cable swap can be removed."""
    assert is_stale_device({(DOMAIN, OLD)}, ENTRY_ID, {LIVE})


def test_live_display_is_kept() -> None:
    """A display the Mac still reports would just be recreated."""
    assert not is_stale_device({(DOMAIN, LIVE)}, ENTRY_ID, {LIVE})


def test_mac_device_is_kept() -> None:
    """The Mac's own device carries the connectivity sensor."""
    assert not is_stale_device({(DOMAIN, ENTRY_ID)}, ENTRY_ID, {LIVE})


def test_foreign_identifiers_are_ignored() -> None:
    """A device with none of our identifiers isn't ours to judge."""
    assert not is_stale_device({("other", OLD)}, ENTRY_ID, {LIVE})
