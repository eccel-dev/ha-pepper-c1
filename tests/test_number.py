"""Testy encji number — polling timeout."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


def make_number(timeout_ms: int = 200, reader_polling_active: bool = True):
    from custom_components.pepper_c1.number import PepperC1PollingTimeoutNumber

    coordinator = MagicMock()
    coordinator.polling_timeout_ms = timeout_ms
    coordinator.reader_polling_active = reader_polling_active
    coordinator.enqueue_reader_command = MagicMock()
    coordinator.device_id = "pepper_c1_test"
    coordinator.device_name = "Pepper C1 Test"

    entry = MagicMock()
    entry.entry_id = "test_entry"

    number = PepperC1PollingTimeoutNumber.__new__(PepperC1PollingTimeoutNumber)
    number._coordinator = coordinator
    number._entry = entry
    number._attr_name = "Pepper C1 Polling Timeout"
    number._attr_unique_id = "test_entry_polling_timeout"
    number.async_write_ha_state = MagicMock()
    return number, coordinator


class TestPollingTimeoutNumber:
    def test_native_value_reflects_coordinator(self):
        number, coordinator = make_number(timeout_ms=300)
        assert number.native_value == 300.0

    def test_min_max_step(self):
        number, _ = make_number()
        assert number._attr_native_min_value == 0
        assert number._attr_native_max_value == 5000
        assert number._attr_native_step == 1

    async def test_set_value_updates_coordinator(self):
        number, coordinator = make_number(timeout_ms=200)
        await number.async_set_native_value(500.0)
        assert coordinator.polling_timeout_ms == 500

    async def test_set_value_enqueues_command_when_active(self):
        number, coordinator = make_number(reader_polling_active=True)
        await number.async_set_native_value(400.0)
        coordinator.enqueue_reader_command.assert_called_once()

    async def test_set_value_no_command_when_polling_off(self):
        number, coordinator = make_number(reader_polling_active=False)
        await number.async_set_native_value(400.0)
        coordinator.enqueue_reader_command.assert_not_called()

    async def test_set_value_writes_state(self):
        number, _ = make_number()
        await number.async_set_native_value(100.0)
        number.async_write_ha_state.assert_called_once()

    def test_device_info_keys(self):
        number, _ = make_number()
        info = number.device_info
        assert "identifiers" in info
        assert info["manufacturer"] == "Eccel Technology Ltd"
