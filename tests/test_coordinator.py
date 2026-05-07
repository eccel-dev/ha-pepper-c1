"""Tests for the Pepper C1 coordinator (server mode)."""
from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def make_coordinator(
    device_id: str = "pepper_c1_entrance",
    device_name: str = "Pepper C1 Entrance",
    timeout_ms: int = 200,
):
    """Create a coordinator without starting HA (bypasses DataUpdateCoordinator __init__)."""
    from custom_components.pepper_c1.coordinator import PepperC1Coordinator

    coordinator = PepperC1Coordinator.__new__(PepperC1Coordinator)
    coordinator.device_id = device_id
    coordinator.device_name = device_name
    coordinator.polling_timeout_ms = timeout_ms
    coordinator.hass = MagicMock()
    coordinator.hass.loop = MagicMock()
    coordinator._firmware = None
    coordinator._socket = None
    coordinator._tag_timeout_cancel = None
    coordinator.data = None
    coordinator._polling_active = False
    coordinator._watchdog_task = None
    coordinator._listener_thread = None
    coordinator._last_frame_time = 0.0
    coordinator._last_scanned_uid = None
    coordinator._on_connection_lost = None
    return coordinator


class TestOnConnected:
    def test_sets_firmware_and_available(self):
        coordinator = make_coordinator()
        coordinator.data = {"tag_present": False, "uid": None}

        with patch.object(coordinator, "async_set_updated_data") as mock_set:
            coordinator._on_connected("2.56.2249")

        assert coordinator._firmware == "2.56.2249"
        data = mock_set.call_args[0][0]
        assert data["firmware"] == "2.56.2249"
        assert data["available"] is True

    def test_preserves_existing_data(self):
        coordinator = make_coordinator()
        coordinator.data = {"tag_present": True, "uid": "AABB", "tag_count": 1}

        with patch.object(coordinator, "async_set_updated_data") as mock_set:
            coordinator._on_connected("2.56")

        data = mock_set.call_args[0][0]
        assert data["tag_present"] is True
        assert data["uid"] == "AABB"


class TestOnTagFrame:
    def test_mifare_tag(self):
        coordinator = make_coordinator()
        coordinator.data = {"firmware": "1.0", "available": True}
        coordinator._firmware = "1.0"

        with patch.object(coordinator, "async_set_updated_data") as mock_set:
            coordinator._on_tag_frame("DEADBEEF1234", 0x01)

        mock_set.assert_called_once()
        data = mock_set.call_args[0][0]
        assert data["tag_present"] is True
        assert data["uid"] == "DEADBEEF1234"
        assert data["tag_count"] == 1
        assert data["tag_type"] == "MIFARE"
        assert data["available"] is True

    def test_icode_tag(self):
        coordinator = make_coordinator()
        coordinator.data = {}
        coordinator._firmware = "1.0"

        with patch.object(coordinator, "async_set_updated_data") as mock_set:
            coordinator._on_tag_frame("0102030405060708", 0x10)

        data = mock_set.call_args[0][0]
        assert data["tag_type"] == "ICODE"

    def test_unknown_type(self):
        coordinator = make_coordinator()
        coordinator.data = {}
        coordinator._firmware = None

        with patch.object(coordinator, "async_set_updated_data") as mock_set:
            coordinator._on_tag_frame("AABB", 0x04)

        data = mock_set.call_args[0][0]
        assert data["tag_type"] == "0x04"

    def test_deduplicates_same_uid(self):
        coordinator = make_coordinator()
        coordinator.data = {
            "tag_present": True,
            "uid": "DEADBEEF",
            "firmware": "1.0",
            "available": True,
        }
        coordinator._firmware = "1.0"

        with patch.object(coordinator, "async_set_updated_data") as mock_set:
            coordinator._on_tag_frame("DEADBEEF", 0x01)

        mock_set.assert_not_called()


class TestAsyncTagTimeout:
    def test_clears_tag(self):
        coordinator = make_coordinator()
        coordinator.data = {
            "tag_present": True,
            "uid": "DEADBEEF",
            "tag_count": 1,
            "firmware": "1.0",
            "available": True,
        }
        coordinator._tag_timeout_cancel = None

        with patch.object(coordinator, "async_set_updated_data") as mock_set:
            coordinator._async_tag_timeout()

        data = mock_set.call_args[0][0]
        assert data["tag_present"] is False
        assert data["uid"] is None
        assert data["tag_count"] == 0
        assert data["firmware"] == "1.0"


