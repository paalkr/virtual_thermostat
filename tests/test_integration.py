"""Integration tests for virtual_thermostat against a live Home Assistant instance.

These tests require a running HA instance (via devcontainer) at http://localhost:9123
with the virtual_thermostat component configured alongside a generic_thermostat.

Expected configuration (see .devcontainer/configuration.yaml):
  - climate.fake_thermostat (generic_thermostat, physical)
  - climate.1_etg_kontor_virtual_thermostat (virtual_thermostat, wrapping fake_thermostat)
  - input_number.fake_target_sensor (temperature sensor)
  - input_boolean.fake_heater_switch (heater entity)

Setup:
    docker run -d --name ha-virtual-thermostat -p 9123:8123 \
      -v $PWD/.devcontainer/configuration.yaml:/config/configuration.yaml:ro \
      -v $PWD/custom_components/virtual_thermostat:/config/custom_components/virtual_thermostat:ro \
      ghcr.io/home-assistant/home-assistant:2025.1
    # Complete onboarding at http://localhost:9123, then update REFRESH_TOKEN below.

Run:
    .venv/bin/pytest tests/test_integration.py -v --tb=short

Requires: requests (already in requirements_test.txt)
"""

import time

import pytest
import pytest_socket
import requests

# Allow real network access — pytest-socket (from pytest-homeassistant-custom-component)
# blocks sockets by default, but integration tests need real HTTP to the HA container.
pytestmark = pytest.mark.enable_socket


@pytest.fixture(autouse=True, scope="module")
def _enable_real_sockets():
    """Re-enable sockets for the entire module, including module-scoped fixtures."""
    pytest_socket.enable_socket()
    yield
    pytest_socket.enable_socket()

HA_URL = "http://localhost:9123"
REFRESH_TOKEN = (
    "4eb57e0553b2549e8bb4d8e60059f9e4fca955f6758ba254d09d30cd686a7bed"
    "8c78f467729c0e66326167840c1eafb613a55645c7c866451a61190137e92c01"
)
CLIENT_ID = "http://localhost:9123/"

VIRTUAL = "climate.1_etg_kontor_virtual_thermostat"
PHYSICAL = "climate.fake_thermostat"
SENSOR = "input_number.fake_target_sensor"
HEATER = "input_boolean.fake_heater_switch"


class HAClient:
    """Simple Home Assistant REST API client."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def get_state(self, entity_id: str) -> dict:
        r = self.session.get(f"{self.base_url}/api/states/{entity_id}")
        r.raise_for_status()
        return r.json()

    def call_service(self, domain: str, service: str, data: dict) -> None:
        r = self.session.post(
            f"{self.base_url}/api/services/{domain}/{service}",
            json=data,
        )
        r.raise_for_status()

    def set_climate_temp(self, entity_id: str, temperature: float) -> None:
        self.call_service(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": temperature},
        )

    def set_climate_mode(self, entity_id: str, hvac_mode: str) -> None:
        self.call_service(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": hvac_mode},
        )

    def set_climate_preset(self, entity_id: str, preset_mode: str) -> None:
        self.call_service(
            "climate",
            "set_preset_mode",
            {"entity_id": entity_id, "preset_mode": preset_mode},
        )

    def set_sensor_value(self, entity_id: str, value: float) -> None:
        self.call_service(
            "input_number",
            "set_value",
            {"entity_id": entity_id, "value": value},
        )


def _get_token() -> str:
    """Get a fresh access token via refresh token."""
    r = requests.post(
        f"{HA_URL}/auth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "client_id": CLIENT_ID,
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def ha() -> HAClient:
    """Create an authenticated HA API client."""
    token = _get_token()
    client = HAClient(HA_URL, token)
    # Verify connectivity
    r = requests.get(f"{HA_URL}/api/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, f"HA not reachable: {r.status_code}"
    return client


@pytest.fixture(autouse=True)
def reset_state(ha: HAClient):
    """Reset entities to a known state before each test."""
    ha.set_sensor_value(SENSOR, 20.0)
    ha.set_climate_temp(VIRTUAL, 22.0)
    ha.set_climate_mode(VIRTUAL, "heat")
    ha.set_climate_preset(VIRTUAL, "home")
    time.sleep(0.5)
    yield
    # No teardown needed — next test resets


def _wait_for(ha: HAClient, entity_id: str, attr: str, expected, timeout: float = 3.0):
    """Poll until entity attribute matches expected value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = ha.get_state(entity_id)
        if attr == "state":
            actual = state["state"]
        else:
            actual = state["attributes"].get(attr)
        if actual == expected:
            return state
        time.sleep(0.2)
    state = ha.get_state(entity_id)
    actual = state["state"] if attr == "state" else state["attributes"].get(attr)
    pytest.fail(
        f"Timeout waiting for {entity_id}.{attr} == {expected!r}, got {actual!r}"
    )


