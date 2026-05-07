"""Config flow — configuration form for the Eccel C1 integration."""
from __future__ import annotations

import logging
import re
import socket
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .const import (
    CONF_CONNECTION_MODE,
    CONF_POLLING_TIMEOUT_MS,
    CONF_SERVER_PORT,
    CONNECTION_MODE_CLIENT,
    CONNECTION_MODE_HUB,
    DATA_APPROVED_DEVICES,
    DATA_STORE,
    DEFAULT_POLLING_TIMEOUT_MS,
    DEFAULT_READER_PORT,
    DEFAULT_SERVER_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _check_port_available(hass: HomeAssistant, port: int) -> bool:
    def _try_bind() -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False

    return await hass.async_add_executor_job(_try_bind)


async def _probe_reader(
    hass: HomeAssistant, host: str, port: int
) -> tuple[str | None, str | None]:
    """Connect to the reader, read name + firmware, then close. Returns (name, firmware) or (None, None)."""
    def _do_probe() -> tuple[str | None, str | None]:
        from pepper_c1 import CommandError, PepperC1, TransportError  # noqa: PLC0415
        from pepper_c1.transport import TCPTransport  # noqa: PLC0415

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((host, port))
            s.settimeout(None)
        except OSError:
            return None, None

        transport = TCPTransport.from_socket(s)
        reader = PepperC1(transport)
        try:
            name = reader.get_device_name() or f"Eccel C1 ({host})"
        except (CommandError, TransportError, Exception):
            name = f"Eccel C1 ({host})"
        try:
            firmware = reader.get_version()
        except (CommandError, TransportError, Exception):
            firmware = None
        try:
            s.close()
        except OSError:
            pass
        return name, firmware

    try:
        return await hass.async_add_executor_job(_do_probe)
    except Exception:
        return None, None


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_") or "pepper_c1"


class PepperC1ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for the Eccel C1 integration."""

    VERSION = 2

    def __init__(self) -> None:
        self._discovery_info: dict[str, Any] = {}
        self._client_data: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    # Step 1 — choose mode                                                #
    # ------------------------------------------------------------------ #

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            mode = user_input[CONF_CONNECTION_MODE]
            if mode == CONNECTION_MODE_HUB:
                return await self.async_step_hub()
            return await self.async_step_client()

        schema = vol.Schema(
            {
                vol.Required(CONF_CONNECTION_MODE, default=CONNECTION_MODE_HUB): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[CONNECTION_MODE_HUB, CONNECTION_MODE_CLIENT],
                        translation_key="connection_mode",
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    # ------------------------------------------------------------------ #
    # Hub mode                                                            #
    # ------------------------------------------------------------------ #

    async def async_step_hub(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            port = user_input[CONF_SERVER_PORT]
            if not await _check_port_available(self.hass, port):
                errors["base"] = "port_in_use"

            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Eccel C1 Hub (port {port})",
                    data={
                        CONF_CONNECTION_MODE: CONNECTION_MODE_HUB,
                        CONF_SERVER_PORT: port,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_SERVER_PORT, default=DEFAULT_SERVER_PORT): vol.All(
                    int, vol.Range(min=1024, max=65535)
                ),
            }
        )
        return self.async_show_form(step_id="hub", data_schema=schema, errors=errors)

    # ------------------------------------------------------------------ #
    # Client mode — step 1: host + port                                  #
    # ------------------------------------------------------------------ #

    async def async_step_client(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]

            name, firmware = await _probe_reader(self.hass, host, port)
            if name is None:
                errors["base"] = "cannot_connect"
            else:
                self._client_data = {
                    CONF_HOST: host,
                    CONF_PORT: port,
                    "probed_name": name,
                    "firmware": firmware,
                }
                return await self.async_step_client_confirm()

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_READER_PORT): vol.All(
                    int, vol.Range(min=1, max=65535)
                ),
            }
        )
        return self.async_show_form(step_id="client", data_schema=schema, errors=errors)

    # ------------------------------------------------------------------ #
    # Client mode — step 2: confirm name + settings                      #
    # ------------------------------------------------------------------ #

    async def async_step_client_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            host = self._client_data[CONF_HOST]
            port = self._client_data[CONF_PORT]
            firmware = self._client_data["firmware"]
            name = (user_input.get("device_name") or "").strip() or self._client_data["probed_name"]
            polling_timeout = user_input.get(CONF_POLLING_TIMEOUT_MS, DEFAULT_POLLING_TIMEOUT_MS)
            area_id: str | None = user_input.get("area_id") or None
            device_id = _slugify(f"{host}_{port}")

            await self.async_set_unique_id(f"{DOMAIN}_client_{host}_{port}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=name,
                data={
                    CONF_CONNECTION_MODE: CONNECTION_MODE_CLIENT,
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_POLLING_TIMEOUT_MS: polling_timeout,
                    "device_name": name,
                    "device_id": device_id,
                    "firmware": firmware,
                    "area_id": area_id,
                },
            )

        schema = vol.Schema(
            {
                vol.Required("device_name", default=self._client_data["probed_name"]): str,
                vol.Required(CONF_POLLING_TIMEOUT_MS, default=DEFAULT_POLLING_TIMEOUT_MS): vol.All(
                    int, vol.Range(min=0, max=5000)
                ),
                vol.Optional("area_id"): selector.AreaSelector(),
            }
        )
        return self.async_show_form(
            step_id="client_confirm",
            data_schema=schema,
            description_placeholders={
                "firmware": self._client_data.get("firmware") or "unknown",
                "host": self._client_data[CONF_HOST],
                "port": str(self._client_data[CONF_PORT]),
            },
        )

    # ------------------------------------------------------------------ #
    # Discovery — approval of readers connected to hub                   #
    # ------------------------------------------------------------------ #

    async def async_step_integration_discovery(
        self, discovery_info: config_entries.DiscoveryInfoType
    ) -> config_entries.FlowResult:
        hub_entry_id = discovery_info["hub_entry_id"]
        device_id = discovery_info["device_id"]
        await self.async_set_unique_id(f"{hub_entry_id}_{device_id}")
        self._discovery_info = dict(discovery_info)
        self.context["title_placeholders"] = {
            "name": discovery_info.get("name") or f"Eccel C1 ({discovery_info.get('ip', '?')})"
        }
        return await self.async_step_confirm_device()

    async def async_step_confirm_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            name = (user_input.get("device_name") or "").strip() or self._discovery_info.get("name", "Eccel C1")
            hub_entry_id = self._discovery_info["hub_entry_id"]
            device_id = self._discovery_info["device_id"]
            firmware = self._discovery_info.get("firmware")

            hub = self.hass.data.get(DOMAIN, {}).get(hub_entry_id, {})
            store = hub.get(DATA_STORE)
            if store is None:
                from homeassistant.helpers.storage import Store  # noqa: PLC0415
                store = Store(self.hass, 1, f"pepper_c1.{hub_entry_id}")

            stored = await store.async_load() or {"approved_devices": {}}
            area_id: str | None = user_input.get("area_id") or None
            stored["approved_devices"][device_id] = {"name": name, "firmware": firmware, "area_id": area_id}
            await store.async_save(stored)

            hub.setdefault(DATA_APPROVED_DEVICES, set()).add(device_id)

            _LOGGER.info("Eccel C1: approved reader %r as %r", device_id, name)
            return self.async_abort(reason="device_approved")

        suggested_name = self._discovery_info.get("name", "Eccel C1")
        schema = vol.Schema(
            {
                vol.Required("device_name", default=suggested_name): str,
                vol.Optional("area_id"): selector.AreaSelector(),
            }
        )
        return self.async_show_form(
            step_id="confirm_device",
            data_schema=schema,
            description_placeholders={
                "device_name": self._discovery_info.get("name", "?"),
                "firmware": self._discovery_info.get("firmware") or "unknown",
                "ip": self._discovery_info.get("ip", "?"),
            },
        )
