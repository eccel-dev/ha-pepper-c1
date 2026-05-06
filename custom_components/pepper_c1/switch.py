"""Switch — enables/disables RFID polling on the Eccel C1 reader."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    hub[DATA_ENTITY_ADDERS]["switch"] = async_add_entities

    for coordinator in hub[DATA_COORDINATORS].values():
        async_add_entities([PepperC1PollingSwitch(coordinator, entry)])


class PepperC1PollingSwitch(CoordinatorEntity[PepperC1Coordinator], SwitchEntity):
    """Switch that enables/disables RFID polling on the reader."""

    _attr_icon = "mdi:radar"

    def __init__(self, coordinator: PepperC1Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Eccel C1 Polling"
        self._attr_unique_id = f"{coordinator.device_id}_polling"

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self.coordinator.device_id)},
            "name": self.coordinator.device_name,
            "manufacturer": "Eccel Technology Ltd",
            "model": "Eccel C1",
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.reader_polling_active

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.coordinator.reader_polling_active:
            return
        if not self.coordinator.polling_active:
            return
        from pepper_c1 import PollingEventFormat  # noqa: PLC0415
        pef = PollingEventFormat

        def _cmd(reader) -> None:
            reader.set_polling(False)
            reader.polling_setup_async(known=False, frame_format=pef.JSON)
            reader.polling_setup_async(known=True, frame_format=pef.JSON)
            reader.set_polling(True)

        self.coordinator._reader_polling_active = True
        self.coordinator.enqueue_reader_command(_cmd)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if not self.coordinator.reader_polling_active:
            return

        def _cmd(reader) -> None:
            reader.set_polling(False)

        self.coordinator._reader_polling_active = False
        self.coordinator.enqueue_reader_command(_cmd)
        self.async_write_ha_state()
