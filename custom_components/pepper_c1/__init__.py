"""Eccel C1 RFID Reader integration for Home Assistant."""
from __future__ import annotations

import logging
import socket

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store

from .const import (
    CONF_CONNECTION_MODE,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_DEVICE_TYPE,
    CONF_HUB_ENTRY_ID,
    CONF_SERVER_PORT,
    CONNECTION_MODE_CLIENT,
    CONNECTION_MODE_HUB,
    DATA_APPROVED_DEVICES,
    DATA_CLIENT,
    DATA_COORDINATORS,
    DATA_ENTITY_ADDERS,
    DATA_SERVER,
    DATA_STORE,
    DEFAULT_SERVER_PORT,
    DEVICE_TYPE_READER,
    DOMAIN,
)
from .client import PepperC1Client
from .coordinator import PepperC1Coordinator
from .server import PepperC1Server

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "switch", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up integration from config entry."""
    if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_READER:
        return True

    mode = entry.data.get(CONF_CONNECTION_MODE, CONNECTION_MODE_HUB)
    if mode == CONNECTION_MODE_CLIENT:
        return await _setup_client_entry(hass, entry)
    return await _setup_hub_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload integration."""
    if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_READER:
        return True

    mode = entry.data.get(CONF_CONNECTION_MODE, CONNECTION_MODE_HUB)
    if mode == CONNECTION_MODE_CLIENT:
        return await _unload_client_entry(hass, entry)
    return await _unload_hub_entry(hass, entry)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migration from v1 (client mode) is not possible — user must reconfigure."""
    _LOGGER.warning(
        "Eccel C1: config entry version %d is not supported (v2 requires a new configuration). "
        "Remove and re-add the integration.",
        entry.version,
    )
    return False


# ---------------------------------------------------------------------------
# Hub entry
# ---------------------------------------------------------------------------

async def _setup_hub_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start TCP server and load approved devices from Store."""
    hass.data.setdefault(DOMAIN, {})

    store = Store(hass, 1, f"pepper_c1.{entry.entry_id}")
    stored: dict = await store.async_load() or {"approved_devices": {}}

    approved: set[str] = set(stored.get("approved_devices", {}).keys())

    old_device_entries = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_READER
        and e.data.get(CONF_HUB_ENTRY_ID) == entry.entry_id
    ]
    if old_device_entries:
        for dev_entry in old_device_entries:
            device_id = dev_entry.data.get(CONF_DEVICE_ID)
            if device_id and device_id not in stored["approved_devices"]:
                stored["approved_devices"][device_id] = {
                    "name": dev_entry.data.get(CONF_DEVICE_NAME, dev_entry.title),
                    "firmware": dev_entry.data.get("firmware"),
                }
                approved.add(device_id)
        await store.async_save(stored)
        for dev_entry in old_device_entries:
            hass.async_create_task(hass.config_entries.async_remove(dev_entry.entry_id))
        _LOGGER.info("Eccel C1: migrated %d old device entries to Store", len(old_device_entries))

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_SERVER: None,
        DATA_COORDINATORS: {},
        DATA_ENTITY_ADDERS: {},
        DATA_APPROVED_DEVICES: approved,
        DATA_STORE: store,
        DATA_CLIENT: None,
    }

    def _is_approved(device_id: str) -> bool:
        hub = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        return device_id in hub.get(DATA_APPROVED_DEVICES, set())

    def _on_reader_discovered(
        device_id: str, name: str, firmware: str | None, ip: str
    ) -> None:
        hass.async_create_task(
            _fire_discovery(hass, entry, device_id, name, firmware, ip)
        )

    port = entry.data.get(CONF_SERVER_PORT, DEFAULT_SERVER_PORT)
    server = PepperC1Server(
        hass=hass,
        port=port,
        on_reader_connected=lambda device_id, name, sock, firmware: (
            hass.async_create_task(
                _on_reader_connected(hass, entry, device_id, name, sock, firmware)
            )
        ),
        on_reader_disconnected=lambda device_id: (
            hass.async_create_task(
                _on_reader_disconnected(hass, entry, device_id)
            )
        ),
        on_reader_discovered=_on_reader_discovered,
        is_approved=_is_approved,
    )
    await server.start()
    hass.data[DOMAIN][entry.entry_id][DATA_SERVER] = server

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("Eccel C1 hub started on port %d (%d approved devices)", port, len(approved))
    return True


