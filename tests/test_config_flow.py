"""Tests de la configuration et de la réauthentification."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.atmo_qualite_air.const import CONF_CODE_ZONE, DEFAULT_CODE_ZONE, DOMAIN

from .fausse_api import IDENTIFIANT, MOT_DE_PASSE, ZONE, ZONE_HORS, Etat


def _saisie(zone: str = ZONE, mot_de_passe: str = MOT_DE_PASSE) -> dict[str, str]:
    return {CONF_USERNAME: IDENTIFIANT, CONF_PASSWORD: mot_de_passe, CONF_CODE_ZONE: zone}


async def _formulaire(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_formulaire_prerempli(hass: HomeAssistant) -> None:
    resultat = await _formulaire(hass)
    assert resultat["type"] is FlowResultType.FORM
    cle = next(k for k in resultat["data_schema"].schema if k == CONF_CODE_ZONE)
    assert cle.default() == DEFAULT_CODE_ZONE


async def test_creation(hass: HomeAssistant, serveur) -> None:
    resultat = await _formulaire(hass)
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], _saisie())
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert resultat["title"] == "Ville de test"
    assert resultat["data"] == _saisie()
    assert resultat["result"].unique_id == ZONE


async def test_identifiants_refuses(hass: HomeAssistant, serveur) -> None:
    resultat = await _formulaire(hass)
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], _saisie(mot_de_passe="faux")
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"base": "invalid_auth"}


async def test_api_en_panne(hass: HomeAssistant, serveur, etat: Etat) -> None:
    etat.panne_indices = True
    resultat = await _formulaire(hass)
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], _saisie())
    assert resultat["errors"] == {"base": "cannot_connect"}


async def test_zone_invalide(hass: HomeAssistant, serveur) -> None:
    resultat = await _formulaire(hass)
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], _saisie(zone="Strasbourg"))
    assert resultat["errors"] == {CONF_CODE_ZONE: "zone_invalide"}


async def test_zone_inconnue(hass: HomeAssistant, serveur) -> None:
    resultat = await _formulaire(hass)
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], _saisie(zone=ZONE_HORS))
    assert resultat["errors"] == {CONF_CODE_ZONE: "zone_inconnue"}


async def test_zone_deja_suivie(hass: HomeAssistant, serveur) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=ZONE, data=_saisie()).add_to_hass(hass)
    resultat = await _formulaire(hass)
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], _saisie())
    assert resultat["type"] is FlowResultType.ABORT
    assert resultat["reason"] == "already_configured"


async def test_reauthentification(hass: HomeAssistant, serveur) -> None:
    entree = MockConfigEntry(domain=DOMAIN, unique_id=ZONE, data=_saisie(mot_de_passe="ancien"))
    entree.add_to_hass(hass)
    resultat = await entree.start_reauth_flow(hass)
    assert resultat["step_id"] == "reauth_confirm"
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {CONF_USERNAME: IDENTIFIANT, CONF_PASSWORD: "faux"}
    )
    assert resultat["errors"] == {"base": "invalid_auth"}
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {CONF_USERNAME: IDENTIFIANT, CONF_PASSWORD: MOT_DE_PASSE}
    )
    assert resultat["type"] is FlowResultType.ABORT
    assert resultat["reason"] == "reauth_successful"
    assert entree.data[CONF_PASSWORD] == MOT_DE_PASSE
    assert entree.data[CONF_CODE_ZONE] == ZONE
