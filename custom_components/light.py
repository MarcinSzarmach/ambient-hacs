import logging
import asyncio
import voluptuous as vol
from homeassistant.components.light import (
    LightEntity,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR,
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
)
from homeassistant.const import CONF_TOKEN
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .const import DOMAIN, CONF_URL, DEFAULT_URL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """
    Set up AmbientLed lights from a config entry.
    """
    token = entry.data[CONF_TOKEN]
    url = entry.data.get(CONF_URL, DEFAULT_URL)
    ws = AmbientLedWebsocket(token, url, hass)
    await ws.connect()
    devices = await ws.get_devices()
    entities = []
    for dev in devices:
        entities.append(AmbientLedLight(dev, ws))
    async_add_entities(entities)

class AmbientLedWebsocket:
    def __init__(self, token, url, hass):
        self.token = token
        self.url = url
        self.hass = hass
        self.ws = None
        self.connected = False
        self.reconnect_task = None
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5
        self._listeners = []

    async def connect(self):
        """Connect to WebSocket with error handling and reconnection."""
        try:
            import websockets
            self.ws = await asyncio.wait_for(
                websockets.connect(
                    self.url, 
                    extra_headers={"Authorization": f"Bearer {self.token}"},
                    ping_interval=30,
                    ping_timeout=10
                ),
                timeout=10
            )
            self.connected = True
            _LOGGER.info("Connected to AmbientLed WebSocket")
            
            # Start listening for messages
            asyncio.create_task(self._listen())
            
        except asyncio.TimeoutError:
            _LOGGER.error("Connection timeout to AmbientLed WebSocket")
            await self._schedule_reconnect()
        except Exception as e:
            _LOGGER.error(f"Failed to connect to AmbientLed WebSocket: {e}")
            await self._schedule_reconnect()

    async def _listen(self):
        """Listen for incoming WebSocket messages."""
        try:
            while self.connected and self.ws:
                try:
                    message = await asyncio.wait_for(self.ws.recv(), timeout=60)
                    await self._handle_message(message)
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    if self.ws:
                        await self.ws.ping()
                except websockets.exceptions.ConnectionClosed:
                    _LOGGER.warning("WebSocket connection closed")
                    break
                except Exception as e:
                    _LOGGER.error(f"Error receiving message: {e}")
                    break
        except Exception as e:
            _LOGGER.error(f"WebSocket listen error: {e}")
        finally:
            self.connected = False
            await self._schedule_reconnect()

    async def _handle_message(self, message):
        """Handle incoming WebSocket message."""
        try:
            import json
            data = json.loads(message)
            
            # Handle device updates
            if data.get("method") == "getDevice" and data.get("status"):
                device_data = data.get("data")
                if device_data:
                    # Notify listeners about device update
                    for listener in self._listeners:
                        try:
                            await listener(device_data)
                        except Exception as e:
                            _LOGGER.error(f"Error in message listener: {e}")
                            
        except Exception as e:
            _LOGGER.error(f"Error handling message: {e}")

    async def _schedule_reconnect(self):
        """Schedule reconnection attempt."""
        if self.reconnect_task:
            self.reconnect_task.cancel()
        
        self.reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self):
        """Attempt to reconnect with exponential backoff."""
        for attempt in range(self.max_reconnect_attempts):
            try:
                await asyncio.sleep(self.reconnect_delay * (2 ** attempt))
                _LOGGER.info(f"Attempting to reconnect (attempt {attempt + 1}/{self.max_reconnect_attempts})")
                await self.connect()
                if self.connected:
                    _LOGGER.info("Successfully reconnected to AmbientLed WebSocket")
                    return
            except Exception as e:
                _LOGGER.error(f"Reconnection attempt {attempt + 1} failed: {e}")
        
        _LOGGER.error("Failed to reconnect after all attempts")

    async def get_devices(self):
        """Get devices with error handling."""
        if not self.connected or not self.ws:
            _LOGGER.error("Not connected to WebSocket")
            return []
        
        try:
            await self.ws.send('{"method": "getDevices", "id": "1"}')
            resp = await asyncio.wait_for(self.ws.recv(), timeout=10)
            import json
            data = json.loads(resp)
            return data.get("data", [])
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout getting devices")
            return []
        except Exception as e:
            _LOGGER.error(f"Error getting devices: {e}")
            return []

    async def send_command(self, device_id, method, params):
        """Send command with error handling."""
        if not self.connected or not self.ws:
            _LOGGER.error("Not connected to WebSocket")
            return False
        
        try:
            import json
            msg = {"method": method, "id": device_id, "data": params}
            await asyncio.wait_for(self.ws.send(json.dumps(msg)), timeout=5)
            return True
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout sending command")
            return False
        except Exception as e:
            _LOGGER.error(f"Error sending command: {e}")
            return False

    def add_listener(self, listener):
        """Add message listener."""
        self._listeners.append(listener)

    def remove_listener(self, listener):
        """Remove message listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def disconnect(self):
        """Disconnect WebSocket."""
        self.connected = False
        if self.reconnect_task:
            self.reconnect_task.cancel()
        if self.ws:
            await self.ws.close()

class AmbientLedLight(LightEntity):
    def __init__(self, device, ws):
        self._device = device
        self._ws = ws
        self._name = device.get("name", "AmbientLed")
        self._unique_id = device.get("_id")
        self._is_on = device.get("data", {}).get("lighting", False)
        self._brightness = device.get("data", {}).get("brightness", 255)
        self._hs_color = (0, 0)
        self._supported_features = SUPPORT_BRIGHTNESS | SUPPORT_COLOR
        self._available = True
        
        # Add listener for device updates
        self._ws.add_listener(self._handle_device_update)

    async def _handle_device_update(self, device_data):
        """Handle device state updates from WebSocket."""
        if device_data.get("_id") == self._unique_id:
            data = device_data.get("data", {})
            self._is_on = data.get("lighting", self._is_on)
            self._brightness = data.get("brightness", self._brightness)
            # Update color if available
            color = data.get("color", "#000000")
            if color and color != "#000000":
                # Convert hex to HS
                import colorsys
                color_rgb = tuple(int(color[i:i+2], 16) / 255 for i in (1, 3, 5))
                self._hs_color = colorsys.rgb_to_hsv(*color_rgb)[:2]
            
            self.async_write_ha_state()

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def is_on(self):
        return self._is_on

    @property
    def brightness(self):
        return self._brightness

    @property
    def hs_color(self):
        return self._hs_color

    @property
    def supported_features(self):
        return self._supported_features

    @property
    def available(self):
        return self._available and self._ws.connected

    async def async_turn_on(self, **kwargs):
        """Turn on the light with error handling."""
        params = {}
        if ATTR_BRIGHTNESS in kwargs:
            params["brightness"] = kwargs[ATTR_BRIGHTNESS]
        if ATTR_HS_COLOR in kwargs:
            # Convert HS to hex
            import colorsys
            rgb = colorsys.hsv_to_rgb(kwargs[ATTR_HS_COLOR][0], kwargs[ATTR_HS_COLOR][1], 1)
            hex_color = "#{:02x}{:02x}{:02x}".format(
                int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)
            )
            params["color"] = hex_color
        params["lighting"] = True
        
        success = await self._ws.send_command(self._unique_id, "setDevice", {"app": params})
        if success:
            self._is_on = True
            if "brightness" in params:
                self._brightness = params["brightness"]
            if "color" in params:
                self._hs_color = kwargs.get(ATTR_HS_COLOR, self._hs_color)
            self.async_write_ha_state()
        else:
            _LOGGER.error(f"Failed to turn on light {self._name}")

    async def async_turn_off(self, **kwargs):
        """Turn off the light with error handling."""
        success = await self._ws.send_command(self._unique_id, "setDevice", {"app": {"lighting": False}})
        if success:
            self._is_on = False
            self.async_write_ha_state()
        else:
            _LOGGER.error(f"Failed to turn off light {self._name}")

    async def async_update(self):
        """Update light state."""
        # This will be handled by WebSocket updates
        pass

    async def async_will_remove_from_hass(self):
        """Clean up when entity is removed."""
        self._ws.remove_listener(self._handle_device_update) 
