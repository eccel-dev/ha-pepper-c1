"""Sensor — shows the UID of the last scanned RFID tag and firmware version."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATORS, DATA_ENTITY_ADDERS, DOMAIN
from .coordinator import PepperC1Coordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Save callback and add entities for already-connected readers."""
    hub = hass.data[DOMAIN][entry.entry_id]
    hub[DATA_ENTITY_ADDERS]["sensor"] = async_add_entities

    for coordinator in hub[DATA_COORDINATORS].values():
        async_add_entities([
            PepperC1TagUIDSensor(coordinator, entry),
            PepperC1TagTypeSensor(coordinator, entry),
            PepperC1ReaderUptimeSensor(coordinator, entry),
            PepperC1FirmwareSensor(coordinator, entry),
        ])


class PepperC1BaseSensor(CoordinatorEntity[PepperC1Coordinator], SensorEntity):
    """Base class for Eccel C1 sensors."""

    def __init__(self, coordinator: PepperC1Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self.coordinator.device_id)},
            "name": self.coordinator.device_name,
            "manufacturer": "Eccel Technology Ltd",
            "model": "Eccel C1",
            "sw_version": self.coordinator.data.get("firmware") if self.coordinator.data else None,
        }

    @property
    def available(self) -> bool:
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get("available", False)


class PepperC1TagUIDSensor(PepperC1BaseSensor):
    """Sensor showing the UID of the last scanned tag."""

    _attr_icon = "mdi:nfc"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PepperC1Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Eccel C1 Tag UID"
        self._attr_unique_id = f"{coordinator.device_id}_tag_uid"

    @property
    def state(self) -> str | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("uid")


class PepperC1TagTypeSensor(PepperC1BaseSensor):
    """Sensor showing the RFID tag type/family."""

    _attr_icon = "mdi:nfc-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PepperC1Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Eccel C1 Tag Type"
        self._attr_unique_id = f"{coordinator.device_id}_tag_type"

    @property
    def state(self) -> str | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("tag_type")


class PepperC1ReaderUptimeSensor(PepperC1BaseSensor):
    """Sensor showing reader uptime since last restart (in ms)."""

    _attr_icon = "mdi:timer"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "ms"

    def __init__(self, coordinator: PepperC1Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Eccel C1 Reader Uptime (ms)"
        self._attr_unique_id = f"{coordinator.device_id}_reader_uptime_ms"

    @property
    def state(self) -> int | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("reader_uptime_ms")


class PepperC1FirmwareSensor(PepperC1BaseSensor):
    """Sensor showing the reader firmware version."""

    _attr_icon = "mdi:chip"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PepperC1Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Eccel C1 Firmware"
        self._attr_unique_id = f"{coordinator.device_id}_firmware"

    @property
    def state(self) -> str | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("firmware")