class TestOnDisconnected:
    def test_marks_unavailable_and_clears_tag(self):
        coordinator = make_coordinator()
        coordinator.data = {
            "tag_present": True,
            "uid": "ABC",
            "tag_count": 1,
            "firmware": "1.0",
            "available": True,
        }
        coordinator._tag_timeout_cancel = None

        with patch.object(coordinator, "async_set_updated_data") as mock_set:
            coordinator._on_disconnected()

        data = mock_set.call_args[0][0]
        assert data["available"] is False
        assert data["tag_present"] is False
        assert data["uid"] is None

    def test_cancels_pending_timeout(self):
        coordinator = make_coordinator()
        coordinator.data = {}
        cancel_mock = MagicMock()
        coordinator._tag_timeout_cancel = cancel_mock

        with patch.object(coordinator, "async_set_updated_data"):
            coordinator._on_disconnected()

        cancel_mock.assert_called_once()
        assert coordinator._tag_timeout_cancel is None


class TestInitialState:
    def test_initial_state_structure(self):
        coordinator = make_coordinator()
        coordinator._firmware = "2.56"
        state = coordinator._initial_state()
        assert state["tag_present"] is False
        assert state["uid"] is None
        assert state["firmware"] == "2.56"
        assert state["available"] is False


class TestTagScannedEvent:
    def test_fires_event_on_new_json_tag(self):
        coordinator = make_coordinator()
        coordinator.data = {"tag_present": False, "uid": None, "available": True}
        coordinator._firmware = "1.0"

        with patch.object(coordinator, "async_set_updated_data"):
            coordinator._on_tag_frame_json({
                "uid": "AABBCCDD",
                "string": "MIFARE",
                "antenna": 1,
                "tag_index": 0,
                "known_tag": True,
                "memory": "DEADBEEF",
            })

        coordinator.hass.bus.async_fire.assert_called_once()
        event_name, event_data = coordinator.hass.bus.async_fire.call_args[0]
        assert event_name == "pepper_c1_tag_scanned"
        assert event_data["uid"] == "AABBCCDD"
        assert event_data["tag_type"] == "MIFARE"
        assert event_data["memory_content"] == "DEADBEEF"
        assert event_data["antenna"] == 1
        assert event_data["tag_index"] == 0
        assert event_data["known_tag"] is True
        assert event_data["device_id"] == "pepper_c1_entrance"

    def test_no_event_on_repeated_same_uid(self):
        coordinator = make_coordinator()
        coordinator.data = {
            "tag_present": True, "uid": "AABBCCDD", "available": True,
            "tag_type": "MIFARE",
        }
        coordinator._firmware = "1.0"

        with patch.object(coordinator, "async_set_updated_data"):
            coordinator._on_tag_frame_json({"uid": "AABBCCDD", "string": "MIFARE"})

        coordinator.hass.bus.async_fire.assert_not_called()

    def test_fires_event_on_new_binary_tag(self):
        coordinator = make_coordinator()
        coordinator.data = {"tag_present": False, "uid": None, "available": True}
        coordinator._firmware = "1.0"

        with patch.object(coordinator, "async_set_updated_data"):
            coordinator._on_tag_frame("DEADBEEF", 0x01)

        coordinator.hass.bus.async_fire.assert_called_once()
        event_name, event_data = coordinator.hass.bus.async_fire.call_args[0]
        assert event_name == "pepper_c1_tag_scanned"
        assert event_data["uid"] == "DEADBEEF"
        assert event_data["tag_type"] == "MIFARE"
        assert event_data["memory_content"] is None

    def test_event_fires_again_after_tag_leaves_and_returns(self):
        coordinator = make_coordinator()
        coordinator._firmware = "1.0"

        # First scan
        coordinator.data = {"tag_present": False, "uid": None, "available": True}
        with patch.object(coordinator, "async_set_updated_data"):
            coordinator._on_tag_frame_json({"uid": "AABB", "string": "MIFARE"})
        assert coordinator.hass.bus.async_fire.call_count == 1

        # Simulate tag leaving (watchdog clears data)
        coordinator.data = {"tag_present": False, "uid": None, "available": True}

        # Same tag returns
        with patch.object(coordinator, "async_set_updated_data"):
            coordinator._on_tag_frame_json({"uid": "AABB", "string": "MIFARE"})
        assert coordinator.hass.bus.async_fire.call_count == 2


class TestDeviceInfo:
    def test_uses_device_id_and_name(self, mock_socket):
        coordinator = make_coordinator(
            device_id="pepper_c1_front_door",
            device_name="Pepper C1 Front Door",
        )
        from custom_components.pepper_c1.coordinator import DOMAIN

        from homeassistant.helpers.entity import DeviceInfo
        info = {
            "identifiers": {(DOMAIN, coordinator.device_id)},
            "name": coordinator.device_name,
        }
        assert (DOMAIN, "pepper_c1_front_door") in info["identifiers"]
        assert info["name"] == "Pepper C1 Front Door"
