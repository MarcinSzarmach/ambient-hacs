"""
Config flow for AmbientLed integration.
"""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_TOKEN
from .const import DOMAIN, CONF_URL, DEFAULT_URL
import logging

_LOGGER = logging.getLogger(__name__)

class AmbientLedConfigFlow(config_entries.ConfigFlow):
    """AmbientLed config flow."""
    VERSION = 1
    DOMAIN = DOMAIN

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Validate token by testing WebSocket connection
            try:
                from .light import AmbientLedWebsocket
                ws = AmbientLedWebsocket(user_input[CONF_TOKEN], user_input.get(CONF_URL, DEFAULT_URL), self.hass)
                await ws.connect()
                
                if not ws.connected:
                    errors["base"] = "cannot_connect"
                else:
                    # Test getting devices
                    devices = await ws.get_devices()
                    if devices is None or len(devices) == 0:
                        errors["base"] = "no_devices"
                    else:
                        await ws.disconnect()
                        return self.async_create_entry(title="AmbientLed", data=user_input)
                        
            except Exception as e:
                _LOGGER.error(f"Config flow error: {e}")
                errors["base"] = "unknown"

        data_schema = vol.Schema({
            vol.Required(CONF_TOKEN): str,
            vol.Optional(CONF_URL, default=DEFAULT_URL): str,
        })
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors) 
