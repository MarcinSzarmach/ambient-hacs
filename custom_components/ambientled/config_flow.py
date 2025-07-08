"""
Config flow for AmbientLed integration.
"""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_TOKEN
from homeassistant.core import callback
from .const import DOMAIN, CONF_URL, DEFAULT_URL
import logging

_LOGGER = logging.getLogger(__name__)

class AmbientLedConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """AmbientLed config flow."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
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
            vol.Required(
                CONF_TOKEN, 
                description="Your AmbientLed user token. You can find this in your AmbientLed dashboard under account settings."
            ): str,
            vol.Optional(
                CONF_URL, 
                default=DEFAULT_URL,
                description="WebSocket URL for your AmbientLed backend. Leave as default unless you have a custom server."
            ): str,
        })
        
        # Add helpful error messages
        if errors:
            if errors["base"] == "cannot_connect":
                errors["base"] = "Unable to connect to AmbientLed backend. Please check your token and URL."
            elif errors["base"] == "no_devices":
                errors["base"] = "No devices found. Please make sure you have at least one AmbientLed device configured."
            elif errors["base"] == "unknown":
                errors["base"] = "An unexpected error occurred. Please check your configuration and try again."
        
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return AmbientLedOptionsFlow(config_entry)

class AmbientLedOptionsFlow(config_entries.OptionsFlow):
    """AmbientLed options flow."""
    
    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_URL, 
                    default=self.config_entry.data.get(CONF_URL, DEFAULT_URL),
                    description="WebSocket URL for your AmbientLed backend. Change this if you have a custom server."
                ): str,
            })
        ) 
