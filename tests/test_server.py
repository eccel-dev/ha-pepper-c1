"""Tests for the Pepper C1 TCP server."""
from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def make_server(port: int = 1234):
    """Create a PepperC1Server with a mocked hass."""
    from custom_components.pepper_c1.server import PepperC1Server

    hass = MagicMock()
    hass.loop = MagicMock()
    hass.async_add_executor_job = AsyncMock()
    hass.async_create_task = MagicMock()

    on_connected = MagicMock()
    on_disconnected = MagicMock()

    server = PepperC1Server(
        hass=hass,
        port=port,
        on_reader_connected=on_connected,
        on_reader_disconnected=on_disconnected,
    )
    return server, hass, on_connected, on_disconnected


class TestPepperC1Server:
    async def test_start_creates_server(self):
        server, hass, _, _ = make_server(1234)
        mock_asyncio_server = MagicMock()
        mock_asyncio_server.wait_closed = AsyncMock()
        mock_create = AsyncMock(return_value=mock_asyncio_server)

        with patch.object(hass.loop, "create_server", new=mock_create):
            await server.start()
            mock_create.assert_awaited_once()
            call_kwargs = mock_create.call_args
            assert call_kwargs[1]["port"] == 1234
            assert call_kwargs[1]["host"] == "0.0.0.0"

    async def test_stop_closes_server(self):
        server, hass, _, _ = make_server()
        mock_asyncio_server = MagicMock()
        mock_asyncio_server.close = MagicMock()
        mock_asyncio_server.wait_closed = AsyncMock()
        server._server = mock_asyncio_server

        await server.stop()

        mock_asyncio_server.close.assert_called_once()
        mock_asyncio_server.wait_closed.assert_awaited_once()
        assert server._server is None

    async def test_stop_noop_when_not_started(self):
        server, _, _, _ = make_server()
        await server.stop()  # should not raise


class TestIdentifyReader:
    async def test_calls_on_connected_with_device_info(self):
        server, hass, on_connected, _ = make_server()
        mock_sock = MagicMock(spec=socket.socket)

        def fake_query():
            return "Pepper C1 Entrance", "2.56.2249"

        hass.async_add_executor_job = AsyncMock(return_value=("Pepper C1 Entrance", "2.56.2249"))

        await server._identify_reader(mock_sock, ("192.168.1.10", 54321))

        on_connected.assert_called_once()
        args = on_connected.call_args[0]
        assert args[0] == "pepper_c1_entrance"  # device_id = slugified name
        assert args[1] == "Pepper C1 Entrance"  # device_name
        assert args[2] is mock_sock
        assert args[3] == "2.56.2249"

    async def test_fallback_name_when_query_fails(self):
        server, hass, on_connected, _ = make_server()
        mock_sock = MagicMock(spec=socket.socket)

        hass.async_add_executor_job = AsyncMock(side_effect=Exception("connection error"))

        await server._identify_reader(mock_sock, ("192.168.1.99", 54321))

        on_connected.assert_not_called()
        mock_sock.close.assert_called()

    async def test_empty_name_fallback_to_ip(self):
        server, hass, on_connected, _ = make_server()
        mock_sock = MagicMock(spec=socket.socket)

        hass.async_add_executor_job = AsyncMock(return_value=("", "2.56"))

        await server._identify_reader(mock_sock, ("10.0.0.1", 12345))

        args = on_connected.call_args[0]
        assert "pepper_c1" in args[0]


class TestApprovalGate:
    async def test_approved_device_calls_on_connected(self):
        from custom_components.pepper_c1.server import PepperC1Server

        hass = MagicMock()
        hass.loop = MagicMock()
        hass.async_add_executor_job = AsyncMock(return_value=("Pepper C1 Door", "2.0"))
        hass.async_create_task = MagicMock()

        on_connected = MagicMock()
        on_discovered = MagicMock()
        is_approved = MagicMock(return_value=True)

        server = PepperC1Server(
            hass=hass,
            port=1234,
            on_reader_connected=on_connected,
            on_reader_disconnected=MagicMock(),
            on_reader_discovered=on_discovered,
            is_approved=is_approved,
        )
        mock_sock = MagicMock(spec=socket.socket)
        await server._identify_reader(mock_sock, ("10.0.0.1", 12345))

        on_connected.assert_called_once()
        on_discovered.assert_not_called()

    async def test_unknown_device_closes_socket_and_fires_discovery(self):
        from custom_components.pepper_c1.server import PepperC1Server

        hass = MagicMock()
        hass.loop = MagicMock()
        hass.async_add_executor_job = AsyncMock(return_value=("Pepper C1 New", "2.0"))
        hass.async_create_task = MagicMock()

        on_connected = MagicMock()
        on_discovered = MagicMock()
        is_approved = MagicMock(return_value=False)

        server = PepperC1Server(
            hass=hass,
            port=1234,
            on_reader_connected=on_connected,
            on_reader_disconnected=MagicMock(),
            on_reader_discovered=on_discovered,
            is_approved=is_approved,
        )
        mock_sock = MagicMock(spec=socket.socket)
        await server._identify_reader(mock_sock, ("10.0.0.2", 12345))

        on_connected.assert_not_called()
        mock_sock.close.assert_called()
        on_discovered.assert_called_once()
        args = on_discovered.call_args[0]
        assert args[0] == "pepper_c1_new"   # device_id
        assert args[1] == "Pepper C1 New"   # name
        assert args[3] == "10.0.0.2"        # ip

    async def test_no_is_approved_always_connects(self):
        """If is_approved=None (legacy), all devices connect immediately."""
        server, hass, on_connected, _ = make_server()
        hass.async_add_executor_job = AsyncMock(return_value=("Pepper C1", "2.0"))
        mock_sock = MagicMock(spec=socket.socket)

        await server._identify_reader(mock_sock, ("10.0.0.3", 12345))

        on_connected.assert_called_once()


class TestSlugify:
    def test_basic(self):
        from custom_components.pepper_c1.server import _slugify
        assert _slugify("Pepper C1 Front Door") == "pepper_c1_front_door"

    def test_special_chars(self):
        from custom_components.pepper_c1.server import _slugify
        assert _slugify("Pepper C1 #1") == "pepper_c1_1"

    def test_empty_string(self):
        from custom_components.pepper_c1.server import _slugify
        assert _slugify("") == "pepper_c1"

    def test_ip_address(self):
        from custom_components.pepper_c1.server import _slugify
        result = _slugify("192.168.1.100")
        assert result == "192_168_1_100"
