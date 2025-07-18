"""
AmbientLed Home Assistant Integration
"""

import logging
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass, config):
    """
    Set up the AmbientLed component.
    """
    return True

async def async_setup_entry(hass, entry):
    """
    Set up AmbientLed from a config entry.
    """
    try:
        await hass.config_entries.async_forward_entry_setups(entry, ["light"])
        return True
    except Exception as e:
        _LOGGER.error(f"Error setting up AmbientLed entry: {e}")
        return False

async def async_unload_entry(hass, entry):
    """
    Unload AmbientLed config entry.
    """
    try:
        # Unload light platform
        unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "light")
        
        if unload_ok:
            _LOGGER.info("AmbientLed integration unloaded successfully")
            
            # Cleanup WebSocket connections if no more entries
            from .light import get_websocket_manager
            manager = get_websocket_manager()
            await manager.cleanup_all()
        
        return unload_ok
    except Exception as e:
        _LOGGER.error(f"Error unloading AmbientLed entry: {e}")
        return False

async def async_migrate_entry(hass, config_entry):
    """Migrate old entry."""
    _LOGGER.info("Migrating from version %s", config_entry.version)
    return True 