# ── Group 1: API - Entity Discovery ──────────────────────────────────────


class TestEntityDiscovery:
    """Verify entities exist and have correct attributes."""

    def test_virtual_thermostat_exists(self, ha: HAClient):
        state = ha.get_state(VIRTUAL)
        assert state["state"] in ("heat", "off", "cool")

    def test_physical_thermostat_exists(self, ha: HAClient):
        state = ha.get_state(PHYSICAL)
        assert state["state"] in ("heat", "off", "cool")

    def test_virtual_has_preset_modes(self, ha: HAClient):
        state = ha.get_state(VIRTUAL)
        presets = state["attributes"]["preset_modes"]
        assert "home" in presets
        assert "away" in presets
        assert "eco" in presets

    def test_virtual_has_correct_hvac_modes(self, ha: HAClient):
        state = ha.get_state(VIRTUAL)
        modes = state["attributes"]["hvac_modes"]
        assert "heat" in modes
        assert "off" in modes

    def test_sensor_exists(self, ha: HAClient):
        state = ha.get_state(SENSOR)
        assert float(state["state"]) >= 0


# ── Group 2: API - Two-Way Temperature Sync ──────────────────────────────


class TestTemperatureSync:
    """Verify temperature setpoint syncs between virtual and physical."""

    def test_virtual_to_physical_temp_sync(self, ha: HAClient):
        """Setting temp on virtual should propagate to physical."""
        ha.set_climate_temp(VIRTUAL, 25.0)
        _wait_for(ha, PHYSICAL, "temperature", 25.0)

    def test_physical_to_virtual_temp_sync(self, ha: HAClient):
        """Setting temp on physical should propagate to virtual."""
        ha.set_climate_temp(PHYSICAL, 18.0)
        _wait_for(ha, VIRTUAL, "temperature", 18.0)

    def test_sensor_update_reflects_on_virtual(self, ha: HAClient):
        """Changing the sensor value updates current_temperature on virtual."""
        ha.set_sensor_value(SENSOR, 23.5)
        _wait_for(ha, VIRTUAL, "current_temperature", 23.5)


# ── Group 3: API - Two-Way HVAC Mode Sync ────────────────────────────────


class TestHVACModeSync:
    """Verify HVAC mode syncs between virtual and physical."""

    def test_virtual_off_syncs_to_physical(self, ha: HAClient):
        ha.set_climate_mode(VIRTUAL, "off")
        _wait_for(ha, PHYSICAL, "state", "off")

    def test_virtual_heat_syncs_to_physical(self, ha: HAClient):
        ha.set_climate_mode(VIRTUAL, "off")
        time.sleep(0.3)
        ha.set_climate_mode(VIRTUAL, "heat")
        _wait_for(ha, PHYSICAL, "state", "heat")

    def test_physical_off_syncs_to_virtual(self, ha: HAClient):
        ha.set_climate_mode(PHYSICAL, "off")
        _wait_for(ha, VIRTUAL, "state", "off")

    def test_physical_heat_syncs_to_virtual(self, ha: HAClient):
        ha.set_climate_mode(PHYSICAL, "off")
        time.sleep(0.3)
        ha.set_climate_mode(PHYSICAL, "heat")
        _wait_for(ha, VIRTUAL, "state", "heat")


