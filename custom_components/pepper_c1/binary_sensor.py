"""Binary sensor — True when an RFID tag is in range of the reader."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    hub = hass.data[DOMAIN][entry.entry_id]
    hub[DATA_ENTITY_ADDERS]["binary_sensor"] = async_add_entities

    for coordinator in hub[DATA_COORDINATORS].values():
        async_add_entities([
            PepperC1TagPresentSensor(coordinator, entry),
        ])


class PepperC1BaseBinarySensor(CoordinatorEntity[PepperC1Coordinator], BinarySensorEntity):
    """Base class for Eccel C1 binary sensors."""

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
        }

    @property
    def available(self) -> bool:
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get("available", False)


class PepperC1TagPresentSensor(PepperC1BaseBinarySensor):
    """Binary sensor — whether a tag is currently in range."""

    _attr_icon = "mdi:nfc-tap"

    def __init__(self, coordinator: PepperC1Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Eccel C1 Tag Present"
        self._attr_unique_id = f"{coordinator.device_id}_tag_present"

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return False
        return bool(self.coordinator.data.get("tag_present", False))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return {
            "uid": self.coordinator.data.get("uid"),
            "tag_type": self.coordinator.data.get("tag_type"),
        }


