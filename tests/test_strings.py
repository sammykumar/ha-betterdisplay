"""Tests for the translation files.

A `_attr_translation_key` with no matching entry in strings.json does not fail
loudly: the entity silently falls back to its device name, and two entities on
the same device then collide into `number.foo` and `number.foo_2`. That shipped
once, so it is pinned here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parent.parent / "custom_components" / "betterdisplay"
STRING_FILES = [PACKAGE / "strings.json", PACKAGE / "translations" / "en.json"]

# Platform module -> the section of strings.json its keys must live under.
PLATFORMS = {
    "binary_sensor.py": "binary_sensor",
    "number.py": "number",
    "select.py": "select",
    "light.py": "light",
}


def declared_translation_keys() -> set[tuple[str, str]]:
    """Every (platform, translation_key) pair the code actually sets."""
    found: set[tuple[str, str]] = set()
    for filename, platform in PLATFORMS.items():
        source = (PACKAGE / filename).read_text()
        for match in re.finditer(
            r"_attr_translation_key\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|(\w+))", source
        ):
            literal = match.group(1) or match.group(2)
            if literal:
                found.add((platform, literal))
                continue
            # The key is a constant; resolve it from const.py.
            const_name = match.group(3)
            const_src = (PACKAGE / "const.py").read_text()
            value = re.search(
                rf"^{const_name}:\s*Final\s*=\s*\"([^\"]+)\"", const_src, re.M
            )
            assert value, f"could not resolve {const_name} in const.py"
            found.add((platform, value.group(1)))
    return found


@pytest.mark.parametrize("path", STRING_FILES, ids=lambda p: p.name)
def test_every_translation_key_has_a_name(path: Path) -> None:
    """Otherwise the entity falls back to the device name and IDs collide."""
    data = json.loads(path.read_text())
    entity = data.get("entity", {})

    missing = [
        f"{platform}.{key}"
        for platform, key in sorted(declared_translation_keys())
        if key not in entity.get(platform, {}) or "name" not in entity[platform][key]
    ]

    assert not missing, f"{path.name} is missing entity names for: {missing}"


def test_string_files_stay_in_sync() -> None:
    """A key added to one file and not the other is invisible until runtime."""

    def shape(value):
        if isinstance(value, dict):
            return {k: shape(v) for k, v in sorted(value.items())}
        return type(value).__name__

    shapes = [shape(json.loads(p.read_text())) for p in STRING_FILES]

    assert shapes[0] == shapes[1]


def test_no_orphaned_entity_names() -> None:
    """A name with no code setting that key is dead weight."""
    data = json.loads(STRING_FILES[0].read_text())
    declared = declared_translation_keys()

    orphans = [
        f"{platform}.{key}"
        for platform, keys in data.get("entity", {}).items()
        for key in keys
        if (platform, key) not in declared
    ]

    assert not orphans, f"strings.json names keys nothing sets: {orphans}"
