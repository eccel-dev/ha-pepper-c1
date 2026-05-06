"""pytest configuration for Pepper C1 integration tests."""
from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def sample_entry_data():
    """Sample config entry data (server mode)."""
    return {
        "server_port": 1234,
    }


@pytest.fixture
def mock_socket():
    """Mock TCP socket."""
    sock = MagicMock(spec=socket.socket)
    return sock


@pytest.fixture
def mock_server():
    """Mock PepperC1Server."""
    server = MagicMock()
    server.start = AsyncMock()
    server.stop = AsyncMock()
    return server
