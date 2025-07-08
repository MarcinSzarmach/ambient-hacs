import logging
import asyncio
import json
import colorsys
import websockets
import voluptuous as vol
import certifi
from homeassistant.components.light import (
    LightEntity,
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ColorMode,
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
    
    try:
        await ws.connect()
        devices = await ws.get_devices()
        entities = []
        
        if not devices:
            _LOGGER.warning("No devices found or failed to get devices")
            return
            
        for dev in devices:
            # Check if device is a dictionary and has required fields
            if isinstance(dev, dict) and dev.get("_id") and dev.get("name"):
                try:
                    entities.append(AmbientLedLight(dev, ws))
                except Exception as e:
                    _LOGGER.error(f"Failed to create entity for device {dev.get('name', 'unknown')}: {e}")
            else:
                _LOGGER.warning(f"Invalid device data: {dev}")
        
        if entities:
            async_add_entities(entities)
        else:
            _LOGGER.warning("No valid devices found to create entities")
            
    except Exception as e:
        _LOGGER.error(f"Failed to setup AmbientLed integration: {e}")
        # Don't raise the exception to prevent integration from failing completely

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
            import ssl
            import certifi
            
            # Create SSL context in async way to avoid blocking calls
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            
            self.ws = await asyncio.wait_for(
                websockets.connect(
                    self.url, 
                    additional_headers={"Authorization": f"Bearer {self.token}"},
                    ssl=ssl_context
                ),
                timeout=10
            )
            self.connected = True
            _LOGGER.info("Connected to AmbientLed WebSocket")
            
            # Start listening for messages
            asyncio.create_task(self._listen())
            
        except asyncio.TimeoutError:
            _LOGGER.error("Connection timeout to AmbientLed WebSocket")
            self.connected = False
            raise Exception("Connection timeout - server not responding")
        except websockets.exceptions.InvalidURI:
            _LOGGER.error("Invalid WebSocket URL")
            self.connected = False
            raise Exception("Invalid WebSocket URL - please check the URL format")
        except websockets.exceptions.InvalidStatusCode as e:
            if e.status_code == 401:
                _LOGGER.error("Authentication failed - invalid token")
                self.connected = False
                raise Exception("Authentication failed - please check your token")
            else:
                _LOGGER.error(f"Server returned error {e.status_code}")
                self.connected = False
                raise Exception(f"Server error {e.status_code} - please check your configuration")
        except Exception as e:
            _LOGGER.error(f"Failed to connect to AmbientLed WebSocket: {e}")
            self.connected = False
            raise Exception(f"Connection failed: {str(e)}")

    async def _listen(self):
        """Listen for incoming WebSocket messages."""
        try:
            while self.connected and self.ws:
                try:
                    message = await asyncio.wait_for(self.ws.recv(), timeout=60)
                    await self._handle_message(message)
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    if self.ws and self.connected:
                        try:
                            await self.ws.ping()
                        except Exception as e:
                            _LOGGER.warning(f"Failed to send ping: {e}")
                            break
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
            # Check if message is empty or None
            if not message or message.strip() == "":
                return
                
            # Ignore ping/pong messages (both "pong" and "ping")
            message_text = message.strip().lower()
            if message_text in ["pong", "ping"]:
                return
                
            # Try to parse JSON
            try:
                data = json.loads(message)
            except json.JSONDecodeError as e:
                # Only log if it's not a ping/pong message
                if not message_text.startswith("ping") and not message_text.startswith("pong"):
                    _LOGGER.debug(f"Non-JSON message received (likely ping/pong): {message[:50]}")
                return
            
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
            
            # Check if response is empty
            if not resp or resp.strip() == "":
                _LOGGER.error("Empty response from WebSocket")
                return []
                
            data = json.loads(resp)
            return data.get("data", [])
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout getting devices")
            return []
        except json.JSONDecodeError as e:
            _LOGGER.error(f"Invalid JSON response: {resp[:100]}... Error: {e}")
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
        self._supported_color_modes = {ColorMode.HS}
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
    def supported_color_modes(self):
        return self._supported_color_modes

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
