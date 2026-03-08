"""The LMSCloud integration."""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_TIME_ZONE, CONF_USERNAME
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LMSCloudApiClient
from .const import CONF_BASE_DOMAIN, DOMAIN, PLATFORMS
from .coordinator import LMSCloudCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LMSCloud from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = LMSCloudApiClient(
        session=async_get_clientsession(hass),
        base_domain=entry.data[CONF_BASE_DOMAIN],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        time_zone=entry.data.get(CONF_TIME_ZONE, hass.config.time_zone or "UTC"),
    )

    coordinator = LMSCloudCoordinator(
        hass=hass,
        client=client,
        entry_id=entry.entry_id,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
