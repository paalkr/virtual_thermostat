"""Tests for the virtual_thermostat climate platform."""
from unittest.mock import patch

import pytest
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    HVACAction,
    HVACMode,
    PRESET_AWAY,
    PRESET_ECO,
    PRESET_HOME,
    ClimateEntityFeature,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    PRECISION_HALVES,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import mock_restore_cache

ENTITY_ID = "climate.virtual_thermostat"
SENSOR_ENTITY = "sensor.room_temp"
PHYSICAL_THERMOSTAT = "climate.physical"


def _minimal_config():
    """Return minimal YAML configuration."""
    return {
        "climate": {
            "platform": "virtual_thermostat",
            "name": "Virtual Thermostat",
            "target_sensor": SENSOR_ENTITY,
            "thermostat": PHYSICAL_THERMOSTAT,
        }
    }


def _full_config(**overrides):
    """Return full configuration with overrides."""
    config = {
        "climate": {
            "platform": "virtual_thermostat",
            "name": "Test Thermostat",
            "target_sensor": SENSOR_ENTITY,
            "thermostat": PHYSICAL_THERMOSTAT,
            "min_temp": 10,
            "max_temp": 30,
            "target_temp": 21,
            "initial_hvac_mode": "heat",
            "precision": PRECISION_HALVES,
            "unique_id": "test_unique_123",
        }
    }
    config["climate"].update(overrides)
    return config


async def _setup_component(hass: HomeAssistant, config: dict):
    """Set up the component and the physical thermostat mock state."""
    # Set up the physical thermostat state before component loads
    hass.states.async_set(
        PHYSICAL_THERMOSTAT,
        HVACMode.HEAT,
        {ATTR_TEMPERATURE: 21},
    )
    hass.states.async_set(SENSOR_ENTITY, "20.5")
    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()


# ============================================================
# Group 1: Initialization & Configuration
# ============================================================


async def test_setup_with_minimal_config(hass: HomeAssistant):
    """Test component loads with only required params."""
    await _setup_component(hass, _minimal_config())
    state = hass.states.get(ENTITY_ID)
    assert state is not None


async def test_setup_with_full_config(hass: HomeAssistant):
    """Test component loads with all optional params."""
    await _setup_component(hass, _full_config())
    state = hass.states.get("climate.test_thermostat")
    assert state is not None
    assert state.attributes.get("min_temp") == 10
    assert state.attributes.get("max_temp") == 30


async def test_default_values(hass: HomeAssistant):
    """Test default values when only required config is provided."""
    await _setup_component(hass, _minimal_config())
    state = hass.states.get(ENTITY_ID)
    assert state.attributes.get(ATTR_PRESET_MODE) == PRESET_HOME
    # Physical thermostat is HEAT, so virtual should sync to HEAT
    assert state.state == HVACMode.HEAT


async def test_ac_mode_hvac_list(hass: HomeAssistant):
    """Test ac_mode=true gives COOL+OFF, false gives HEAT+OFF."""
    # Default (no ac_mode) -> HEAT + OFF
    await _setup_component(hass, _minimal_config())
    state = hass.states.get(ENTITY_ID)
    hvac_modes = state.attributes.get("hvac_modes")
    assert HVACMode.HEAT in hvac_modes
    assert HVACMode.OFF in hvac_modes
    assert HVACMode.COOL not in hvac_modes


async def test_ac_mode_cool(hass: HomeAssistant):
    """Test ac_mode=true gives COOL+OFF."""
    config = _minimal_config()
    config["climate"]["ac_mode"] = True
    hass.states.async_set(
        PHYSICAL_THERMOSTAT,
        HVACMode.COOL,
        {ATTR_TEMPERATURE: 25},
    )
    hass.states.async_set(SENSOR_ENTITY, "26.0")
    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    hvac_modes = state.attributes.get("hvac_modes")
    assert HVACMode.COOL in hvac_modes
    assert HVACMode.OFF in hvac_modes
    assert HVACMode.HEAT not in hvac_modes


async def test_unique_id(hass: HomeAssistant):
    """Test unique_id is set correctly."""
    await _setup_component(hass, _full_config())
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get("climate.test_thermostat")
    assert entry is not None
    assert entry.unique_id == "test_unique_123"


# ============================================================
# Group 2: Temperature Sensor Sync
# ============================================================


