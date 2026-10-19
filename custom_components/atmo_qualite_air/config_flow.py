"""Configuration : compte Atmo Data et territoire suivi."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.util import dt as dt_util

from .api import AtmoApiError, AtmoAuthError, AtmoDataClient, code_zone_valide
from .const import CONF_CODE_ZONE, DEFAULT_CODE_ZONE, DOMAIN

_MOT_DE_PASSE = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class AtmoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Une entrée par territoire ; plusieurs entrées peuvent partager un compte."""

    VERSION = 1

    async def _async_valider(self, saisie: dict[str, Any]) -> tuple[dict[str, str], str | None]:
        """Connexion et lecture des indices de la zone ; erreurs du formulaire et libellé."""
        code_zone = saisie[CONF_CODE_ZONE].strip().upper()
        if not code_zone_valide(code_zone):
            return {CONF_CODE_ZONE: "zone_invalide"}, None
        client = AtmoDataClient(
            async_get_clientsession(self.hass), saisie[CONF_USERNAME], saisie[CONF_PASSWORD]
        )
        aujourdhui = dt_util.now().date()
        try:
            await client.async_login()
            # Hier → demain : une zone sans aucun indice sur trois jours
            # n'est pas couverte (code erroné ou hors périmètre des AASQA).
            indices = await client.async_get_indices(
                code_zone, aujourdhui - timedelta(days=1), aujourdhui + timedelta(days=1)
            )
        except AtmoAuthError:
            return {"base": "invalid_auth"}, None
        except AtmoApiError:
            return {"base": "cannot_connect"}, None
        if not indices:
            return {CONF_CODE_ZONE: "zone_inconnue"}, None
        return {}, next(iter(indices.values())).lib_zone

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        erreurs: dict[str, str] = {}
        if user_input is not None:
            code_zone = user_input[CONF_CODE_ZONE].strip().upper()
            await self.async_set_unique_id(code_zone)
            self._abort_if_unique_id_configured()
            erreurs, libelle = await self._async_valider(user_input)
            if not erreurs:
                return self.async_create_entry(
                    title=libelle or code_zone,
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_CODE_ZONE: code_zone,
                    },
                )
        defauts = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=defauts.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD): _MOT_DE_PASSE,
                vol.Required(CONF_CODE_ZONE, default=defauts.get(CONF_CODE_ZONE, DEFAULT_CODE_ZONE)): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=erreurs)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Identifiants refusés : demander un nouveau mot de passe."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entree = self._get_reauth_entry()
        erreurs: dict[str, str] = {}
        if user_input is not None:
            saisie = {
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_CODE_ZONE: entree.data[CONF_CODE_ZONE],
            }
            erreurs, _libelle = await self._async_valider(saisie)
            if not erreurs:
                return self.async_update_reload_and_abort(
                    entree,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=entree.data[CONF_USERNAME]): str,
                vol.Required(CONF_PASSWORD): _MOT_DE_PASSE,
            }
        )
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=erreurs)
