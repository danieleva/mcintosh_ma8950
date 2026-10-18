import logging
import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    PLATFORM_SCHEMA,
    MediaPlayerDeviceClass,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_PORT,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
import homeassistant.helpers.config_validation as cv

from .mcintosh_api import McIntoshMA8950API, SOURCE_MAPPING

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "McIntosh MA8950"

AVAILABLE_SOURCES = [v for k, v in SOURCE_MAPPING.items() if k not in ["U", "D"]]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_PORT): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
})

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    name = config.get(CONF_NAME)
    port_url = config.get(CONF_PORT)
    
    api = McIntoshMA8950API(port_url)
    async_add_entities([McIntoshMA8950Device(api, name, port_url)], update_before_add=True)

class McIntoshMA8950Device(MediaPlayerEntity):
    def __init__(self, api: McIntoshMA8950API, name: str, port_url: str):
        self._api = api
        self._attr_name = name
        self._attr_unique_id = f"mcintosh_ma8950_{port_url}"
        self._attr_device_class = MediaPlayerDeviceClass.RECEIVER
        
        self._state = STATE_UNAVAILABLE
        self._volume = 0.0
        self._is_muted = False
        self._source = None
        self._source_list = AVAILABLE_SOURCES

        self._attr_supported_features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.SELECT_SOURCE
        )

    @property
    def state(self):
        return self._state

    @property
    def volume_level(self):
        return self._volume

    @property
    def is_volume_muted(self):
        return self._is_muted

    @property
    def source(self):
        return self._source

    @property
    def source_list(self):
        return self._source_list

    async def async_update(self):
        try:
            status = await self._api.get_status()
            
            if status:
                power_on = status.get("power", False)
                self._state = STATE_ON if power_on else STATE_OFF

                if "volume" in status:
                    self._volume = min(1.0, max(0.0, status["volume"] / 100.0))
                
                if "mute" in status:
                    self._is_muted = status["mute"]

                if "source" in status:
                    self._source = status["source"]
            else:
                self._state = STATE_UNAVAILABLE
                
        except Exception as e:
            _LOGGER.error(f"Error updating McIntosh MA8950 state: {e}")
            self._state = STATE_UNAVAILABLE

    async def async_turn_on(self):
        if await self._api.turn_on():
            self._state = STATE_ON
            self.async_write_ha_state()

    async def async_turn_off(self):
        if await self._api.turn_off():
            self._state = STATE_OFF
            self.async_write_ha_state()

    async def async_set_volume_level(self, volume):
        mcintosh_volume = int(volume * 100)
        if await self._api.set_volume(mcintosh_volume):
            self._volume = volume
            self.async_write_ha_state()

    async def async_volume_up(self):
        current_vol = int(self._volume * 100)
        target_vol = min(100, current_vol + 1)
        await self._api.set_volume(target_vol)

    async def async_volume_down(self):
        current_vol = int(self._volume * 100)
        target_vol = max(0, current_vol - 1)
        await self._api.set_volume(target_vol)

    async def async_mute_volume(self, mute):
        if mute:
            if await self._api.mute_on():
                self._is_muted = True
        else:
            if await self._api.mute_off():
                self._is_muted = False
        self.async_write_ha_state()

    async def async_select_source(self, source):
        if await self._api.select_source(source):
            self._source = source
            self.async_write_ha_state()