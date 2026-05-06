"""TCP client — HA connects to a Eccel C1 reader at a fixed host:port with auto-reconnect."""
from __future__ import annotations

import asyncio
import logging
import socket
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from .coordinator import PepperC1Coordinator

_LOGGER = logging.getLogger(__name__)

_RETRY_DELAY = 5.0
_CONNECT_TIMEOUT = 10.0


class PepperC1Client:
    """Manages outgoing TCP connection to a Eccel C1 reader.

    Connects to host:port, passes the socket to the coordinator, and retries
    after disconnection. The coordinator's on_connection_lost callback signals
    when the TCP session ends so the reconnect loop can fire.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: PepperC1Coordinator,
        host: str,
        port: int,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._host = host
        self._port = port
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._disconnected = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    async def async_start(self) -> None:
        self._running = True
        self._coordinator._on_connection_lost = self._on_connection_lost
        self._task = asyncio.ensure_future(self._connect_loop())

    async def async_stop(self) -> None:
        self._running = False
        self._disconnected.set()
        await self._coordinator.async_stop()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    # ------------------------------------------------------------------ #
    # Internal                                                            #
    # ------------------------------------------------------------------ #

    def _on_connection_lost(self) -> None:
        """Called by coordinator (in event loop) when TCP session drops."""
        self._disconnected.set()

    async def _connect_loop(self) -> None:
        first = True
        while self._running:
            sock = await self._connect()
            if sock is None:
                _LOGGER.warning(
                    "Eccel C1 client: cannot connect to %s:%d, retrying in %.0fs",
                    self._host, self._port, _RETRY_DELAY,
                )
                await asyncio.sleep(_RETRY_DELAY)
                continue

            self._disconnected.clear()
            if first:
                await self._coordinator.async_start(sock)
                first = False
            else:
                await self._coordinator.async_reconnect(sock)

            await self._disconnected.wait()

            if self._running:
                _LOGGER.debug(
                    "Eccel C1 client: %s:%d disconnected, retrying in %.0fs",
                    self._host, self._port, _RETRY_DELAY,
                )
                await asyncio.sleep(_RETRY_DELAY)

    async def _connect(self) -> socket.socket | None:
        def _do_connect() -> socket.socket | None:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(_CONNECT_TIMEOUT)
                s.connect((self._host, self._port))
                s.settimeout(None)
                return s
            except OSError as err:
                _LOGGER.debug(
                    "Eccel C1 client: connect to %s:%d failed: %s",
                    self._host, self._port, err,
                )
                return None

        return await self._hass.async_add_executor_job(_do_connect)