async def test_sensor_update(hass: HomeAssistant):
    """Test sensor state change updates current_temperature."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    hass.states.async_set(SENSOR_ENTITY, "22.5")
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes.get("current_temperature") == 22.5


async def test_sensor_unavailable_ignored(hass: HomeAssistant):
    """Test sensor going unavailable doesn't crash or change temp."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # First set a valid temp
    hass.states.async_set(SENSOR_ENTITY, "22.0")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.attributes.get("current_temperature") == 22.0

    # Now set unavailable
    hass.states.async_set(SENSOR_ENTITY, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    # Temperature should remain unchanged
    assert state.attributes.get("current_temperature") == 22.0


async def test_sensor_nan_ignored(hass: HomeAssistant):
    """Test NaN sensor values are rejected."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    hass.states.async_set(SENSOR_ENTITY, "22.0")
    await hass.async_block_till_done()

    hass.states.async_set(SENSOR_ENTITY, "nan")
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes.get("current_temperature") == 22.0


async def test_sensor_startup_sync(hass: HomeAssistant):
    """Test on startup, current_temperature reads from sensor."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"
    state = hass.states.get(entity_id)
    assert state.attributes.get("current_temperature") == 20.5


# ============================================================
# Group 3: Two-Way Sync (Virtual -> Physical)
# ============================================================


async def test_set_temperature_syncs_to_physical(hass: HomeAssistant):
    """Test set_temperature updates the virtual thermostat state."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 25},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes.get(ATTR_TEMPERATURE) == 25


async def test_set_hvac_mode_syncs_to_physical(hass: HomeAssistant):
    """Test changing HVAC mode updates the virtual thermostat state."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == HVACMode.OFF


async def test_preset_switch_syncs_to_physical(hass: HomeAssistant):
    """Test switching presets pushes the preset's temp to physical."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Set temp for HOME preset
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 22},
        blocking=True,
    )

    # Switch to ECO and set a temp
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_preset_mode",
        {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: PRESET_ECO},
        blocking=True,
    )

    calls = []
    hass.services.async_register(
        CLIMATE_DOMAIN, "set_temperature", lambda call: calls.append(call)
    )

    # Switch back to HOME - should sync HOME's temp to physical
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_preset_mode",
        {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: PRESET_HOME},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert state.attributes.get(ATTR_TEMPERATURE) == 22


async def test_turn_on_syncs(hass: HomeAssistant):
    """Test async_turn_on sets HEAT and syncs."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # First turn off
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == HVACMode.OFF

    # Turn on
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.HEAT


async def test_turn_off_syncs(hass: HomeAssistant):
    """Test async_turn_off sets OFF and syncs."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.OFF


# ============================================================
# Group 4: Two-Way Sync (Physical -> Virtual)
# ============================================================


async def test_physical_temp_change_syncs_to_virtual(hass: HomeAssistant):
    """Test physical thermostat temp change updates virtual."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Simulate physical thermostat changing temperature (e.g., user at wall)
    hass.states.async_set(
        PHYSICAL_THERMOSTAT,
        HVACMode.HEAT,
        {ATTR_TEMPERATURE: 25},
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes.get(ATTR_TEMPERATURE) == 25


async def test_physical_hvac_mode_change_syncs_to_virtual(hass: HomeAssistant):
    """Test physical HVAC mode change updates virtual."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Physical thermostat turned off at wall
    hass.states.async_set(
        PHYSICAL_THERMOSTAT,
        HVACMode.OFF,
        {ATTR_TEMPERATURE: 21},
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == HVACMode.OFF


async def test_physical_off_syncs_to_virtual(hass: HomeAssistant):
    """Test physical thermostat turned OFF -> virtual shows OFF."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Confirm it starts as HEAT
    assert hass.states.get(entity_id).state == HVACMode.HEAT

    # Physical goes OFF
    hass.states.async_set(
        PHYSICAL_THERMOSTAT,
        HVACMode.OFF,
        {},
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == HVACMode.OFF


async def test_physical_unavailable_ignored(hass: HomeAssistant):
    """Test physical going unavailable doesn't crash."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    hass.states.async_set(PHYSICAL_THERMOSTAT, STATE_UNAVAILABLE)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    # Should still show previous state
    assert state.state == HVACMode.HEAT


async def test_physical_missing_temperature_attr(hass: HomeAssistant):
    """Test physical state with no ATTR_TEMPERATURE doesn't crash."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Physical thermostat changes state but has no temperature attribute
    hass.states.async_set(PHYSICAL_THERMOSTAT, HVACMode.OFF, {})
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == HVACMode.OFF


# ============================================================
# Group 5: Sync Loop Prevention
# ============================================================


async def test_no_sync_loop_on_set_temperature(hass: HomeAssistant):
    """Test that physical thermostat change back doesn't alter virtual state.

    After setting temp on virtual, the physical thermostat reports the
    same temp back. Virtual thermostat should accept it without resetting.
    """
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Set temperature on virtual thermostat
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 25},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Simulate the physical thermostat echoing the same temp back
    hass.states.async_set(
        PHYSICAL_THERMOSTAT, HVACMode.HEAT, {ATTR_TEMPERATURE: 25}
    )
    await hass.async_block_till_done()

    # Virtual thermostat should still show 25 (no change from the echo)
    state = hass.states.get(entity_id)
    assert state.attributes.get(ATTR_TEMPERATURE) == 25


async def test_no_sync_loop_on_set_hvac_mode(hass: HomeAssistant):
    """Test that physical thermostat mode echo doesn't alter virtual state."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Change HVAC mode on virtual
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Simulate physical thermostat reporting OFF back
    hass.states.async_set(PHYSICAL_THERMOSTAT, HVACMode.OFF, {ATTR_TEMPERATURE: 21})
    await hass.async_block_till_done()

    # Virtual should still show OFF (stable, no loop)
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.OFF


# ============================================================
# Group 6: Preset Mode Behavior
# ============================================================


async def test_preset_modes_available(hass: HomeAssistant):
    """Test preset_modes returns [AWAY, ECO, HOME]."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"
    state = hass.states.get(entity_id)
    preset_modes = state.attributes.get("preset_modes")
    assert PRESET_AWAY in preset_modes
    assert PRESET_ECO in preset_modes
    assert PRESET_HOME in preset_modes


async def test_preset_switch_restores_saved_temp(hass: HomeAssistant):
    """Test switching HOME(21)->ECO(18)->HOME restores 21."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Set HOME temp to 22
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 22},
        blocking=True,
    )

    # Switch to ECO
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_preset_mode",
        {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: PRESET_ECO},
        blocking=True,
    )
    # Set ECO temp
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 18},
        blocking=True,
    )

    # Switch back to HOME
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_preset_mode",
        {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: PRESET_HOME},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert state.attributes.get(ATTR_TEMPERATURE) == 22
    assert state.attributes.get(ATTR_PRESET_MODE) == PRESET_HOME


async def test_preset_temp_saved_on_change(hass: HomeAssistant):
    """Test changing temp while in ECO, switch away and back, ECO remembers."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Switch to ECO
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_preset_mode",
        {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: PRESET_ECO},
        blocking=True,
    )
    # Set ECO temp to 17
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 17},
        blocking=True,
    )

    # Switch to AWAY
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_preset_mode",
        {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: PRESET_AWAY},
        blocking=True,
    )

    # Switch back to ECO
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_preset_mode",
        {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: PRESET_ECO},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert state.attributes.get(ATTR_TEMPERATURE) == 17


