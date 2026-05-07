"""Number — adjust polling_timeout_ms at runtime."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_POLLING_TIMEOUT_MS, DATA_COORDINATORS, DATA_ENTITY_ADDERS, DOMAIN
from .coordinator import PepperC1Coordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = hass.data[DOMAIN][entry.entry_id]
    hub[DATA_ENTITY_ADDERS]["number"] = async_add_entities

    for coordinator in hub[DATA_COORDINATORS].values():
        async_add_entities([PepperC1PollingTimeoutNumber(coordinator, entry)])


class PepperC1PollingTimeoutNumber(NumberEntity):
    """Entity for setting the tag absence timeout in ms."""

    _attr_should_poll = False
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 5000
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "ms"
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: PepperC1Coordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_name = "Eccel C1 Polling Timeout"
        self._attr_unique_id = f"{coordinator.device_id}_polling_timeout"

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._coordinator.device_id)},
            "name": self._coordinator.device_name,
            "manufacturer": "Eccel Technology Ltd",
            "model": "Eccel C1",
        }

    @property
    def native_value(self) -> float:
        return float(self._coordinator.polling_timeout_ms)

    async def async_set_native_value(self, value: float) -> None:
        new_ms = int(value)
        self._coordinator.polling_timeout_ms = new_ms
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_POLLING_TIMEOUT_MS: new_ms},
        )
        if self._coordinator.polling_active:
            def _cmd(reader) -> None:
                reader.polling_setup_timeout(new_ms)
            self._coordinator.enqueue_reader_command(_cmd)
        self.async_write_ha_state()
