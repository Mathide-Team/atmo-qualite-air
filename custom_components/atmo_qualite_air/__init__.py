"""Intégration « Atmo Data (qualité de l'air) » : indices ATMO et pollinique."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AtmoDataClient
from .const import CONF_CODE_ZONE, LOGGER
from .coordinator import AtmoCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type AtmoConfigEntry = ConfigEntry[AtmoCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AtmoConfigEntry) -> bool:
    """Crée le client et le coordinateur de la zone, puis les capteurs."""
    LOGGER.debug("async_setup_entry() appelé | zone=%s", entry.data[CONF_CODE_ZONE])
    client = AtmoDataClient(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinateur = AtmoCoordinator(hass, entry, client, entry.data[CONF_CODE_ZONE])
    # Lève ConfigEntryNotReady (réessai) ou ConfigEntryAuthFailed (réauthentification).
    await coordinateur.async_config_entry_first_refresh()
    entry.runtime_data = coordinateur
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    LOGGER.debug("async_setup_entry() retourne True")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AtmoConfigEntry) -> bool:
    """Décharge les capteurs de l'entrée."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
