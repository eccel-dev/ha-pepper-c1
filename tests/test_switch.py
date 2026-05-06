"""Tests for switch — enabling/disabling polling."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


def make_switch(reader_polling_active: bool = True, coordinator_active: bool = True):
    """Create a switch with a mocked coordinator."""
    from custom_components.pepper_c1.switch import PepperC1PollingSwitch

    coordinator = MagicMock()
    coordinator.reader_polling_active = reader_polling_active
    coordinator.polling_active = coordinator_active
    coordinator.enqueue_reader_command = MagicMock()
    coordinator.device_id = "pepper_c1_test"
    coordinator.device_name = "Pepper C1 Test"
    coordinator.data = {}

    entry = MagicMock()
    entry.entry_id = "test_entry"

    switch = PepperC1PollingSwitch.__new__(PepperC1PollingSwitch)
    switch.coordinator = coordinator
    switch._entry = entry
    switch._attr_name = "Pepper C1 Polling"
    switch._attr_unique_id = "test_entry_polling"
    switch.async_write_ha_state = MagicMock()
    return switch, coordinator


class TestPollingSwitch:
    def test_is_on_when_polling_active(self):
        switch, _ = make_switch(reader_polling_active=True)
        assert switch.is_on is True

    def test_is_off_when_polling_inactive(self):
        switch, _ = make_switch(reader_polling_active=False)
        assert switch.is_on is False

    async def test_turn_off_enqueues_command(self):
        switch, coordinator = make_switch(reader_polling_active=True)
        await switch.async_turn_off()
        coordinator.enqueue_reader_command.assert_called_once()
        assert coordinator._reader_polling_active is False
        switch.async_write_ha_state.assert_called_once()

    async def test_turn_on_enqueues_command(self):
        switch, coordinator = make_switch(reader_polling_active=False, coordinator_active=True)
        await switch.async_turn_on()
        coordinator.enqueue_reader_command.assert_called_once()
        assert coordinator._reader_polling_active is True
        switch.async_write_ha_state.assert_called_once()

    async def test_turn_on_noop_when_not_connected(self):
        switch, coordinator = make_switch(reader_polling_active=False, coordinator_active=False)
        await switch.async_turn_on()
        coordinator.enqueue_reader_command.assert_not_called()

    async def test_turn_off_noop_when_already_off(self):
        switch, coordinator = make_switch(reader_polling_active=False)
        await switch.async_turn_off()
        coordinator.enqueue_reader_command.assert_not_called()

    async def test_turn_on_noop_when_already_on(self):
        switch, coordinator = make_switch(reader_polling_active=True)
        await switch.async_turn_on()
        coordinator.enqueue_reader_command.assert_not_called()

    def test_unique_id(self):
        switch, _ = make_switch()
        assert switch._attr_unique_id == "test_entry_polling"

    def test_device_info_keys(self):
        switch, _ = make_switch()
        info = switch.device_info
        assert "identifiers" in info
        assert info["manufacturer"] == "Eccel Technology Ltd"
