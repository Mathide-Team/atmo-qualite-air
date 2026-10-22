"""Coordonnateur : indices ATMO et pollinique d'une zone, aujourd'hui et demain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AtmoAuthError, AtmoError, IndiceAtmo, IndicePollen
from .const import LOGGER, UPDATE_INTERVAL_MIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .api import AtmoDataClient


@dataclass(frozen=True)
class AtmoData:
    """Données consolidées d'une zone à une mise à jour donnée."""

    aujourdhui: IndiceAtmo | None
    demain: IndiceAtmo | None
    pollen: IndicePollen | None


class AtmoCoordinator(DataUpdateCoordinator[AtmoData]):
    """Interroge Atmo Data toutes les heures pour une zone.

    L'indice ATMO est la donnée principale : son échec fait échouer la
    mise à jour. L'indice pollinique est secondaire (pas diffusé partout,
    ni toute l'année) : son échec laisse l'indice ATMO disponible.
    Des identifiants refusés déclenchent la réauthentification.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AtmoDataClient,
        code_zone: str,
    ) -> None:
        LOGGER.debug("AtmoCoordinator.__init__() appelé | zone=%s", code_zone)
        super().__init__(
            hass,
            LOGGER,
            name=f"Atmo Data {code_zone}",
            config_entry=entry,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MIN),
        )
        self._client = client
        self.code_zone = code_zone
        LOGGER.debug("AtmoCoordinator.__init__() retourne")

    async def _async_update_data(self) -> AtmoData:
        LOGGER.debug("_async_update_data() appelé | zone=%s", self.code_zone)
        # Jour civil local (fuseau de Home Assistant) : les indices sont
        # établis par jour en heure française.
        aujourdhui: date = dt_util.now().date()
        demain = aujourdhui + timedelta(days=1)
        try:
            indices = await self._client.async_get_indices(self.code_zone, aujourdhui, demain)
        except AtmoAuthError as erreur:
            LOGGER.debug("authentification refusée (%s) : %s", self.code_zone, erreur)
            raise ConfigEntryAuthFailed(str(erreur)) from erreur
        except AtmoError as erreur:
            msg = f"Mise à jour impossible : {erreur}"
            LOGGER.debug("mise à jour impossible (%s) : %s", self.code_zone, erreur)
            raise UpdateFailed(msg) from erreur
        pollen: IndicePollen | None = None
        try:
            pollens = await self._client.async_get_pollens(self.code_zone, aujourdhui, aujourdhui)
            pollen = pollens.get(aujourdhui)
        except AtmoAuthError as erreur:
            LOGGER.debug("authentification refusée (pollens, %s) : %s", self.code_zone, erreur)
            raise ConfigEntryAuthFailed(str(erreur)) from erreur
        except AtmoError as erreur:
            LOGGER.debug("indice pollinique indisponible (%s) : %s", self.code_zone, erreur)
            LOGGER.warning("Indice pollinique indisponible pour %s : %s", self.code_zone, erreur)
        LOGGER.debug("_async_update_data() retourne les données (%s)", self.code_zone)
        return AtmoData(
            aujourdhui=indices.get(aujourdhui),
            demain=indices.get(demain),
            pollen=pollen,
        )