# ── Group 4: API - Preset Mode Behavior ──────────────────────────────────


class TestPresetModes:
    """Verify preset mode switching and temperature memory."""

    def test_switch_to_away_preset(self, ha: HAClient):
        ha.set_climate_preset(VIRTUAL, "away")
        state = ha.get_state(VIRTUAL)
        assert state["attributes"]["preset_mode"] == "away"

    def test_preset_remembers_temperature(self, ha: HAClient):
        """Each preset should remember its own temperature."""
        # Set home to 22
        ha.set_climate_preset(VIRTUAL, "home")
        time.sleep(0.3)
        ha.set_climate_temp(VIRTUAL, 22.0)
        time.sleep(0.3)

        # Set eco to 18
        ha.set_climate_preset(VIRTUAL, "eco")
        time.sleep(0.3)
        ha.set_climate_temp(VIRTUAL, 18.0)
        time.sleep(0.3)

        # Switch back to home — should restore 22
        ha.set_climate_preset(VIRTUAL, "home")
        _wait_for(ha, VIRTUAL, "temperature", 22.0)

    def test_preset_temp_syncs_to_physical(self, ha: HAClient):
        """Switching preset should sync the preset's temp to physical."""
        ha.set_climate_preset(VIRTUAL, "home")
        time.sleep(0.3)
        ha.set_climate_temp(VIRTUAL, 25.0)
        time.sleep(0.3)

        ha.set_climate_preset(VIRTUAL, "eco")
        time.sleep(0.3)
        ha.set_climate_temp(VIRTUAL, 17.0)
        time.sleep(0.3)

        # Switch to home — physical should get 25
        ha.set_climate_preset(VIRTUAL, "home")
        _wait_for(ha, PHYSICAL, "temperature", 25.0)


# ── Group 5: API - HVAC Action ───────────────────────────────────────────


class TestHVACAction:
    """Verify hvac_action reflects heating/idle/off correctly."""

    def test_action_heating(self, ha: HAClient):
        """When target > current, action should be heating."""
        ha.set_sensor_value(SENSOR, 18.0)
        ha.set_climate_temp(VIRTUAL, 25.0)
        _wait_for(ha, VIRTUAL, "hvac_action", "heating")

    def test_action_idle(self, ha: HAClient):
        """When current >= target, action should be idle."""
        ha.set_sensor_value(SENSOR, 25.0)
        ha.set_climate_temp(VIRTUAL, 20.0)
        _wait_for(ha, VIRTUAL, "hvac_action", "idle")

    def test_action_off(self, ha: HAClient):
        """When mode is off, action should be off."""
        ha.set_climate_mode(VIRTUAL, "off")
        _wait_for(ha, VIRTUAL, "hvac_action", "off")


# ── Group 6: API - Edge Cases ────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_rapid_temp_changes(self, ha: HAClient):
        """Rapid successive changes should converge to final value."""
        for temp in [15.0, 18.0, 21.0, 24.0, 27.0]:
            ha.set_climate_temp(VIRTUAL, temp)
            time.sleep(0.1)
        _wait_for(ha, PHYSICAL, "temperature", 27.0)

    def test_min_temp_boundary(self, ha: HAClient):
        """Setting minimum temperature should work."""
        state = ha.get_state(VIRTUAL)
        min_temp = state["attributes"]["min_temp"]
        ha.set_climate_temp(VIRTUAL, min_temp)
        _wait_for(ha, PHYSICAL, "temperature", min_temp)

    def test_max_temp_boundary(self, ha: HAClient):
        """Setting maximum temperature should work."""
        state = ha.get_state(VIRTUAL)
        max_temp = state["attributes"]["max_temp"]
        ha.set_climate_temp(VIRTUAL, max_temp)
        _wait_for(ha, PHYSICAL, "temperature", max_temp)
