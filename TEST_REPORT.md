# Test Report: Virtual Thermostat v2.0.0

**Date:** 2026-03-21
**Test framework:** pytest 8.3.4 + pytest-homeassistant-custom-component 0.13.205
**Home Assistant version:** 2025.1.4
**Python:** 3.12.3
**Total tests:** 39 | **Passed:** 39 | **Failed:** 0

## Test Results

### Group 1: Initialization & Configuration (6/6 passed)

| # | Test | Result |
|---|------|--------|
| 1 | test_setup_with_minimal_config | PASS |
| 2 | test_setup_with_full_config | PASS |
| 3 | test_default_values | PASS |
| 4 | test_ac_mode_hvac_list | PASS |
| 5 | test_ac_mode_cool | PASS |
| 6 | test_unique_id | PASS |

### Group 2: Temperature Sensor Sync (4/4 passed)

| # | Test | Result |
|---|------|--------|
| 7 | test_sensor_update | PASS |
| 8 | test_sensor_unavailable_ignored | PASS |
| 9 | test_sensor_nan_ignored | PASS |
| 10 | test_sensor_startup_sync | PASS |

### Group 3: Two-Way Sync - Virtual to Physical (5/5 passed)

| # | Test | Result |
|---|------|--------|
| 11 | test_set_temperature_syncs_to_physical | PASS |
| 12 | test_set_hvac_mode_syncs_to_physical | PASS |
| 13 | test_preset_switch_syncs_to_physical | PASS |
| 14 | test_turn_on_syncs | PASS |
| 15 | test_turn_off_syncs | PASS |

### Group 4: Two-Way Sync - Physical to Virtual (5/5 passed)

| # | Test | Result |
|---|------|--------|
| 16 | test_physical_temp_change_syncs_to_virtual | PASS |
| 17 | test_physical_hvac_mode_change_syncs_to_virtual | PASS |
| 18 | test_physical_off_syncs_to_virtual | PASS |
| 19 | test_physical_unavailable_ignored | PASS |
| 20 | test_physical_missing_temperature_attr | PASS |

### Group 5: Sync Loop Prevention (2/2 passed)

| # | Test | Result |
|---|------|--------|
| 21 | test_no_sync_loop_on_set_temperature | PASS |
| 22 | test_no_sync_loop_on_set_hvac_mode | PASS |

### Group 6: Preset Mode Behavior (5/5 passed)

| # | Test | Result |
|---|------|--------|
| 23 | test_preset_modes_available | PASS |
| 24 | test_preset_switch_restores_saved_temp | PASS |
| 25 | test_preset_temp_saved_on_change | PASS |
| 26 | test_invalid_preset_rejected | PASS |
| 27 | test_preset_temps_in_attributes | PASS |

### Group 7: State Restoration - HA Restart (5/5 passed)

| # | Test | Result |
|---|------|--------|
| 28 | test_restore_preset_mode | PASS |
| 29 | test_restore_preset_temperatures | PASS |
| 30 | test_startup_syncs_from_physical | PASS |
| 31 | test_startup_physical_unavailable_falls_back_to_restored | PASS |
| 32 | test_startup_no_saved_state_uses_defaults | PASS |

### Group 8: HVAC Action (4/4 passed)

| # | Test | Result |
|---|------|--------|
| 33 | test_hvac_action_off | PASS |
| 34 | test_hvac_action_heating | PASS |
| 35 | test_hvac_action_idle | PASS |
| 36 | test_hvac_action_cooling | PASS |

### Group 9: Edge Cases (3/3 passed)

| # | Test | Result |
|---|------|--------|
| 37 | test_supported_features | PASS |
| 38 | test_precision_override | PASS |
| 39 | test_min_max_temp_override | PASS |

## Issues Found During Testing

### 1. Missing `_attr_temperature_unit` class attribute (BUG - FIXED)

**Severity:** Critical (component fails to load)
**Description:** HA 2025.1's `ClimateEntity` uses a `cached_property` for `temperature_unit` that reads `self._attr_temperature_unit`. When we removed the `temperature_unit` property override (Phase 3b of the upgrade plan), we didn't provide this attribute. HA's entity platform calls `capability_attributes` during entity registration, which accesses `temperature_unit` before `async_added_to_hass()` runs.
**Fix:** Added `_attr_temperature_unit = UnitOfTemperature.CELSIUS` as a class-level default on `VirtualThermostat`, and set the actual value from `hass.config.units.temperature_unit` in `async_added_to_hass()`.

### 2. HA 2025.1 validates preset modes before entity code (TEST FIX)

**Severity:** Test-only
**Description:** HA 2025.1 validates preset mode values before calling `async_set_preset_mode()`. Invalid presets raise `ServiceValidationError` instead of silently being rejected by our code.
**Fix:** Updated `test_invalid_preset_rejected` to expect `ServiceValidationError` via `pytest.raises()`.

## Test Infrastructure Notes

- Tests use `pytest-homeassistant-custom-component` which provides full HA test fixtures
- Custom component discovery requires a symlink from the test framework's `testing_config/custom_components/` to our component directory
- The `enable_custom_integrations` fixture (auto-enabled via conftest.py) allows HA to discover custom components in tests
- `mock_restore_cache` must be called BEFORE `async_setup_component` for state restoration tests
- `asyncio_mode = "auto"` in `pyproject.toml` is required for async fixtures to resolve properly

## Running Tests

```bash
cd virtual_thermostat
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt

# Symlink component into test config (one-time setup)
ln -sfn "$(pwd)/custom_components/virtual_thermostat" \
  .venv/lib/python3.12/site-packages/pytest_homeassistant_custom_component/testing_config/custom_components/virtual_thermostat

# Run tests
.venv/bin/pytest tests/ -v
```
