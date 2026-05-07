"""Constants for the Eccel C1 integration."""

DOMAIN = "pepper_c1"

CONF_SERVER_PORT = "server_port"
CONF_POLLING_TIMEOUT_MS = "polling_timeout_ms"
CONF_CONNECTION_MODE = "connection_mode"
CONF_READER_POLLING_ENABLED = "reader_polling_enabled"

DEFAULT_SERVER_PORT = 1234
DEFAULT_READER_PORT = 1234
DEFAULT_POLLING_TIMEOUT_MS = 200  # ms — time without a frame before we consider the tag gone

CONNECTION_MODE_HUB = "hub"
CONNECTION_MODE_CLIENT = "client"

# Legacy — data keys from an older version (needed for migration)
CONF_DEVICE_TYPE = "device_type"
DEVICE_TYPE_READER = "reader"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
CONF_HUB_ENTRY_ID = "hub_entry_id"

# Event fired when a new tag is scanned (once per tag appearance)
EVENT_TAG_SCANNED = "pepper_c1_tag_scanned"

# Keys in hass.data[DOMAIN][entry.entry_id]
DATA_SERVER = "server"
DATA_COORDINATORS = "coordinators"
DATA_ENTITY_ADDERS = "entity_adders"
DATA_APPROVED_DEVICES = "approved_devices"
DATA_STORE = "store"
DATA_CLIENT = "client_connector"
