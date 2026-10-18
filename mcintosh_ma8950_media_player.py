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

# Create a list of available sources for the UI, excluding the relative 'Next'/'Previous' commands
AVAILABLE_SOURCES = [v for k, v in SOURCE_MAPPING.items() if k not in ["U", "D"]]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_PORT): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
})

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the McIntosh MA8950 media player platform."""
    name = config.get(CONF_NAME)
    port_url = config.get(CONF_PORT)
    
    api = McIntoshMA8950API(port_url)
    async_add_entities([McIntoshMA8950Device(api, name)], update_before_add=True)

class McIntoshMA8950Device(MediaPlayerEntity):
    """Representation of a McIntosh MA8950 Amplifier."""

    def __init__(self, api: McIntoshMA8950API, name: str):
        """Initialize the media player."""
        self._api = api
        self._attr_name = name
        self._attr_device_class = MediaPlayerDeviceClass.RECEIVER
        
        self._state = STATE_UNAVAILABLE
        self._volume = 0.0
        self._source = None
        self._source_list = AVAILABLE_SOURCES

        self._attr_supported_features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.SELECT_SOURCE
        )

    @property
    def state(self):
        """Return the state of the device (ON, OFF, or UNAVAILABLE)."""
        return self._state

    @property
    def volume_level(self):
        """Return the volume level of the media player (0.0 to 1.0)."""
        return self._volume

    @property
    def source(self):
        """Return the current input source."""
        return self._source

    @property
    def source_list(self):
        """Return the list of available input sources."""
        return self._source_list

    async def async_update(self):
        """Fetch the latest status from the amplifier."""
        try:
            if not self._api._connected:
                success = await self._api.connect()
                if not success:
                    self._state = STATE_UNAVAILABLE
                    return

            status = await self._api.get_status()
            
            if status:
                power_on = status.get("power", False)
                self._state = STATE_ON if power_on else STATE_OFF

                if "volume" in status:
                    self._volume = min(1.0, max(0.0, status["volume"] / 100.0))

                if "source" in status:
                    self._source = status["source"]
            else:
                self._state = STATE_UNAVAILABLE
                
        except Exception as e:
            _LOGGER.error(f"Error updating McIntosh MA8950 state: {e}")
            self._state = STATE_UNAVAILABLE

    async def async_turn_on(self):
        """Turn the amplifier on."""
        if await self._api.turn_on():
            self._state = STATE_ON
            self.async_write_ha_state()

    async def async_turn_off(self):
        """Turn the amplifier off."""
        if await self._api.turn_off():
            self._state = STATE_OFF
            self.async_write_ha_state()

    async def async_set_volume_level(self, volume):
        """Set volume level, range 0.0 to 1.0."""
        mcintosh_volume = int(volume * 100)
        if await self._api.set_volume(mcintosh_volume):
            self._volume = volume
            self.async_write_ha_state()

    async def async_volume_up(self):
        """Turn volume up for media player."""
        current_vol = int(self._volume * 100)
        target_vol = min(100, current_vol + 1)
        await self._api.set_volume(target_vol)

    async def async_volume_down(self):
        """Turn volume down for media player."""
        current_vol = int(self._volume * 100)
        target_vol = max(0, current_vol - 1)
        await self._api.set_volume(target_vol)

    async def async_select_source(self, source):
        """Select input source."""
        if await self._api.select_source(source):
            self._source = source
            self.async_write_ha_state()