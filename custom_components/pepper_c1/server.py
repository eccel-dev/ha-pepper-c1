"""TCP server — accepts connections from Eccel C1 readers."""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Any, Callable

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class _AcceptProtocol(asyncio.Protocol):
    """Protocol that accepts a new TCP connection and hands the socket to a handler."""

    def __init__(
        self,
        hass: HomeAssistant,
        on_connect: Callable[[socket.socket, tuple[str, int]], None],
    ) -> None:
        self._hass = hass
        self._on_connect = on_connect

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        transport_sock = transport.get_extra_info("socket")
        peername: tuple[str, int] = transport.get_extra_info("peername")
        # Duplicate the file descriptor — creates a regular socket outside asyncio's control.
        # Then close the asyncio transport (releases its copy of the fd).
        real_sock = socket.socket(fileno=os.dup(transport_sock.fileno()))
        transport.close()
        _LOGGER.debug("New connection from %s:%d", peername[0], peername[1])
        self._hass.loop.call_soon(self._on_connect, real_sock, peername)

    def connection_lost(self, exc: Exception | None) -> None:
        pass


class PepperC1Server:
    """Asyncio TCP server listening for connections from Eccel C1 readers.

    When a reader connects, the server queries it for name and firmware (in an executor).
    If the device is already approved (is_approved returns True), it calls
    on_reader_connected. Otherwise it closes the socket and calls
    on_reader_discovered — the hub then triggers an approval flow in HA UI.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        port: int,
        on_reader_connected: Callable[[str, str, socket.socket, str | None], Any],
        on_reader_disconnected: Callable[[str], Any],
        on_reader_discovered: Callable[[str, str, str | None, str], Any] | None = None,
        is_approved: Callable[[str], bool] | None = None,
    ) -> None:
        self._hass = hass
        self._port = port
        self._on_reader_connected = on_reader_connected
        self._on_reader_disconnected = on_reader_disconnected
        self._on_reader_discovered = on_reader_discovered
        self._is_approved = is_approved
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Start the TCP server on the configured port."""
        loop = self._hass.loop
        self._server = await loop.create_server(
            lambda: _AcceptProtocol(self._hass, self._handle_raw_connection),
            host="0.0.0.0",
            port=self._port,
            reuse_address=True,
        )
        _LOGGER.info("Eccel C1 server listening on port %d", self._port)

    async def stop(self) -> None:
        """Stop the TCP server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            _LOGGER.info("Eccel C1 server stopped")

    def _handle_raw_connection(
        self, sock: socket.socket, peername: tuple[str, int]
    ) -> None:
        """Called internally in the event loop when a client connects."""
        self._hass.async_create_task(
            self._identify_reader(sock, peername)
        )

    async def _identify_reader(
        self, sock: socket.socket, peername: tuple[str, int]
    ) -> None:
        """Query the reader for name and firmware, then decide whether to accept it."""
        peer_ip = peername[0]

        def _query() -> tuple[str, str | None]:
            from pepper_c1 import CommandError, PepperC1, TransportError  # noqa: PLC0415
            from pepper_c1.transport import TCPTransport  # noqa: PLC0415

            transport = TCPTransport.from_socket(sock)
            reader = PepperC1(transport)
            try:
                name = reader.get_device_name()
                if not name:
                    name = f"Eccel C1 ({peer_ip})"
            except (CommandError, TransportError, Exception):
                name = f"Eccel C1 ({peer_ip})"
            try:
                firmware = reader.get_version()
            except (CommandError, TransportError, Exception):
                firmware = None
            return name, firmware

        try:
            name, firmware = await self._hass.async_add_executor_job(_query)
        except Exception as err:
            _LOGGER.warning("Eccel C1: reader identification error %s: %s", peer_ip, err)
            try:
                sock.close()
            except OSError:
                pass
            return

        device_id = _slugify(name)

        if self._is_approved is None or self._is_approved(device_id):
            # Approved device — pass socket to coordinator
            _LOGGER.info(
                "Eccel C1 reader connected: name=%r device_id=%r firmware=%s",
                name, device_id, firmware,
            )
            self._on_reader_connected(device_id, name, sock, firmware)
        else:
            # Unknown device — close socket, trigger approval flow
            _LOGGER.info(
                "New unapproved reader: name=%r device_id=%r ip=%s — awaiting approval",
                name, device_id, peer_ip,
            )
            try:
                sock.close()
            except OSError:
                pass
            if self._on_reader_discovered is not None:
                self._on_reader_discovered(device_id, name, firmware, peer_ip)


def _slugify(text: str) -> str:
    """Convert a string to a safe identifier (lowercase, underscores)."""
    import re
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or "pepper_c1"