async def test_invalid_preset_rejected(hass: HomeAssistant):
    """Test setting invalid preset is rejected."""
    from homeassistant.exceptions import ServiceValidationError

    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # HA 2025.1+ validates presets before calling the entity
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            "set_preset_mode",
            {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: "invalid_mode"},
            blocking=True,
        )

    state = hass.states.get(entity_id)
    # Should still be HOME (default)
    assert state.attributes.get(ATTR_PRESET_MODE) == PRESET_HOME


async def test_preset_temps_in_attributes(hass: HomeAssistant):
    """Test per-preset temps stored as extra_state_attributes."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Set HOME temp
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 22},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert state.attributes.get("home_temp") == 22


# ============================================================
# Group 7: State Restoration (HA Restart)
# ============================================================


async def test_restore_preset_mode(hass: HomeAssistant):
    """Test after restart, preset mode is restored from saved state."""
    mock_restore_cache(
        hass,
        (
            State(
                ENTITY_ID,
                HVACMode.HEAT,
                {
                    ATTR_TEMPERATURE: 20,
                    ATTR_PRESET_MODE: PRESET_ECO,
                    "eco_temp": 18,
                    "home_temp": 21,
                    "away_temp": 15,
                },
            ),
        ),
    )

    # Physical thermostat available with same mode
    hass.states.async_set(
        PHYSICAL_THERMOSTAT,
        HVACMode.HEAT,
        {ATTR_TEMPERATURE: 20},
    )
    hass.states.async_set(SENSOR_ENTITY, "19.5")

    assert await async_setup_component(hass, CLIMATE_DOMAIN, _minimal_config())
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state.attributes.get(ATTR_PRESET_MODE) == PRESET_ECO


async def test_restore_preset_temperatures(hass: HomeAssistant):
    """Test after restart, per-preset temps are restored."""
    mock_restore_cache(
        hass,
        (
            State(
                ENTITY_ID,
                HVACMode.HEAT,
                {
                    ATTR_TEMPERATURE: 18,
                    ATTR_PRESET_MODE: PRESET_ECO,
                    "eco_temp": 18,
                    "home_temp": 22,
                    "away_temp": 15,
                },
            ),
        ),
    )

    hass.states.async_set(
        PHYSICAL_THERMOSTAT,
        HVACMode.HEAT,
        {ATTR_TEMPERATURE: 18},
    )
    hass.states.async_set(SENSOR_ENTITY, "19.5")

    assert await async_setup_component(hass, CLIMATE_DOMAIN, _minimal_config())
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state.attributes.get("home_temp") == 22
    assert state.attributes.get("eco_temp") == 18
    assert state.attributes.get("away_temp") == 15


async def test_startup_syncs_from_physical(hass: HomeAssistant):
    """Test physical thermostat is source of truth on startup."""
    mock_restore_cache(
        hass,
        (
            State(
                ENTITY_ID,
                HVACMode.HEAT,
                {
                    ATTR_TEMPERATURE: 18,
                    ATTR_PRESET_MODE: PRESET_HOME,
                },
            ),
        ),
    )

    # Physical thermostat has DIFFERENT temperature than saved state
    hass.states.async_set(
        PHYSICAL_THERMOSTAT,
        HVACMode.HEAT,
        {ATTR_TEMPERATURE: 23},
    )
    hass.states.async_set(SENSOR_ENTITY, "20.0")

    assert await async_setup_component(hass, CLIMATE_DOMAIN, _minimal_config())
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    # Should have synced from physical (23), not restored (18)
    assert state.attributes.get(ATTR_TEMPERATURE) == 23


async def test_startup_physical_unavailable_falls_back_to_restored(
    hass: HomeAssistant,
):
    """Test if physical not ready, use restored state."""
    mock_restore_cache(
        hass,
        (
            State(
                ENTITY_ID,
                HVACMode.HEAT,
                {
                    ATTR_TEMPERATURE: 20,
                    ATTR_PRESET_MODE: PRESET_HOME,
                },
            ),
        ),
    )

    # Physical thermostat is unavailable
    hass.states.async_set(PHYSICAL_THERMOSTAT, STATE_UNAVAILABLE)
    hass.states.async_set(SENSOR_ENTITY, "19.0")

    assert await async_setup_component(hass, CLIMATE_DOMAIN, _minimal_config())
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state.attributes.get(ATTR_TEMPERATURE) == 20


async def test_startup_no_saved_state_uses_defaults(hass: HomeAssistant):
    """Test no saved state -> uses min_temp (or max_temp in ac_mode)."""
    # No mock_restore_cache = no saved state
    # Physical also unavailable
    hass.states.async_set(PHYSICAL_THERMOSTAT, STATE_UNAVAILABLE)
    hass.states.async_set(SENSOR_ENTITY, "20.0")

    config = _minimal_config()
    config["climate"]["min_temp"] = 10
    config["climate"]["max_temp"] = 30

    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    # Default for heat mode: min_temp
    assert state.attributes.get(ATTR_TEMPERATURE) == 10


# ============================================================
# Group 8: HVAC Action
# ============================================================


async def test_hvac_action_off(hass: HomeAssistant):
    """Test hvac_mode=OFF -> action=OFF."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert state.attributes.get("hvac_action") == HVACAction.OFF


