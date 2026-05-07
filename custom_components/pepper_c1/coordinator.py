"""Coordinator for Eccel C1 — listens for async RFID frames over TCP."""
from __future__ import annotations

import asyncio
import json
import logging
import queue as _queue
import socket
import threading
import time
import uuid
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_POLLING_TIMEOUT_MS,
    CONF_READER_POLLING_ENABLED,
    DEFAULT_POLLING_TIMEOUT_MS,
    DOMAIN,
    EVENT_TAG_SCANNED,
)

_LOGGER = logging.getLogger(__name__)

_PEPPER_TAG_NS = uuid.UUID("5b4ac81e-ec3b-4f5e-b8e0-f2e7f5e5f50e")


def _uid_to_tag_id(uid: str) -> str:
    """Map a raw RFID UID to a deterministic UUID expected by HA's tag system."""
    return str(uuid.uuid5(_PEPPER_TAG_NS, uid.upper()))


class PepperC1Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator listening for async RFID frames from a single Eccel C1 reader.

    Accepts a ready socket (accepted by PepperC1Server) and starts a blocking
    TCP thread. No frame for polling_timeout_ms → tag gone.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
        on_connection_lost: Any | None = None,
    ) -> None:
        self.device_id = device_id
        self.device_name = device_name
        self._on_connection_lost = on_connection_lost
        self.polling_timeout_ms: int = entry.options.get(
            CONF_POLLING_TIMEOUT_MS,
            entry.data.get(CONF_POLLING_TIMEOUT_MS, DEFAULT_POLLING_TIMEOUT_MS),
        )

        self._firmware: str | None = None
        self._socket: socket.socket | None = None
        self._stop_event = threading.Event()
        self._polling_active: bool = False
        self._reader_polling_active: bool = entry.options.get(CONF_READER_POLLING_ENABLED, True)
        self._listener_thread: threading.Thread | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._last_frame_time: float = 0.0
        self._tag_timeout_cancel: Any | None = None
        self._last_scanned_uid: str | None = None
        self._cmd_queue: _queue.SimpleQueue = _queue.SimpleQueue()

        super().__init__(hass, _LOGGER, name=f"{DOMAIN}_{device_id}", update_interval=None)

    # ------------------------------------------------------------------ #
    # Initialization                                                       #
    # ------------------------------------------------------------------ #

    async def _async_update_data(self) -> dict[str, Any]:
        return self._initial_state()

    def _initial_state(self) -> dict[str, Any]:
        return {
            "tag_present": False,
            "uid": None,
            "tag_count": 0,
            "firmware": self._firmware,
            "available": False,
            "tag_type": None,
            "tag_index": None,
            "reader_uptime_ms": None,
            "known_tag": None,
            "antenna": None,
            "memory": None,
        }

    # ------------------------------------------------------------------ #
    # Start / stop / reconnect                                            #
    # ------------------------------------------------------------------ #

    @property
    def polling_active(self) -> bool:
        return self._polling_active

    @property
    def reader_polling_active(self) -> bool:
        return self._reader_polling_active and self._polling_active

    def enqueue_reader_command(self, cmd) -> None:
        """Send a command to the TCP thread. cmd(reader) runs in the listener thread."""
        self._cmd_queue.put(cmd)

    def _drain_cmd_queue(self) -> None:
        while True:
            try:
                self._cmd_queue.get(block=False)
            except _queue.Empty:
                break

    async def async_start(self, sock: socket.socket | None = None) -> None:
        """Start listening on the given socket.

        If sock=None, self._socket is reused (after a previous stop).
        """
        if sock is not None:
            self._socket = sock
        if self._socket is None:
            raise ValueError("No socket — provide a socket on first start")

        self._polling_active = True
        self._stop_event.clear()
        self._drain_cmd_queue()
        self._watchdog_task = asyncio.ensure_future(self._tag_watchdog_loop())
        self._listener_thread = threading.Thread(
            target=self._real_listener_loop,
            daemon=True,
            name=f"pepper_c1_{self.device_id}",
        )
        self._listener_thread.start()

    async def async_stop(self) -> None:
        """Stop listening."""
        self._polling_active = False
        self._stop_event.set()

        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            await asyncio.gather(self._watchdog_task, return_exceptions=True)
            self._watchdog_task = None

        self._last_scanned_uid = None
        current = self.data or {}
        self.async_set_updated_data(
            {**current, "tag_present": False, "uid": None, "tag_count": 0}
        )

    async def async_reconnect(self, new_sock: socket.socket) -> None:
        """Handle reader reconnection with a new socket."""
        await self.async_stop()
        await self.async_start(new_sock)

    # ------------------------------------------------------------------ #
    # TCP thread — blocking IO                                            #
    # ------------------------------------------------------------------ #

    def _real_listener_loop(self) -> None:
        """TCP loop in a separate thread — single run, no retry (server handles reconnect)."""
        from pepper_c1 import Command, CommandError, PepperC1, PollingEventFormat, TransportError  # noqa: PLC0415
        from pepper_c1.transport import TCPTransport  # noqa: PLC0415

        if self._socket is None:
            return

        transport = TCPTransport.from_socket(self._socket)
        try:
            with PepperC1(transport) as reader:
                try:
                    firmware = reader.get_version()
                except Exception:
                    firmware = self._firmware

                reader.set_polling(False)
                reader.polling_setup_timeout(self.polling_timeout_ms)
                reader.polling_setup_async(known=False, frame_format=PollingEventFormat.JSON)
                reader.polling_setup_async(known=True, frame_format=PollingEventFormat.JSON)
                if self._reader_polling_active:
                    reader.set_polling(True)
                self.hass.loop.call_soon_threadsafe(self._on_connected, firmware)
                _LOGGER.debug(
                    "Eccel C1 %r: firmware=%s, polling=%s (timeout=%d ms)",
                    self.device_id,
                    firmware,
                    self._reader_polling_active,
                    self.polling_timeout_ms,
                )

                try:
                    self._read_frames(reader._transport, Command.ASYNC, reader)
                finally:
                    for known in (False, True):
                        try:
                            reader.polling_setup_async(known=known, frame_format=PollingEventFormat.NONE)
                        except (CommandError, TransportError):
                            pass
                    try:
                        reader.set_polling(False)
                    except (CommandError, TransportError):
                        pass

        except Exception as err:
            _LOGGER.warning("Eccel C1 %r: connection error: %s", self.device_id, err)

        if not self._stop_event.is_set():
            _LOGGER.warning("Eccel C1 %r: disconnected", self.device_id)
            self.hass.loop.call_soon_threadsafe(self._on_disconnected)

    _EOF_CHUNK_THRESHOLD = 0.02
    _EOF_CONSECUTIVE = 5

    _JSON_BUF_MAX = 4096

    def _read_frames(self, transport: Any, async_marker: Any, reader: Any = None) -> None:
        """Blocking TCP frame read loop.

        JSON events arrive as raw UTF-8 text (no binary envelope).
        Binary frames are wrapped with 0xF5 STX and handled by FrameParser.
        """
        from pepper_c1 import TransportError  # noqa: PLC0415
        from pepper_c1.protocol import FrameParser  # noqa: PLC0415

        parser = FrameParser()
        json_buf = b""
        fast_empty_count = 0
        _json_decoder = json.JSONDecoder()

        while not self._stop_event.is_set():
            if reader is not None:
                try:
                    while True:
                        cmd = self._cmd_queue.get(block=False)
                        try:
                            cmd(reader)
                        except Exception as cmd_err:  # noqa: BLE001
                            _LOGGER.warning("Eccel C1 %r: reader command error: %s", self.device_id, cmd_err)
                except _queue.Empty:
                    pass

            t0 = time.monotonic()
            try:
                chunk = transport._read_chunk(256)
            except TransportError:
                _LOGGER.warning("Eccel C1 %r: TCP read error", self.device_id)
                return

            elapsed = time.monotonic() - t0

            if chunk:
                fast_empty_count = 0

                if json_buf or chunk[0:1] == b"{":
                    # Accumulating raw JSON text
                    json_buf += chunk
                    if len(json_buf) > self._JSON_BUF_MAX:
                        _LOGGER.warning("Eccel C1 %r: JSON buffer overflow, resetting", self.device_id)
                        json_buf = b""
                        continue
                    try:
                        json_data, _ = _json_decoder.raw_decode(
                            json_buf.decode("utf-8", errors="replace")
                        )
                        if isinstance(json_data, dict) and json_data.get("type") == "uid":
                            self._last_frame_time = time.monotonic()
                            self.hass.loop.call_soon_threadsafe(
                                self._on_tag_frame_json, json_data
                            )
                        json_buf = b""
                    except (ValueError, json.JSONDecodeError):
                        pass  # incomplete JSON — wait for next chunk
                else:
                    # Binary framed data (STX = 0xF5)
                    for payload in parser.feed(chunk):
                        if not payload or payload[0] != async_marker or len(payload) < 5:
                            continue
                        uid_type: int = payload[2]
                        uid_hex: str = payload[4:].hex().upper()
                        self._last_frame_time = time.monotonic()
                        self.hass.loop.call_soon_threadsafe(self._on_tag_frame, uid_hex, uid_type)
            else:
                if elapsed < self._EOF_CHUNK_THRESHOLD:
                    fast_empty_count += 1
                    if fast_empty_count >= self._EOF_CONSECUTIVE:
                        _LOGGER.warning("Eccel C1 %r: EOF (device disconnected)", self.device_id)
                        return
                else:
                    fast_empty_count = 0

    # ------------------------------------------------------------------ #
    # HA event loop callbacks                                             #
    # ------------------------------------------------------------------ #

    @callback
    def _on_connected(self, firmware: str | None) -> None:
        self._firmware = firmware
        current = self.data or {}
        self.async_set_updated_data({**current, "firmware": firmware, "available": True})

    @callback
    def _on_tag_frame_json(self, data: dict[str, Any]) -> None:
        uid_hex: str = data.get("uid", "")
        current = self.data or {}
        new_state = {
            "tag_present": True,
            "uid": uid_hex,
            "tag_count": 1,
            "firmware": self._firmware,
            "available": True,
            "tag_type": data.get("string"),
            "tag_index": data.get("tag_index"),
            "reader_uptime_ms": data.get("uptime_ms"),
            "known_tag": data.get("known_tag"),
            "antenna": data.get("antenna"),
            "memory": data.get("memory"),
        }
        if current.get("tag_present") and current.get("uid") == uid_hex:
            changed = {k: v for k, v in new_state.items() if current.get(k) != v}
            if changed:
                self.async_set_updated_data({**current, **changed})
            return

        self.async_set_updated_data(new_state)
        self._fire_tag_scanned_event(
            uid=uid_hex,
            tag_type=data.get("string"),
            antenna=data.get("antenna"),
            tag_index=data.get("tag_index"),
            known_tag=data.get("known_tag"),
            memory_content=data.get("memory"),
        )

    @callback
    def _on_tag_frame(self, uid_hex: str, uid_type: int) -> None:
        if uid_type & 0x10:
            family = "ICODE"
        elif uid_type & 0x01:
            family = "MIFARE"
        else:
            family = f"0x{uid_type:02X}"

        current = self.data or {}
        if current.get("tag_present") and current.get("uid") == uid_hex:
            return

        self.async_set_updated_data(
            {
                "tag_present": True,
                "uid": uid_hex,
                "tag_count": 1,
                "firmware": self._firmware,
                "available": True,
                "tag_type": family,
                "tag_index": None,
                "reader_uptime_ms": current.get("reader_uptime_ms"),
                "known_tag": None,
                "antenna": None,
                "memory": None,
            }
        )
        self._fire_tag_scanned_event(
            uid=uid_hex,
            tag_type=family,
            antenna=None,
            tag_index=None,
            known_tag=None,
            memory_content=None,
        )

    @callback
    def _async_tag_timeout(self) -> None:
        """Callback called when the tag leaves the RF field."""
        self._tag_timeout_cancel = None
        current = self.data or {}
        self.async_set_updated_data(
            {
                **current,
                "tag_present": False,
                "uid": None,
                "tag_count": 0,
                "tag_type": None,
                "tag_index": None,
                "known_tag": None,
                "antenna": None,
                "memory": None,
            }
        )

    async def _tag_watchdog_loop(self) -> None:
        """Checks every 50 ms if polling_timeout + 300 ms has elapsed since the last frame."""
        threshold = self.polling_timeout_ms / 1000.0 + 0.3
        try:
            while self._polling_active:
                await asyncio.sleep(0.05)
                if (self.data or {}).get("tag_present") and \
                        time.monotonic() - self._last_frame_time > threshold:
                    current = self.data or {}
                    self.async_set_updated_data(
                        {
                            **current,
                            "tag_present": False,
                            "uid": None,
                            "tag_count": 0,
                            "tag_type": None,
                            "tag_index": None,
                            "known_tag": None,
                            "antenna": None,
                            "memory": None,
                        }
                    )
        except asyncio.CancelledError:
            pass

    @callback
    def _on_disconnected(self) -> None:
        self._last_frame_time = 0.0
        self._last_scanned_uid = None
        if self._tag_timeout_cancel is not None:
            self._tag_timeout_cancel()
            self._tag_timeout_cancel = None
        current = self.data or {}
        self.async_set_updated_data(
            {**current, "tag_present": False, "uid": None, "tag_count": 0, "available": False}
        )
        if self._on_connection_lost is not None:
            self._on_connection_lost()

    @callback
    def _fire_tag_scanned_event(
        self,
        uid: str,
        tag_type: str | None,
        antenna: int | None,
        tag_index: int | None,
        known_tag: bool | None,
        memory_content: str | None,
    ) -> None:
        self.hass.bus.async_fire(
            EVENT_TAG_SCANNED,
            {
                "uid": uid,
                "tag_type": tag_type,
                "memory_content": memory_content,
                "antenna": antenna,
                "tag_index": tag_index,
                "known_tag": known_tag,
                "device_id": self.device_id,
                "device_name": self.device_name,
            },
        )
        try:
            from homeassistant.components import tag as ha_tag  # noqa: PLC0415
            self.hass.async_create_task(
                ha_tag.async_scan_tag(self.hass, _uid_to_tag_id(uid), self.device_id)
            )
        except Exception:  # noqa: BLE001
            pass
