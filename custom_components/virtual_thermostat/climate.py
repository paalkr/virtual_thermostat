"""Virtual thermostat that wraps a physical thermostat with preset support."""
import logging
import math

import voluptuous as vol

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.components.climate.const import (
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
    CONF_NAME,
    CONF_UNIQUE_ID,
    EVENT_HOMEASSISTANT_START,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import CoreState, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Virtual Thermostat"

CONF_SENSOR = "target_sensor"
CONF_THERMOSTAT = "thermostat"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP = "target_temp"
CONF_AC_MODE = "ac_mode"
CONF_INITIAL_HVAC_MODE = "initial_hvac_mode"
CONF_PRECISION = "precision"

SUPPORT_FLAGS = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.PRESET_MODE
    | ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SENSOR): cv.entity_id,
        vol.Required(CONF_THERMOSTAT): cv.entity_id,
        vol.Optional(CONF_AC_MODE): cv.boolean,
        vol.Optional(CONF_MAX_TEMP): vol.Coerce(float),
        vol.Optional(CONF_MIN_TEMP): vol.Coerce(float),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_TARGET_TEMP): vol.Coerce(float),
        vol.Optional(CONF_INITIAL_HVAC_MODE): vol.In(
            [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF]
        ),
        vol.Optional(CONF_PRECISION): vol.In(
            [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        ),
        vol.Optional(CONF_UNIQUE_ID): cv.string,
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the virtual thermostat platform."""
    async_add_entities(
        [
            VirtualThermostat(
                name=config.get(CONF_NAME),
                sensor_entity_id=config.get(CONF_SENSOR),
                thermostat_entity_id=config.get(CONF_THERMOSTAT),
                min_temp=config.get(CONF_MIN_TEMP),
                max_temp=config.get(CONF_MAX_TEMP),
                target_temp=config.get(CONF_TARGET_TEMP),
                ac_mode=config.get(CONF_AC_MODE),
                initial_hvac_mode=config.get(CONF_INITIAL_HVAC_MODE),
                precision=config.get(CONF_PRECISION),
                unique_id=config.get(CONF_UNIQUE_ID),
            )
        ]
    )


class VirtualThermostat(ClimateEntity, RestoreEntity):
    """Virtual thermostat that wraps a physical thermostat with preset support."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        name,
        sensor_entity_id,
        thermostat_entity_id,
        min_temp,
        max_temp,
        target_temp,
        ac_mode,
        initial_hvac_mode,
        precision,
        unique_id,
    ):
        """Initialize the thermostat."""
        self._name = name
        self.sensor_entity_id = sensor_entity_id
        self.thermostat_entity_id = thermostat_entity_id
        self.ac_mode = ac_mode
        self._hvac_mode = initial_hvac_mode
        self._temp_precision = precision
        if self.ac_mode:
            self._hvac_list = [HVACMode.COOL, HVACMode.OFF]
        else:
            self._hvac_list = [HVACMode.HEAT, HVACMode.OFF]
        self._cur_temp = None
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temp = target_temp
        self._unique_id = unique_id
        self._support_flags = SUPPORT_FLAGS
        self._preset_mode = PRESET_HOME
        self._attributes = {}
        self._syncing_to_physical = False

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Set temperature unit from HA config (overrides class default)
        self._attr_temperature_unit = self.hass.config.units.temperature_unit

        # Add listener for temperature sensor changes
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.sensor_entity_id], self._async_sensor_changed
            )
        )

        # Add listener for physical thermostat changes
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self.thermostat_entity_id],
                self._async_thermostat_changed,
            )
        )

        @callback
        def _async_startup(*_):
            """Init on startup."""
            sensor_state = self.hass.states.get(self.sensor_entity_id)
            if sensor_state and sensor_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                self._async_update_temp(sensor_state)
                self.async_write_ha_state()

        if self.hass.state == CoreState.running:
            _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

        # Restore saved state (preset temps, preset mode)
        old_state = await self.async_get_last_state()
        if old_state is not None:
            # Restore preset mode
            if old_state.attributes.get(ATTR_PRESET_MODE) is not None:
                self._preset_mode = old_state.attributes.get(ATTR_PRESET_MODE)

            # Restore per-preset temperature memory
            for preset in self.preset_modes:
                saved_temp = old_state.attributes.get(preset + "_temp")
                if saved_temp is not None:
                    self._attributes[preset + "_temp"] = saved_temp

        # Sync FROM physical thermostat (it's the source of truth after restart)
        thermostat_state = self.hass.states.get(self.thermostat_entity_id)
        if thermostat_state and thermostat_state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            # Sync HVAC mode from physical thermostat
            try:
                phys_hvac = HVACMode(thermostat_state.state)
                if phys_hvac in self._hvac_list:
                    self._hvac_mode = phys_hvac
            except ValueError:
                pass

            # Sync target temperature from physical thermostat
            phys_temp = thermostat_state.attributes.get(ATTR_TEMPERATURE)
            if phys_temp is not None:
                self._target_temp = float(phys_temp)
                if self._preset_mode in self.preset_modes:
                    self._attributes[self._preset_mode + "_temp"] = self._target_temp
        else:
            # Physical thermostat not available yet, fall back to restored/default state
            if self._target_temp is None:
                if old_state is not None:
                    saved_temp = old_state.attributes.get(ATTR_TEMPERATURE)
                    if saved_temp is not None:
                        self._target_temp = float(saved_temp)

            if self._target_temp is None:
                if self.ac_mode:
                    self._target_temp = self.max_temp
                else:
                    self._target_temp = self.min_temp
                _LOGGER.warning(
                    "No temperature available, falling back to %s",
                    self._target_temp,
                )

        # Set default state to off if no mode was determined
        if not self._hvac_mode:
            self._hvac_mode = HVACMode.OFF

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attributes

    @property
    def unique_id(self):
        """Return the unique id of this thermostat."""
        return self._unique_id

    @property
    def precision(self):
        """Return the precision of the system."""
        if self._temp_precision is not None:
            return self._temp_precision
        return super().precision

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return self.precision

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported."""
        if self._hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if not self._is_device_active:
            return HVACAction.IDLE
        if self.ac_mode:
            return HVACAction.COOLING
        return HVACAction.HEATING

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def hvac_modes(self):
        """List of available operation modes."""
        return self._hvac_list

    @property
    def preset_mode(self):
        """Return the current preset mode."""
        return self._preset_mode

    @property
    def preset_modes(self):
        """Return the list of available preset modes."""
        return [PRESET_AWAY, PRESET_ECO, PRESET_HOME]

    async def async_set_hvac_mode(self, hvac_mode):
        """Set hvac mode."""
        if hvac_mode not in self._hvac_list:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        self._hvac_mode = hvac_mode
        await self._async_copy_hvac_mode()
        self.async_write_ha_state()

    async def async_turn_on(self):
        """Turn the entity on."""
        if self.ac_mode:
            await self.async_set_hvac_mode(HVACMode.COOL)
        else:
            await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self):
        """Turn the entity off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._target_temp = temperature
        self._attributes[self._preset_mode + "_temp"] = self._target_temp
        await self._async_copy_temperature()
        self.async_write_ha_state()

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self._min_temp is not None:
            return self._min_temp
        return super().min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._max_temp is not None:
            return self._max_temp
        return super().max_temp

    async def _async_sensor_changed(self, event):
        """Handle temperature changes."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        self._async_update_temp(new_state)
        self.async_write_ha_state()

    async def _async_thermostat_changed(self, event):
        """Handle physical thermostat state/setpoint changes."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        # Skip self-triggered updates to prevent sync loops
        if self._syncing_to_physical:
            return

        # Sync HVAC mode from physical thermostat
        try:
            phys_hvac = HVACMode(new_state.state)
            if phys_hvac in self._hvac_list and phys_hvac != self._hvac_mode:
                self._hvac_mode = phys_hvac
        except ValueError:
            pass

        # Sync target temperature from physical thermostat
        new_temperature = new_state.attributes.get(ATTR_TEMPERATURE)
        if new_temperature is not None:
            self._target_temp = float(new_temperature)
            if self._preset_mode in self.preset_modes:
                self._attributes[self._preset_mode + "_temp"] = self._target_temp

        self.async_write_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from sensor."""
        try:
            cur_temp = float(state.state)
            if math.isnan(cur_temp) or math.isinf(cur_temp):
                raise ValueError(f"Sensor has illegal state {state.state}")
            self._cur_temp = cur_temp
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    @property
    def _is_device_active(self):
        """If the toggleable device is currently active."""
        if self._cur_temp is None or self._target_temp is None:
            return False
        if self.ac_mode:
            return self._cur_temp > self._target_temp
        return self._target_temp > self._cur_temp

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    async def async_set_preset_mode(self, preset_mode: str):
        """Set new preset mode."""
        if preset_mode not in self.preset_modes:
            return
        self._preset_mode = preset_mode
        temp = self._attributes.get(self._preset_mode + "_temp", self._target_temp)
        self._target_temp = float(temp)
        await self._async_copy_temperature()
        self.async_write_ha_state()

    async def _async_copy_temperature(self):
        """Copy temperature to physical thermostat entity."""
        self._syncing_to_physical = True
        try:
            data = {
                ATTR_ENTITY_ID: self.thermostat_entity_id,
                ATTR_TEMPERATURE: self._target_temp,
            }
            await self.hass.services.async_call(
                "climate", "set_temperature", data, context=self._context
            )
        finally:
            self._syncing_to_physical = False

    async def _async_copy_hvac_mode(self):
        """Copy HVAC mode to physical thermostat entity."""
        self._syncing_to_physical = True
        try:
            data = {
                ATTR_ENTITY_ID: self.thermostat_entity_id,
                "hvac_mode": self._hvac_mode,
            }
            await self.hass.services.async_call(
                "climate", "set_hvac_mode", data, context=self._context
            )
        finally:
            self._syncing_to_physical = False
