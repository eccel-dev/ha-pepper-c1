# ha-pepper-c1

[Home Assistant](https://www.home-assistant.io/) integration for the **Eccel C1** RFID reader over TCP/network.

## Requirements

- Home Assistant 2024.1+
- Eccel C1 with TCP interface enabled
- HACS (for UI installation) or direct access to the `custom_components/` folder

## Connection Modes

The integration supports two connection modes depending on how your network and reader are configured.

### Client mode (HA connects to the reader)

Home Assistant acts as a TCP client and connects to the reader, which must have its **TCP server** mode enabled.

This is the simpler setup — no port forwarding needed. Just provide the reader's IP address and port in the integration configuration.

### HUB mode (reader connects to HA)

Home Assistant acts as a TCP server (hub), and the reader acts as a TCP client that connects to HA.

Use this mode when the reader initiates connections (e.g. it is behind NAT or on a separate network segment). You need to:

- Enable **TCP client** mode on the reader and point it at the HA host IP and port
- If Home Assistant runs in **Docker**, expose the hub port in your `docker-compose.yml` or `docker run` command:

```yaml
# docker-compose.yml example
ports:
  - "8765:8765"   # adjust to the port configured in the integration
```

## Installation via HACS

1. In HACS click **Integrations → ⋮ → Custom repositories**
2. Enter URL: `https://github.com/eccel-dev/ha-pepper-c1`
3. Category: **Integration**
4. Click **Add**, then install and restart HA

## Manual Installation

Copy the `custom_components/pepper_c1/` folder to `/config/custom_components/` on your HA instance and restart.

## Configuration

1. **Settings → Devices & Services → Add Integration**
2. Search for "Eccel C1"
3. Select connection mode and provide the required network settings

Optionally enable **mock mode** — simulates the reader without physical hardware, useful during development.

## Entities

| Entity | Type | Description |
|---|---|---|
| `sensor.pepper_c1_tag_uid` | Sensor | UID of the last detected tag (hex) |
| `sensor.pepper_c1_tag_count` | Sensor | Number of tags in range |
| `sensor.pepper_c1_firmware` | Sensor | Reader firmware version |
| `binary_sensor.pepper_c1_tag_present` | Binary sensor | `true` when a tag is in range |

## Example Automation

```yaml
automation:
  - alias: "Door — unlock on card scan"
    trigger:
      - platform: state
        entity_id: binary_sensor.pepper_c1_tag_present
        to: "on"
    condition:
      - condition: template
        value_template: >
          {{ state_attr('binary_sensor.pepper_c1_tag_present', 'uid') == 'DEADBEEF1234' }}
    action:
      - service: lock.unlock
        target:
          entity_id: lock.front_door
```

## Development

```bash
# Clone
git clone https://github.com/eccel-dev/ha-pepper-c1
cd ha-pepper-c1

# Virtual environment
python -m venv venv
source venv/bin/activate   # Linux/Mac
venv\Scripts\activate      # Windows

# Dependencies
pip install -r requirements-dev.txt

# Tests
pytest

# Linting
ruff check custom_components/
```

## License

MIT
