#!/usr/bin/env python3
"""Pepper C1 reader simulator — connects to HA as a TCP client.

Usage:
    python fake_reader.py [HA_IP] [PORT] [DEVICE_NAME]

Example:
    python fake_reader.py 192.168.1.50 54321 "Pepper C1 Entrance"
    python fake_reader.py localhost 54321
"""
from __future__ import annotations

import socket
import struct
import sys
import time
import threading

# ── Protocol ─────────────────────────────────────────────────────────────────

from pepper_c1.protocol import STX, build_frame, calc_crc  # type: ignore[import]


def parse_frames(buf: bytearray) -> tuple[list[bytes], bytearray]:
    """Extract complete frames from the buffer, return list of payloads and remainder."""
    frames = []
    i = 0
    while i < len(buf):
        if buf[i] != STX:
            i += 1
            continue
        if i + 4 >= len(buf):
            break  # not enough data
        len_l, len_h, chk_l, chk_h = buf[i+1], buf[i+2], buf[i+3], buf[i+4]
        if len_l != (chk_l ^ 0xFF) or len_h != (chk_h ^ 0xFF):
            i += 1
            continue
        total_len = len_l | (len_h << 8)
        frame_end = i + 5 + total_len
        if frame_end > len(buf):
            break  # incomplete frame
        raw = buf[i+5:frame_end]
        payload = raw[:-2]
        crc_recv = raw[-2] | (raw[-1] << 8)
        if calc_crc(payload) == crc_recv:
            frames.append(bytes(payload))
        i = frame_end
    return frames, buf[i:]


# ── Commands ─────────────────────────────────────────────────────────────────

ACK = 0x00
CMD_ERROR = 0xFF
GET_VERSION = 0x0B
PROTO_CONFIG = 0x13
SET_POLLING = 0x06
POLLING_SETUP = 0x16
SET_NET_CFG = 0x09
ASYNC = 0xFE


def ack(cmd: int, data: bytes = b"") -> bytes:
    return build_frame(bytes([ACK, cmd]) + data)


def make_proto_config_response(name: str) -> bytes:
    name_b = name.encode("utf-8")
    payload_data = bytes([0x00, 0x00, 0x00, len(name_b)]) + name_b
    return ack(PROTO_CONFIG, payload_data)


def make_version_response(version: str) -> bytes:
    return ack(GET_VERSION, version.encode("ascii") + b"\x00")


def make_async_frame(uid_hex: str, uid_type: int = 0x01) -> bytes:
    """Async frame — simulates an RFID tag appearing."""
    uid_bytes = bytes.fromhex(uid_hex)
    payload = bytes([ASYNC, 0x00, uid_type, 0x00]) + uid_bytes
    return build_frame(payload)


# ── Main loop ────────────────────────────────────────────────────────────────

def run_fake_reader(host: str, port: int, name: str, version: str = "2.56.FAKE") -> None:
    print(f"[fake_reader] Connecting to {host}:{port} as '{name}'...")
    try:
        sock = socket.create_connection((host, port), timeout=10)
    except OSError as e:
        print(f"[fake_reader] Connection error: {e}")
        print(f"[fake_reader] Check if HA is reachable at {host}:{port}")
        print(f"[fake_reader] Diagnostics: nc -zv {host} {port}")
        return

    print(f"[fake_reader] Connected! Waiting for commands from HA...")
    sock.settimeout(30)
    buf = bytearray()
    polling_enabled = False
    tag_thread: threading.Thread | None = None

    try:
        while True:
            try:
                chunk = sock.recv(256)
            except socket.timeout:
                print("[fake_reader] Timeout — no commands for 30 s")
                break
            if not chunk:
                print("[fake_reader] HA closed the connection")
                break

            buf.extend(chunk)
            frames, buf = parse_frames(buf)

            for payload in frames:
                if not payload:
                    continue
                cmd = payload[0]

                if cmd == PROTO_CONFIG:
                    print(f"[fake_reader] ← PROTO_CONFIG — responding with name: {name!r}")
                    sock.sendall(make_proto_config_response(name))

                elif cmd == GET_VERSION:
                    print(f"[fake_reader] ← GET_VERSION — responding with: {version!r}")
                    sock.sendall(make_version_response(version))

                elif cmd == SET_POLLING:
                    enable = bool(payload[1]) if len(payload) > 1 else False
                    polling_enabled = enable
                    print(f"[fake_reader] ← SET_POLLING({'ON' if enable else 'OFF'}) — ACK")
                    sock.sendall(ack(SET_POLLING))
                    if enable and tag_thread is None:
                        tag_thread = threading.Thread(
                            target=_send_tags_loop,
                            args=(sock,),
                            daemon=True,
                        )
                        tag_thread.start()

                elif cmd == POLLING_SETUP:
                    subcmd = payload[1] if len(payload) > 1 else "?"
                    print(f"[fake_reader] ← POLLING_SETUP(sub=0x{subcmd:02X}) — ACK")
                    sock.sendall(ack(POLLING_SETUP))

                elif cmd == SET_NET_CFG:
                    print(f"[fake_reader] ← SET_NET_CFG — ACK")
                    sock.sendall(ack(SET_NET_CFG))

                else:
                    print(f"[fake_reader] ← Unknown command 0x{cmd:02X} — ACK")
                    sock.sendall(ack(cmd))

    except Exception as e:
        print(f"[fake_reader] Error: {e}")
    finally:
        sock.close()
        print("[fake_reader] Disconnected")


def _send_tags_loop(sock: socket.socket) -> None:
    """Sends an async frame with a dummy RFID tag every 10 s."""
    uid = "DEADBEEF1234"
    uid_type = 0x01  # MIFARE
    interval = 10
    print(f"[fake_reader] Starting to send tags every {interval} s (UID: {uid})")
    while True:
        time.sleep(interval)
        try:
            frame = make_async_frame(uid, uid_type)
            sock.sendall(frame)
            print(f"[fake_reader] → ASYNC tag UID={uid} (MIFARE)")
        except OSError:
            break


if __name__ == "__main__":
    ha_host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    ha_port = int(sys.argv[2]) if len(sys.argv) > 2 else 54321
    device_name = sys.argv[3] if len(sys.argv) > 3 else "Pepper C1 Test"
    run_fake_reader(ha_host, ha_port, device_name)
