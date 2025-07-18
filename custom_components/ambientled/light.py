import logging
import asyncio
import json
import colorsys
import websockets
import voluptuous as vol
from homeassistant.components.light import (
    LightEntity,
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ColorMode,
    ATTR_EFFECT,
    LightEntityFeature,
)
from homeassistant.const import CONF_TOKEN
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .const import DOMAIN, CONF_URL, DEFAULT_URL

# Global WebSocket connection manager
_websocket_manager = None

_LOGGER = logging.getLogger(__name__)

class WebSocketManager:
    """Manages WebSocket connections for AmbientLed integration."""
    
    def __init__(self):
        self._connections = {}
        self._lock = asyncio.Lock()
    
    async def get_connection(self, token, url, hass):
        """Get or create WebSocket connection for given token/url."""
        connection_key = f"{token}_{url}"
        
        async with self._lock:
            if connection_key in self._connections:
                connection = self._connections[connection_key]
                if connection.connected:
                    _LOGGER.info(f"Reusing existing WebSocket connection for {connection_key}")
                    return connection
                else:
                    _LOGGER.info(f"Removing stale connection for {connection_key}")
                    await connection.disconnect()
                    del self._connections[connection_key]
            
            # Create new connection
            _LOGGER.info(f"Creating new WebSocket connection for {connection_key}")
            connection = AmbientLedWebsocket(token, url, hass)
            self._connections[connection_key] = connection
            await connection.connect()
            return connection
    
    async def remove_connection(self, token, url):
        """Remove WebSocket connection."""
        connection_key = f"{token}_{url}"
        
        async with self._lock:
            if connection_key in self._connections:
                connection = self._connections[connection_key]
                await connection.disconnect()
                del self._connections[connection_key]
                _LOGGER.info(f"Removed WebSocket connection for {connection_key}")
    
    async def cleanup_all(self):
        """Cleanup all connections."""
        async with self._lock:
            for connection_key, connection in list(self._connections.items()):
                await connection.disconnect()
                _LOGGER.info(f"Cleaned up connection: {connection_key}")
            self._connections.clear()

def get_websocket_manager():
    """Get global WebSocket manager."""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager

async def async_setup_entry(hass, entry, async_add_entities):
    """
    Set up AmbientLed lights from a config entry.
    """
    token = entry.data[CONF_TOKEN]
    url = entry.data.get(CONF_URL, DEFAULT_URL)
    
    # Get WebSocket connection through manager
    manager = get_websocket_manager()
    try:
        ws_connection = await manager.get_connection(token, url, hass)
    except Exception as e:
        _LOGGER.error(f"Failed to connect to AmbientLed WebSocket: {e}")
        return
    
    try:
        devices = await ws_connection.get_devices()
        entities = []
        
        if not devices:
            _LOGGER.warning("No devices found or failed to get devices")
            return
            
        for dev in devices:
            # Check if device is a dictionary and has required fields
            if isinstance(dev, dict) and dev.get("_id") and dev.get("name"):
                try:
                    entities.append(AmbientLedLight(dev, ws_connection))
                    _LOGGER.info(f"Created entity for device: {dev.get('name')}")
                except Exception as e:
                    _LOGGER.error(f"Failed to create entity for device {dev.get('name', 'unknown')}: {e}")
            else:
                # Log the actual type and content for debugging
                dev_type = type(dev).__name__
                dev_content = str(dev)[:100] if dev else "None"
                _LOGGER.warning(f"Invalid device data - Type: {dev_type}, Content: {dev_content}")
        
        if entities:
            async_add_entities(entities)
        else:
            _LOGGER.warning("No valid devices found to create entities")
            
    except Exception as e:
        _LOGGER.error(f"Failed to setup AmbientLed integration: {e}")
        # Don't raise the exception to prevent integration from failing completely

