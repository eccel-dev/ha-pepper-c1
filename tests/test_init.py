"""Tests for __init__.py — hub pattern, _on_reader_connected."""
from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def make_hub_data():
    """Return hass.data structure for a single config entry."""
    from unittest.mock import AsyncMock
    from custom_components.pepper_c1.const import DATA_APPROVED_DEVICES, DATA_COORDINATORS, DATA_ENTITY_ADDERS, DATA_SERVER, DATA_STORE
    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value={"approved_devices": {}})
    return {
        DATA_SERVER: None,
        DATA_COORDINATORS: {},
        DATA_ENTITY_ADDERS: {},
        DATA_APPROVED_DEVICES: set(),
        DATA_STORE: mock_store,
    }


def make_hass(hub_data: dict):
    from custom_components.pepper_c1.const import DOMAIN

    hass = MagicMock()
    hass.data = {DOMAIN: {"test_entry": hub_data}}
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    return hass


def make_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"server_port": 1234}
    return entry


class TestOnReaderConnected:
    async def test_creates_new_coordinator_on_first_connect(self):
        from custom_components.pepper_c1 import _on_reader_connected
        from custom_components.pepper_c1.const import DATA_COORDINATORS

        hub = make_hub_data()
        hass = make_hass(hub)
        entry = make_entry()
        mock_sock = MagicMock(spec=socket.socket)

        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator.async_start = AsyncMock()
        mock_coordinator._firmware = None

        with patch(
            "custom_components.pepper_c1.PepperC1Coordinator",
            return_value=mock_coordinator,
        ), patch(
            "custom_components.pepper_c1._add_entities_for_coordinator"
        ) as mock_add:
            await _on_reader_connected(hass, entry, "pepper_c1_door", "Pepper C1 Door", mock_sock, "2.56")

        assert "pepper_c1_door" in hub[DATA_COORDINATORS]
        mock_coordinator.async_start.assert_awaited_once_with(mock_sock)
        mock_add.assert_called_once()

    async def test_reconnect_reuses_existing_coordinator(self):
        from custom_components.pepper_c1 import _on_reader_connected
        from custom_components.pepper_c1.const import DATA_COORDINATORS

        hub = make_hub_data()
        mock_coordinator = MagicMock()
        mock_coordinator.async_reconnect = AsyncMock()
        hub[DATA_COORDINATORS]["pepper_c1_door"] = mock_coordinator

        hass = make_hass(hub)
        entry = make_entry()
        mock_sock = MagicMock(spec=socket.socket)

        with patch("custom_components.pepper_c1._add_entities_for_coordinator") as mock_add:
            await _on_reader_connected(hass, entry, "pepper_c1_door", "Pepper C1 Door", mock_sock, "2.56")

        mock_coordinator.async_reconnect.assert_awaited_once_with(mock_sock)
        mock_add.assert_not_called()

    async def test_firmware_set_on_coordinator(self):
        from custom_components.pepper_c1 import _on_reader_connected
        from custom_components.pepper_c1.const import DATA_COORDINATORS

        hub = make_hub_data()
        hass = make_hass(hub)
        entry = make_entry()
        mock_sock = MagicMock(spec=socket.socket)

        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator.async_start = AsyncMock()
        mock_coordinator._firmware = None

        with patch(
            "custom_components.pepper_c1.PepperC1Coordinator",
            return_value=mock_coordinator,
        ), patch("custom_components.pepper_c1._add_entities_for_coordinator"):
            await _on_reader_connected(hass, entry, "door", "Pepper C1", mock_sock, "3.0")

        assert mock_coordinator._firmware == "3.0"


class TestAddEntitiesForCoordinator:
    def test_calls_all_platform_adders(self):
        from custom_components.pepper_c1 import _add_entities_for_coordinator
        from custom_components.pepper_c1.coordinator import PepperC1Coordinator

        coordinator = MagicMock(spec=PepperC1Coordinator)
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Device"
        coordinator.data = {}

        entry = MagicMock()
        entry.entry_id = "entry_id"

        sensor_adder = MagicMock()
        binary_sensor_adder = MagicMock()
        switch_adder = MagicMock()
        number_adder = MagicMock()

        entity_adders = {
            "sensor": sensor_adder,
            "binary_sensor": binary_sensor_adder,
            "switch": switch_adder,
            "number": number_adder,
        }

        _add_entities_for_coordinator(coordinator, entry, entity_adders)

        sensor_adder.assert_called_once()
        binary_sensor_adder.assert_called_once()
        switch_adder.assert_called_once()
        number_adder.assert_called_once()

    def test_skips_missing_adders(self):
        from custom_components.pepper_c1 import _add_entities_for_coordinator
        from custom_components.pepper_c1.coordinator import PepperC1Coordinator

        coordinator = MagicMock(spec=PepperC1Coordinator)
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Device"
        coordinator.data = {}

        entry = MagicMock()

        sensor_adder = MagicMock()
        _add_entities_for_coordinator(coordinator, entry, {"sensor": sensor_adder})

        sensor_adder.assert_called_once()
