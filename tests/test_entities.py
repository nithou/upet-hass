from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


PACKAGE_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ubpet"
PACKAGE = "ubpet_entities_test"


@dataclass(frozen=True, kw_only=True)
class _EntityDescription:
    key: str
    name: str | None = None
    icon: str | None = None
    translation_key: str | None = None
    entity_category: object = None
    device_class: object = None
    state_class: object = None
    native_unit_of_measurement: object = None


class _Generic:
    def __class_getitem__(cls, _item):
        return cls


class _Placeholder:
    """Stand-in for Home Assistant constants and enums (any attribute works)."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Placeholder(f"{self._name}.{name}")


class _Anything(types.ModuleType):
    """Module whose missing attributes resolve to a placeholder value."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Placeholder(name)


def _module(name: str, **attrs) -> types.ModuleType:
    module = _Anything(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _load(module_name: str):
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(PACKAGE_DIR)]
    modules = {
        "homeassistant": _module("homeassistant"),
        "homeassistant.components": _module("homeassistant.components"),
        "homeassistant.components.sensor": _module(
            "homeassistant.components.sensor",
            SensorEntity=object,
            SensorEntityDescription=_EntityDescription,
        ),
        "homeassistant.components.binary_sensor": _module(
            "homeassistant.components.binary_sensor",
            BinarySensorEntity=object,
            BinarySensorEntityDescription=_EntityDescription,
        ),
        "homeassistant.config_entries": _module("homeassistant.config_entries"),
        "homeassistant.const": _module("homeassistant.const"),
        "homeassistant.core": _module("homeassistant.core"),
        "homeassistant.helpers": _module("homeassistant.helpers"),
        "homeassistant.helpers.entity": _module("homeassistant.helpers.entity"),
        "homeassistant.helpers.device_registry": _module("homeassistant.helpers.device_registry"),
        "homeassistant.helpers.entity_platform": _module("homeassistant.helpers.entity_platform"),
        "homeassistant.helpers.update_coordinator": _module(
            "homeassistant.helpers.update_coordinator",
            CoordinatorEntity=_Generic,
        ),
        PACKAGE: package,
        f"{PACKAGE}.const": _module(f"{PACKAGE}.const", DOMAIN="ubpet"),
        f"{PACKAGE}.coordinator": _module(f"{PACKAGE}.coordinator", UbpetDataUpdateCoordinator=object),
    }
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{module_name}", PACKAGE_DIR / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    modules[spec.name] = module
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


sensor = _load("sensor")
binary_sensor = _load("binary_sensor")

CAT_RECORD = {
    "catInfoId": 106080,
    "catNickname": "Salem",
    "timeStr": "2026-11-11 19:09:53",
    "eventTime": 1794395393000,
    "eventType": 3,
    "weight": 4.3,
    "costTime": 108,
}


def _description(descriptions, key):
    return next(description for description in descriptions if description.key == key)


class LastVisitSensorTest(unittest.TestCase):
    def value(self, key, item):
        return _description(sensor.DEVICE_SENSORS, key).value_fn(item)

    def test_last_visit_values_come_from_latest_cat_record(self) -> None:
        item = {"cat_records": [CAT_RECORD]}
        self.assertEqual(self.value("last_visit_cat", item), "Salem")
        self.assertEqual(self.value("last_visit_weight", item), 4.3)
        self.assertEqual(self.value("last_visit_duration", item), 108)
        self.assertEqual(
            self.value("last_visit", item),
            datetime.fromtimestamp(1794395393, UTC),
        )

    def test_missing_or_empty_records_give_no_value(self) -> None:
        for item in ({}, {"cat_records": []}, {"cat_records": None}):
            self.assertIsNone(self.value("last_visit_cat", item))
            self.assertIsNone(self.value("last_visit_weight", item))
            self.assertIsNone(self.value("last_visit", item))

    def test_zero_weight_is_not_reported(self) -> None:
        item = {"cat_records": [{**CAT_RECORD, "weight": 0.0, "costTime": 0}]}
        self.assertIsNone(self.value("last_visit_weight", item))
        self.assertIsNone(self.value("last_visit_duration", item))


class BoxStatusTest(unittest.TestCase):
    def test_idle_running_is_standby(self) -> None:
        item = {"mqtt_state": {"w_mode_app_name": "IDLE", "w_state_app_name": "RUNNING"}}
        self.assertEqual(sensor._box_status(item), "Standby")

    def test_cleaning_running_is_running(self) -> None:
        item = {"mqtt_state": {"w_mode_app_name": "CLEANING", "w_state_app_name": "RUNNING"}}
        self.assertEqual(sensor._box_status(item), "Running")


class CatPresentTest(unittest.TestCase):
    def test_blocked_means_cat_present(self) -> None:
        self.assertTrue(binary_sensor._cat_present({"mqtt_state": {"w_state_app_name": "BLOCKED"}}))

    def test_other_states_mean_no_cat(self) -> None:
        self.assertFalse(binary_sensor._cat_present({"mqtt_state": {"w_state_app_name": "RUNNING"}}))

    def test_unknown_without_mqtt_state(self) -> None:
        self.assertIsNone(binary_sensor._cat_present({}))


if __name__ == "__main__":
    unittest.main()