async def _unload_hub_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop server and unload hub platforms."""
    hub = hass.data[DOMAIN][entry.entry_id]

    server: PepperC1Server | None = hub[DATA_SERVER]
    if server is not None:
        await server.stop()

    for coordinator in hub[DATA_COORDINATORS].values():
        await coordinator.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


# ---------------------------------------------------------------------------
# Client entry
# ---------------------------------------------------------------------------

async def _setup_client_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a direct TCP client entry — HA connects to the reader."""
    hass.data.setdefault(DOMAIN, {})

    device_id: str = entry.data["device_id"]
    device_name: str = entry.data.get("device_name", "Eccel C1")
    host: str = entry.data[CONF_HOST]
    port: int = entry.data[CONF_PORT]

    coordinator = PepperC1Coordinator(hass, entry, device_id, device_name)
    coordinator.async_set_updated_data(coordinator._initial_state())

    client = PepperC1Client(hass, coordinator, host, port)

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_SERVER: None,
        DATA_COORDINATORS: {device_id: coordinator},
        DATA_ENTITY_ADDERS: {},
        DATA_APPROVED_DEVICES: set(),
        DATA_STORE: None,
        DATA_CLIENT: client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Apply saved area if present
    area_id: str | None = entry.data.get("area_id")
    if area_id:
        hass.async_create_task(_apply_device_area(hass, device_id, area_id))

    await client.async_start()

    _LOGGER.info("Eccel C1 client started: %r → %s:%d", device_name, host, port)
    return True


async def _unload_client_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop TCP client and unload platforms."""
    hub = hass.data[DOMAIN][entry.entry_id]

    client: PepperC1Client | None = hub[DATA_CLIENT]
    if client is not None:
        await client.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


# ---------------------------------------------------------------------------
# Discovery helpers (hub mode only)
# ---------------------------------------------------------------------------

async def _fire_discovery(
    hass: HomeAssistant,
    hub_entry: ConfigEntry,
    device_id: str,
    name: str,
    firmware: str | None,
    ip: str,
) -> None:
    await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
        data={
            "hub_entry_id": hub_entry.entry_id,
            "device_id": device_id,
            "name": name,
            "firmware": firmware,
            "ip": ip,
        },
    )


async def _on_reader_connected(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_id: str,
    device_name: str,
    sock: socket.socket,
    firmware: str | None,
) -> None:
    hub = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, PepperC1Coordinator] = hub[DATA_COORDINATORS]

    if device_id in coordinators:
        _LOGGER.info("Eccel C1 %r: reconnected", device_id)
        await coordinators[device_id].async_reconnect(sock)
        return

    _LOGGER.info("Eccel C1 %r: first connection of approved reader %r", device_id, device_name)
    coordinator = PepperC1Coordinator(hass, entry, device_id, device_name)
    coordinator.async_set_updated_data(coordinator._initial_state())
    await coordinator.async_start(sock)

    if firmware is not None:
        coordinator._firmware = firmware

    coordinators[device_id] = coordinator
    _add_entities_for_coordinator(coordinator, entry, hub[DATA_ENTITY_ADDERS])

    store: Store = hub[DATA_STORE]
    stored = await store.async_load() or {}
    area_id: str | None = stored.get("approved_devices", {}).get(device_id, {}).get("area_id")
    if area_id:
        hass.async_create_task(_apply_device_area(hass, device_id, area_id))


async def _apply_device_area(hass: HomeAssistant, device_id: str, area_id: str) -> None:
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, device_id)})
    if device:
        dev_reg.async_update_device(device.id, area_id=area_id)
        _LOGGER.debug("Eccel C1: device %r assigned to area %r", device_id, area_id)


async def _on_reader_disconnected(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_id: str,
) -> None:
    _LOGGER.info("Eccel C1 %r: disconnected", device_id)


def _add_entities_for_coordinator(
    coordinator: PepperC1Coordinator,
    entry: ConfigEntry,
    entity_adders: dict,
) -> None:
    from .sensor import (  # noqa: PLC0415
        PepperC1FirmwareSensor,
        PepperC1ReaderUptimeSensor,
        PepperC1TagTypeSensor,
        PepperC1TagUIDSensor,
    )
    from .binary_sensor import PepperC1TagPresentSensor  # noqa: PLC0415
    from .switch import PepperC1PollingSwitch  # noqa: PLC0415
    from .number import PepperC1PollingTimeoutNumber  # noqa: PLC0415

    if "sensor" in entity_adders:
        entity_adders["sensor"]([
            PepperC1TagUIDSensor(coordinator, entry),
            PepperC1TagTypeSensor(coordinator, entry),
            PepperC1ReaderUptimeSensor(coordinator, entry),
            PepperC1FirmwareSensor(coordinator, entry),
        ])
    if "binary_sensor" in entity_adders:
        entity_adders["binary_sensor"]([
            PepperC1TagPresentSensor(coordinator, entry),
        ])
    if "switch" in entity_adders:
        entity_adders["switch"]([PepperC1PollingSwitch(coordinator, entry)])
    if "number" in entity_adders:
        entity_adders["number"]([PepperC1PollingTimeoutNumber(coordinator, entry)])
