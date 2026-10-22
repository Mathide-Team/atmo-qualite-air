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
from .const import CONF_CODE_ZONE, DEFAULT_CODE_ZONE, DOMAIN, LOGGER, URL_COMPTE

_MOT_DE_PASSE = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class AtmoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Une entrée par territoire ; plusieurs entrées peuvent partager un compte."""

    VERSION = 1

    async def _async_valider(self, saisie: dict[str, Any]) -> tuple[dict[str, str], str | None]:
        """Connexion et lecture des indices de la zone ; erreurs du formulaire et libellé."""
        LOGGER.debug("_async_valider() appelé | zone=%s", saisie[CONF_CODE_ZONE])
        code_zone = saisie[CONF_CODE_ZONE].strip().upper()
        if not code_zone_valide(code_zone):
            LOGGER.debug("_async_valider() : code de zone invalide (%s)", code_zone)
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
        except AtmoAuthError as erreur:
            LOGGER.debug("identifiants refusés : %s", erreur)
            return {"base": "invalid_auth"}, None
        except AtmoApiError as erreur:
            LOGGER.debug("API Atmo Data injoignable : %s", erreur)
            return {"base": "cannot_connect"}, None
        if not indices:
            LOGGER.debug("_async_valider() : aucun indice pour la zone %s", code_zone)
            return {CONF_CODE_ZONE: "zone_inconnue"}, None
        LOGGER.debug("_async_valider() retourne %s indice(s)", len(indices))
        return {}, next(iter(indices.values())).lib_zone

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        LOGGER.debug("async_step_user() appelé | saisie=%s", user_input is not None)
        erreurs: dict[str, str] = {}
        if user_input is not None:
            code_zone = user_input[CONF_CODE_ZONE].strip().upper()
            await self.async_set_unique_id(code_zone)
            self._abort_if_unique_id_configured()
            erreurs, libelle = await self._async_valider(user_input)
            if not erreurs:
                LOGGER.debug("async_step_user() crée l'entrée | zone=%s", code_zone)
                return self.async_create_entry(
                    title=libelle or code_zone,
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_CODE_ZONE: code_zone,
                    },
                )
            else:
                LOGGER.debug("async_step_user() affiche le formulaire (erreurs=%s)", erreurs)
        defauts = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=defauts.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD): _MOT_DE_PASSE,
                vol.Required(CONF_CODE_ZONE, default=defauts.get(CONF_CODE_ZONE, DEFAULT_CODE_ZONE)): str,
            }
        )
        LOGGER.debug("async_step_user() retourne le formulaire")
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=erreurs,
            description_placeholders={"url_compte": URL_COMPTE},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Identifiants refusés : demander un nouveau mot de passe."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        LOGGER.debug("async_step_reauth_confirm() appelé | saisie=%s", user_input is not None)
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
                LOGGER.debug("async_step_reauth_confirm() met à jour l'entrée")
                return self.async_update_reload_and_abort(
                    entree,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
            else:
                LOGGER.debug("async_step_reauth_confirm() affiche le formulaire (erreurs=%s)", erreurs)
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=entree.data[CONF_USERNAME]): str,
                vol.Required(CONF_PASSWORD): _MOT_DE_PASSE,
            }
        )
        LOGGER.debug("async_step_reauth_confirm() retourne le formulaire")
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=erreurs)
