import logging
from typing import Optional, List

from homeassistant.components.climate import ClimateDevice, SUPPORT_TARGET_TEMPERATURE, SUPPORT_PRESET_MODE
from homeassistant.components.climate.const import HVAC_MODE_AUTO, HVAC_MODE_HEAT, HVAC_MODE_OFF, PRESET_NONE, \
    CURRENT_HVAC_HEAT, CURRENT_HVAC_OFF, CURRENT_HVAC_IDLE
from homeassistant.const import TEMP_CELSIUS
from meross_iot.cloud.devices.subdevices.thermostats import ValveSubDevice, ThermostatV3Mode, ThermostatMode
from meross_iot.manager import MerossManager
from meross_iot.meross_event import ThermostatTemperatureChange, ThermostatModeChange

from .common import DOMAIN, MANAGER, AbstractMerossEntityWrapper, cloud_io, HA_CLIMATE

_LOGGER = logging.getLogger(__name__)


class ValveEntityWrapper(ClimateDevice, AbstractMerossEntityWrapper):
    """Wrapper class to adapt the Meross thermostat into the Homeassistant platform"""

    def __init__(self, device: ValveSubDevice):
        super().__init__(device)

        self._id = self._device.uuid + ":" + self._device.subdevice_id
        self._device_name = self._device.name

        # For now, we assume that every Meross Thermostat supports the following modes.
        # This might be improved in the future by looking at the device abilities via get_abilities()
        self._flags = 0
        self._flags |= SUPPORT_TARGET_TEMPERATURE
        self._flags |= SUPPORT_PRESET_MODE

        # Device state
        self._current_temperature = None
        self._is_on = None
        self._device_mode = None
        self._target_temperature = None
        self._heating = None

        self.update()

    def device_event_handler(self, evt):
        if isinstance(evt, ThermostatTemperatureChange):
            self._current_temperature = float(evt.temperature.get('room'))/10
            self._target_temperature = float(evt.temperature.get('currentSet')) / 10
            self._heating = evt.temperature.get('heating') == 1
        elif isinstance(evt, ThermostatModeChange):
            self._device_mode = evt.mode
        else:
            _LOGGER.warning("Unhandled/ignored event: %s" % str(evt))

        self.async_schedule_update_ha_state(False)

    def force_state_update(self):
        self.schedule_update_ha_state(force_refresh=True)

    @cloud_io
    def update(self):
        try:
            state = self._device.get_status()
            self._is_online = self._device.online

            if self._is_online:
                self._is_on = state.get('togglex').get('onoff') == 1
                mode = state.get('mode').get('state')

                if self._device.type == "mts100v3":
                    self._device_mode = ThermostatV3Mode(mode)
                elif self._device.type == "mts100":
                    self._device_mode = ThermostatMode(mode)
                else:
                    _LOGGER.warning("Unknown device type %s" % self._device.type)

                temp = state.get('temperature')
                self._current_temperature = float(temp.get('room')) / 10
                self._target_temperature = float(temp.get('currentSet')) / 10
                self._heating = temp.get('heating') == 1
        except:
            _LOGGER.error("Failed to update data for device %s" % self.name)
            _LOGGER.debug("Error details:")
            self._is_online = False

    @property
    def current_temperature(self) -> float:
        return self._current_temperature

    @property
    def hvac_action(self) -> str:
        if not self._is_on:
            return CURRENT_HVAC_OFF
        elif self._heating:
            return CURRENT_HVAC_HEAT
        else:
            return CURRENT_HVAC_IDLE

    @property
    def hvac_mode(self) -> str:
        if not self._is_on:
            return HVAC_MODE_OFF
        elif self._device_mode == ThermostatV3Mode.AUTO:
            return HVAC_MODE_AUTO
        elif self._device_mode == ThermostatV3Mode.CUSTOM:
            return HVAC_MODE_HEAT
        elif self._device_mode == ThermostatMode.SCHEDULE:
            return HVAC_MODE_AUTO
        elif self._device_mode == ThermostatMode.CUSTOM:
            return HVAC_MODE_HEAT
        else:
            return HVAC_MODE_HEAT

    @property
    def available(self) -> bool:
        # A device is available if it's online
        return self._is_online

    @property
    def name(self) -> str:
        return self._device_name

    @property
    def unique_id(self) -> str:
        return self._id

    @property
    def supported_features(self):
        return self._flags

    @property
    def device_info(self):
        return {
            'identifiers': {(DOMAIN, self._id)},
            'name': self._device_name,
            'manufacturer': 'Meross',
            'model': self._device.type,
            'via_device': (DOMAIN, self._device.uuid)
        }

    @property
    def temperature_unit(self) -> str:
        return TEMP_CELSIUS

    @property
    def hvac_modes(self) -> List[str]:
        return [HVAC_MODE_OFF, HVAC_MODE_AUTO, HVAC_MODE_HEAT]

    @cloud_io
    def set_temperature(self, **kwargs) -> None:
        self._device.set_target_temperature(kwargs.get('temperature'))

    @cloud_io
    def set_hvac_mode(self, hvac_mode: str) -> None:
        # NOTE: this method will also update the local state as the thermostat will take too much time to get the
        # command ACK.
        if hvac_mode == HVAC_MODE_OFF:
            self._device.turn_off()
            self._is_on = False  # Update local state
            self.async_schedule_update_ha_state()
            return

        if self._device.type == "mts100v3":
            if hvac_mode == HVAC_MODE_HEAT:
                def action(error, response):
                    if error is None:
                        self._device.set_mode(ThermostatV3Mode.CUSTOM)
                        self._device_mode = ThermostatV3Mode.CUSTOM  # Update local state
                self._device.turn_on(callback=action)
                self._is_on = True  # Update local state

            elif hvac_mode == HVAC_MODE_AUTO:
                def action(error, response):
                    if error is None:
                        self._device.set_mode(ThermostatV3Mode.AUTO)
                        self._device_mode = ThermostatV3Mode.AUTO  # Update local state
                self._device.turn_on(callback=action)
                self._is_on = True  # Update local state
            else:
                _LOGGER.warning("Unsupported mode for this device")

        elif self._device.type == "mts100":
            if hvac_mode == HVAC_MODE_HEAT:
                def action(error, response):
                    if error is None:
                        self._device.set_mode(ThermostatMode.CUSTOM)
                        self._device_mode = ThermostatMode.CUSTOM  # Update local state
                self._device.turn_on(callback=action)
                self._is_on = True  # Update local state
            elif hvac_mode == HVAC_MODE_AUTO:
                def action(error, response):
                    if error is None:
                        self._device.set_mode(ThermostatMode.SCHEDULE)
                        self._device_mode = ThermostatMode.SCHEDULE  # Update local state
                self._device.turn_on(callback=action)
                self._is_on = True  # Update local state
            else:
                _LOGGER.warning("Unsupported mode for this device")
        else:
            _LOGGER.warning("Unsupported mode for this device")

    @cloud_io
    def set_preset_mode(self, preset_mode: str) -> None:
        if self._device.type == "mts100v3":
            self._device.set_mode(ThermostatV3Mode[preset_mode])
            self._device_mode = ThermostatV3Mode[preset_mode]  # Update local state
        elif self._device.type == "mts100":
            self._device.set_mode(ThermostatMode[preset_mode])
            self._device_mode = ThermostatMode[preset_mode]  # Update local state
        else:
            _LOGGER.warning("Unsupported preset for this device")

    @property
    def target_temperature(self) -> Optional[float]:
        return self._target_temperature

    @property
    def target_temperature_step(self) -> Optional[float]:
        return 0.5

    @property
    def preset_mode(self) -> Optional[str]:
        return self._device.mode.name

    @property
    def preset_modes(self) -> Optional[List[str]]:
        if isinstance(self._device_mode, ThermostatV3Mode):
            return [e.name for e in ThermostatV3Mode]
        elif isinstance(self._device_mode, ThermostatMode):
            return [e.name for e in ThermostatMode]
        else:
            _LOGGER.warning("Unknown valve mode type.")
            return [PRESET_NONE]

    @property
    def is_aux_heat(self) -> Optional[bool]:
        return False

    @property
    def target_temperature_high(self) -> Optional[float]:
        # Not supported
        return None

    @property
    def target_temperature_low(self) -> Optional[float]:
        # Not supported
        return None

    @property
    def fan_mode(self) -> Optional[str]:
        # Not supported
        return None

    @property
    def fan_modes(self) -> Optional[List[str]]:
        # Not supported
        return None

    @property
    def swing_mode(self) -> Optional[str]:
        # Not supported
        return None

    @property
    def swing_modes(self) -> Optional[List[str]]:
        # Not supported
        return None

    def set_humidity(self, humidity: int) -> None:
        pass

    def set_fan_mode(self, fan_mode: str) -> None:
        pass

    def set_swing_mode(self, swing_mode: str) -> None:
        pass

    def turn_aux_heat_on(self) -> None:
        pass

    def turn_aux_heat_off(self) -> None:
        pass


async def async_setup_entry(hass, config_entry, async_add_entities):
    def sync_logic():
        thermostat_devices = []
        manager = hass.data[DOMAIN][MANAGER]  # type:MerossManager
        valves = manager.get_devices_by_kind(ValveSubDevice)
        for valve in valves:  # type: ValveSubDevice
            w = ValveEntityWrapper(device=valve)
            thermostat_devices.append(w)
            hass.data[DOMAIN][HA_CLIMATE][w.unique_id] = w
        return thermostat_devices

    thermostat_devices = await hass.async_add_executor_job(sync_logic)
    async_add_entities(thermostat_devices)


def setup_platform(hass, config, async_add_entities, discovery_info=None):
    pass