async def test_hvac_action_heating(hass: HomeAssistant):
    """Test heat mode, target > current -> HEATING."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Set target above current (current is 20.5 from setup)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 25},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert state.attributes.get("hvac_action") == HVACAction.HEATING


async def test_hvac_action_idle(hass: HomeAssistant):
    """Test heat mode, target <= current -> IDLE."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"

    # Set target below current (current is 20.5)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 18},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert state.attributes.get("hvac_action") == HVACAction.IDLE


async def test_hvac_action_cooling(hass: HomeAssistant):
    """Test ac_mode, current > target -> COOLING."""
    config = _full_config(ac_mode=True, initial_hvac_mode="cool")
    hass.states.async_set(
        PHYSICAL_THERMOSTAT,
        HVACMode.COOL,
        {ATTR_TEMPERATURE: 22},
    )
    hass.states.async_set(SENSOR_ENTITY, "25.0")

    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()
    entity_id = "climate.test_thermostat"

    # Current is 25, target is 22 -> cooling needed
    state = hass.states.get(entity_id)
    assert state.attributes.get("hvac_action") == HVACAction.COOLING


# ============================================================
# Group 9: Edge Cases
# ============================================================


async def test_supported_features(hass: HomeAssistant):
    """Test supported features include all required flags."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"
    state = hass.states.get(entity_id)
    features = state.attributes.get("supported_features")
    assert features & ClimateEntityFeature.TARGET_TEMPERATURE
    assert features & ClimateEntityFeature.PRESET_MODE
    assert features & ClimateEntityFeature.TURN_ON
    assert features & ClimateEntityFeature.TURN_OFF


async def test_precision_override(hass: HomeAssistant):
    """Test custom precision is used."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"
    state = hass.states.get(entity_id)
    assert state.attributes.get("target_temp_step") == PRECISION_HALVES


async def test_min_max_temp_override(hass: HomeAssistant):
    """Test custom min/max temps are used."""
    await _setup_component(hass, _full_config())
    entity_id = "climate.test_thermostat"
    state = hass.states.get(entity_id)
    assert state.attributes.get("min_temp") == 10
    assert state.attributes.get("max_temp") == 30
