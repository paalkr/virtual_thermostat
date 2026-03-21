[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

# Virtual Thermostat

A Home Assistant custom component that adds preset mode support (HOME, ECO, AWAY) to physical thermostats that lack this feature.

## Use case

Some hardware thermostats (e.g., Z-Wave Heatit) don't support preset/profile modes. This component creates a virtual thermostat entity that:

- Acts as a **frontend** to your physical thermostat
- Adds **HOME**, **ECO**, and **AWAY** preset modes, each with its own remembered temperature setpoint
- Maintains **two-way sync** between the virtual and physical thermostat at all times
- If someone changes the temperature at the wall-mounted device, the virtual thermostat updates automatically
- If the physical thermostat is turned off at the wall, the virtual thermostat reflects this
- After a Home Assistant restart, the virtual thermostat **syncs from the physical thermostat** (the physical device is the source of truth)

## How presets work

1. Select a preset mode (e.g., ECO)
2. Set a temperature - it is saved for that preset
3. Switch to another preset - its saved temperature is applied
4. Switch back - the previously saved temperature is restored

Each preset remembers its own temperature independently.

## Installation

### HACS (recommended)

1. Install [HACS](https://hacs.xyz/)
2. Add this repository as a custom repository in HACS settings
3. Search and install "Virtual Thermostat"
4. Add configuration to `configuration.yaml` (see below)
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/virtual_thermostat/` directory to your Home Assistant `custom_components/` directory
2. Add configuration to `configuration.yaml` (see below)
3. Restart Home Assistant

## Configuration

```yaml
climate:
  - platform: virtual_thermostat
    name: Living Room Thermostat
    thermostat: climate.living_room_physical
    target_sensor: sensor.living_room_temperature
    initial_hvac_mode: heat
    precision: 0.5
    unique_id: living_room_virtual_thermostat
```

### Configuration options

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `thermostat` | Yes | - | Entity ID of the physical thermostat to wrap |
| `target_sensor` | Yes | - | Entity ID of the temperature sensor |
| `name` | No | Virtual Thermostat | Display name |
| `ac_mode` | No | false | Set to `true` for cooling mode |
| `min_temp` | No | 7 | Minimum allowed temperature |
| `max_temp` | No | 35 | Maximum allowed temperature |
| `target_temp` | No | - | Initial target temperature (overridden by physical thermostat on startup) |
| `initial_hvac_mode` | No | - | Initial HVAC mode (`heat`, `cool`, or `off`) |
| `precision` | No | 0.5 | Temperature precision (0.1, 0.5, or 1.0) |
| `unique_id` | No | - | Unique ID for the entity (recommended) |

## Works great with Scheduler Component

Use with [scheduler-component](https://github.com/nielsfaber/scheduler-component) to schedule preset mode changes throughout the day (e.g., ECO at night, HOME in the morning).

## Contributions are welcome!

If you want to contribute, please read the [Contribution guidelines](CONTRIBUTING.md).

***

[commits-shield]: https://img.shields.io/github/commit-activity/y/paalkr/virtual_thermostat.svg?style=for-the-badge
[commits]: https://github.com/paalkr/virtual_thermostat/commits/master
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/paalkr/virtual_thermostat.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/paalkr/virtual_thermostat.svg?style=for-the-badge
[releases]: https://github.com/paalkr/virtual_thermostat/releases