async def async_unload_entry(hass, entry):
    """Unload the AmbientLed integration."""
    token = entry.data[CONF_TOKEN]
    url = entry.data.get(CONF_URL, DEFAULT_URL)
    
    # Remove connection through manager
    manager = get_websocket_manager()
    await manager.remove_connection(token, url)
    
    return True

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
        self._recv_lock = asyncio.Lock()
        self._pending_responses = {}
        self._message_id = 0
        self._listen_task = None
        self._shutdown = False

    async def connect(self):
        """Connect to WebSocket with error handling and reconnection."""
        if self._shutdown:
            raise Exception("WebSocket is shutting down")
            
        try:
            import ssl
            
            _LOGGER.info(f"Attempting to connect to WebSocket at: {self.url}")
            
            # Create SSL context without loading default certs to avoid blocking calls
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
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
            if self._listen_task:
                self._listen_task.cancel()
            self._listen_task = asyncio.create_task(self._listen())
            
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
        _LOGGER.info("Starting WebSocket listener")
        try:
            while self.connected and self.ws and not self._shutdown:
                try:
                    # Use lock to prevent concurrent recv calls
                    async with self._recv_lock:
                        message = await asyncio.wait_for(self.ws.recv(), timeout=60)
                    
                    # Log every message received
                    _LOGGER.info(f"WebSocket message received: {message}")
                    
                    # Handle the message
                    await self._handle_message(message)
                    
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    if self.ws and self.connected and not self._shutdown:
                        try:
                            await self.ws.ping()
                            _LOGGER.debug("Sent ping to keep connection alive")
                        except Exception as e:
                            _LOGGER.warning(f"Failed to send ping: {e}")
                            break
                except websockets.exceptions.ConnectionClosed as e:
                    _LOGGER.warning(f"WebSocket connection closed: {e}")
                    break
                except Exception as e:
                    _LOGGER.error(f"Error receiving message: {e}")
                    break
        except Exception as e:
            _LOGGER.error(f"WebSocket listen error: {e}")
        finally:
            _LOGGER.info("WebSocket listener stopped")
            self.connected = False
            if not self._shutdown:
                await self._schedule_reconnect()

    async def _handle_message(self, message):
        """Handle incoming WebSocket message."""
        try:
            # Check if message is empty or None
            if not message or message.strip() == "":
                _LOGGER.debug("Received empty message")
                return
                
            # Ignore ping/pong messages (both "pong" and "ping")
            message_text = message.strip().lower()
            if message_text in ["pong", "ping"]:
                _LOGGER.debug(f"Ignoring ping/pong message: {message_text}")
                return
                
            # Try to parse JSON
            try:
                data = json.loads(message)
                _LOGGER.info(f"Parsed WebSocket message: {json.dumps(data, indent=2)}")
            except json.JSONDecodeError as e:
                # Only log if it's not a ping/pong message
                if not message_text.startswith("ping") and not message_text.startswith("pong"):
                    _LOGGER.warning(f"Invalid JSON message: {message[:100]}... Error: {e}")
                return
            
            # Check if this is a response to a pending request
            if "id" in data:
                message_id = data.get("id")
                if message_id in self._pending_responses:
                    _LOGGER.info(f"Resolving pending response for message ID: {message_id}")
                    # Resolve the pending response
                    future = self._pending_responses.pop(message_id)
                    if not future.done():
                        future.set_result(data)
                    return
            
            # Handle device updates for listeners - check multiple possible methods
            device_data = None
            method = data.get("method", "")
            
            # Check for device updates in various message formats
            if method == "getDevice" and "data" in data:
                device_data = data["data"]
                _LOGGER.info(f"Device update via getDevice: {device_data.get('name', 'unknown')}")
            elif method == "getDevices" and "data" in data:
                # Handle array of devices
                devices = data["data"]
                if isinstance(devices, list):
                    for device in devices:
                        if isinstance(device, dict):
                            _LOGGER.info(f"Device update via getDevices: {device.get('name', 'unknown')}")
                            for listener in self._listeners:
                                try:
                                    await listener(device)
                                except Exception as e:
                                    _LOGGER.error(f"Error in message listener: {e}")
                    return
            elif method == "updateParams" and "data" in data:
                # This might be a response to our updateParams command
                _LOGGER.info(f"UpdateParams response received: {data}")
                return
            elif "data" in data and isinstance(data["data"], dict):
                # Generic device data update
                device_data = data["data"]
                _LOGGER.info(f"Generic device update: {device_data.get('name', 'unknown')}")
            
            # If we have device data, notify listeners
            if device_data and isinstance(device_data, dict):
                _LOGGER.info(f"Notifying listeners of device update: {device_data.get('name', 'unknown')} - ID: {device_data.get('_id', 'unknown')}")
                for listener in self._listeners:
                    try:
                        await listener(device_data)
                    except Exception as e:
                        _LOGGER.error(f"Error in message listener: {e}")
            else:
                _LOGGER.info(f"Unhandled message method: {method}")
                        
        except Exception as e:
            _LOGGER.error(f"Error handling message: {e}")

    async def _schedule_reconnect(self):
        """Schedule reconnection attempt."""
        if self._shutdown:
            return
            
        if self.reconnect_task:
            self.reconnect_task.cancel()
        self.reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self):
        """Attempt to reconnect to WebSocket."""
        for attempt in range(1, self.max_reconnect_attempts + 1):
            if self._shutdown:
                return
                
            try:
                _LOGGER.info(f"Attempting to reconnect (attempt {attempt}/{self.max_reconnect_attempts})")
                await self.connect()
                _LOGGER.info("Successfully reconnected to AmbientLed WebSocket")
                return
            except Exception as e:
                _LOGGER.error(f"Reconnection attempt {attempt} failed: {e}")
                if attempt < self.max_reconnect_attempts and not self._shutdown:
                    await asyncio.sleep(self.reconnect_delay)
        
        _LOGGER.error("Failed to reconnect after all attempts")

    async def get_devices(self):
        """Get devices with error handling."""
        if not self.connected or not self.ws:
            _LOGGER.error("Not connected to WebSocket")
            return []
        
        try:
            # Generate unique message ID
            self._message_id += 1
            message_id = str(self._message_id)
            
            # Create future for this request
            future = asyncio.Future()
            self._pending_responses[message_id] = future
            
            # Send message in the correct format expected by the backend
            # Use getDevicesIntegration for Home Assistant to get only light devices
            message = {
                "method": "getDevicesIntegration",
                "id": message_id,
                "data": {}
            }
            _LOGGER.info(f"Sending getDevicesIntegration request: {json.dumps(message)}")
            await self.ws.send(json.dumps(message))
            
            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(future, timeout=10)
            except asyncio.TimeoutError:
                # Remove from pending responses
                self._pending_responses.pop(message_id, None)
                _LOGGER.error("Timeout getting devices")
                return []
            
            _LOGGER.info(f"Response: {json.dumps(response)}")
            
            # Check if response indicates an error
            if not response.get("status", True):
                error_msg = response.get("data", {}).get("error", "Unknown error")
                _LOGGER.error(f"Server returned error: {error_msg}")
                return []
            
            # Check if data field exists and is a list
            devices = response.get("data", [])
            if not isinstance(devices, list):
                _LOGGER.error(f"Expected devices list, got: {type(devices)}")
                return []
            
            _LOGGER.info(f"Successfully retrieved {len(devices)} devices")
            return devices
            
        except Exception as e:
            _LOGGER.error(f"Error getting devices: {e}")
            return []

    async def send_command(self, device_id, method, params):
        """Send command with error handling."""
        if not self.connected or not self.ws:
            _LOGGER.error("Not connected to WebSocket")
            return False
        
        try:
            # Generate unique message ID
            self._message_id += 1
            message_id = str(self._message_id)
            
            # Format message based on method
            if method == "updateParams":
                # For updateParams, the backend expects: { id: device_id, data: params }
                msg = {
                    "method": method, 
                    "id": message_id, 
                    "data": {
                        "id": device_id,
                        "data": params
                    }
                }
            else:
                # For other methods, use the standard format
                msg = {"method": method, "id": message_id, "data": params}
            
            _LOGGER.info(f"Sending command: {json.dumps(msg)}")
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
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener):
        """Remove message listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def disconnect(self):
        """Disconnect WebSocket."""
        self._shutdown = True
        self.connected = False
        
        # Cancel tasks
        if self.reconnect_task:
            self.reconnect_task.cancel()
        if self._listen_task:
            self._listen_task.cancel()
        
        # Clear listeners
        self._listeners.clear()
        
        # Close WebSocket
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                _LOGGER.warning(f"Error closing WebSocket: {e}")

class AmbientLedLight(LightEntity):
    def __init__(self, device, ws):
        self._device = device
        self._ws = ws
        self._name = device.get("name", "AmbientLed")
        self._unique_id = device.get("_id")
        
        # Initialize state from device data
        device_data = device.get("data", {})
        self._is_on = device_data.get("lighting", False)
        
        # Convert device brightness (0-100) to Home Assistant brightness (0-255)
        device_brightness = device_data.get("brightness", 0)
        self._brightness = int((device_brightness / 100) * 255)
        
        self._effect = device_data.get("effect", "Fade")
        
        # Convert color from hex to HS
        color = device_data.get("color", "#ffffff")
        if color and color.startswith("#"):
            try:
                color_rgb = tuple(int(color[i:i+2], 16) / 255 for i in (1, 3, 5))
                self._hs_color = colorsys.rgb_to_hsv(*color_rgb)[:2]
            except (ValueError, IndexError):
                self._hs_color = (0, 0)
        else:
            self._hs_color = (0, 0)
        
        self._supported_color_modes = {ColorMode.HS}
        
        # Set availability based on device online status
        self._available = device.get("online", False)
        
        # Available effects for this device - handle both string and array formats
        effects = device_data.get("effects", [])
        if isinstance(effects, list) and effects:
            self._effects = effects
        elif isinstance(effects, str):
            # If effects is a string, try to parse it as a comma-separated list
            try:
                self._effects = [effect.strip() for effect in effects.split(",") if effect.strip()]
            except:
                self._effects = ["Fade", "Fire", "Rain", "Rainbow", "Rainbow vertical", "Firework", "Romantic", "Disco"]
        else:
            # Fallback effects if none provided
            self._effects = ["Fade", "Fire", "Rain", "Rainbow", "Rainbow vertical", "Firework", "Romantic", "Disco"]
        
        _LOGGER.info(f"Created light entity: {self._name} (ID: {self._unique_id})")
        _LOGGER.info(f"Initial state - On: {self._is_on}, Brightness: {self._brightness} (from device: {device_brightness}), Effect: {self._effect}")
        _LOGGER.info(f"Device online: {self._available}")
        _LOGGER.info(f"Available effects: {self._effects}")
        
        # Add listener for device updates
        self._ws.add_listener(self._handle_device_update)

    async def _handle_device_update(self, device_data):
        """Handle device state updates from WebSocket."""
        if device_data.get("_id") == self._unique_id:
            _LOGGER.info(f"Received device update for {self._name}: {json.dumps(device_data, indent=2)}")
            
            # Update device availability based on online status
            old_available = self._available
            self._available = device_data.get("online", False)
            if old_available != self._available:
                _LOGGER.info(f"Device availability changed for {self._name}: {old_available} -> {self._available}")
                # Force state update when availability changes
                self.async_write_ha_state()
            
            data = device_data.get("data", {})
            old_state = {
                "is_on": self._is_on,
                "brightness": self._brightness,
                "effect": self._effect,
                "hs_color": self._hs_color
            }
            
            # Update lighting state
            if "lighting" in data:
                self._is_on = data.get("lighting", self._is_on)
                _LOGGER.info(f"Updated lighting state: {self._is_on}")
            
            # Update brightness - convert device brightness (0-100) to Home Assistant brightness (0-255)
            if "brightness" in data:
                device_brightness = data.get("brightness", 0)
                ha_brightness = int((device_brightness / 100) * 255)
                self._brightness = ha_brightness
                _LOGGER.info(f"Updated brightness: Device {device_brightness} -> HA {ha_brightness}")
            
            # Update effect
            if "effect" in data:
                self._effect = data.get("effect", self._effect)
                _LOGGER.info(f"Updated effect: {self._effect}")
            
            # Update color
            if "color" in data:
                color = data.get("color", "#ffffff")
                if color and color.startswith("#"):
                    try:
                        color_rgb = tuple(int(color[i:i+2], 16) / 255 for i in (1, 3, 5))
                        self._hs_color = colorsys.rgb_to_hsv(*color_rgb)[:2]
                        _LOGGER.info(f"Updated color: {color} -> HS: {self._hs_color}")
                    except (ValueError, IndexError):
                        _LOGGER.warning(f"Invalid color format: {color}")
            
            # Update effects list if provided
            if "effects" in data:
                effects = data["effects"]
                if isinstance(effects, list) and effects:
                    self._effects = effects
                    _LOGGER.info(f"Updated effects list: {self._effects}")
                elif isinstance(effects, str):
                    try:
                        self._effects = [effect.strip() for effect in effects.split(",") if effect.strip()]
                        _LOGGER.info(f"Updated effects list from string: {self._effects}")
                    except:
                        _LOGGER.warning(f"Could not parse effects string: {effects}")
            
            # Check if state actually changed
            new_state = {
                "is_on": self._is_on,
                "brightness": self._brightness,
                "effect": self._effect,
                "hs_color": self._hs_color
            }
            
            if old_state != new_state:
                _LOGGER.info(f"State changed for {self._name}: {old_state} -> {new_state}")
                # Force state update
                self.async_write_ha_state()
            else:
                _LOGGER.debug(f"No state change for {self._name}")

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
    def color_mode(self):
        """Return the color mode of the light."""
        return ColorMode.HS

    @property
    def effect_list(self):
        """Return the list of supported effects."""
        _LOGGER.info(f"Effect list for {self._name}: {self._effects}")
        return self._effects

    @property
    def effect(self):
        """Return the current effect."""
        return self._effect

    @property
    def available(self):
        """Return if the light is available."""
        return self._available and self._ws.connected

    @property
    def supported_features(self):
        """Return the supported features of the light."""
        return LightEntityFeature.EFFECT

    async def async_turn_on(self, **kwargs):
        """Turn on the light with error handling."""
        _LOGGER.info(f"Turning on {self._name} with kwargs: {kwargs}")
        
        params = {}
        if ATTR_BRIGHTNESS in kwargs:
            # Convert Home Assistant brightness (0-255) to device brightness (0-100)
            ha_brightness = kwargs[ATTR_BRIGHTNESS]
            device_brightness = int((ha_brightness / 255) * 100)
            params["brightness"] = device_brightness
            _LOGGER.info(f"Converting brightness: HA {ha_brightness} -> Device {device_brightness}")
        if ATTR_HS_COLOR in kwargs:
            # Convert HS to hex - fix the formatting
            h, s = kwargs[ATTR_HS_COLOR]
            # Convert HSV to RGB (h is in degrees 0-360, s and v are 0-1)
            rgb = colorsys.hsv_to_rgb(h/360, s/100, 1)
            # Convert RGB to hex
            hex_color = "#{:02x}{:02x}{:02x}".format(
                int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)
            )
            params["color"] = hex_color
            _LOGGER.info(f"Setting color to: {hex_color} (HS: {kwargs[ATTR_HS_COLOR]})")
        if ATTR_EFFECT in kwargs:
            params["effect"] = kwargs[ATTR_EFFECT]
            _LOGGER.info(f"Setting effect to: {kwargs[ATTR_EFFECT]}")
        params["lighting"] = True
        
        # Use updateParams method for Home Assistant integration
        success = await self._ws.send_command(self._unique_id, "updateParams", params)
        if success:
            self._is_on = True
            if "brightness" in params:
                # Store the Home Assistant brightness value, not the device value
                self._brightness = kwargs.get(ATTR_BRIGHTNESS, self._brightness)
            if "color" in params:
                self._hs_color = kwargs.get(ATTR_HS_COLOR, self._hs_color)
            if "effect" in params:
                self._effect = params["effect"]
            _LOGGER.info(f"Successfully turned on {self._name}")
            self.async_write_ha_state()
        else:
            _LOGGER.error(f"Failed to turn on light {self._name}")

    async def async_turn_off(self, **kwargs):
        """Turn off the light with error handling."""
        _LOGGER.info(f"Turning off {self._name}")
        params = {"lighting": False}
        success = await self._ws.send_command(self._unique_id, "updateParams", params)
        if success:
            self._is_on = False
            _LOGGER.info(f"Successfully turned off {self._name}")
            self.async_write_ha_state()
        else:
            _LOGGER.error(f"Failed to turn off light {self._name}")

    async def async_update(self):
        """Update the light state."""
        # The state is updated via WebSocket messages, so no manual update needed
        pass

    async def async_will_remove_from_hass(self):
        """Clean up when entity is removed."""
        self._ws.remove_listener(self._handle_device_update) 
