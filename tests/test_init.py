"""Tests de l'installation et des capteurs."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.atmo_qualite_air.const import CONF_CODE_ZONE, DOMAIN

from .fausse_api import IDENTIFIANT, MOT_DE_PASSE, ZONE, ZONE_PANNE_POLLEN, ZONE_SANS_POLLEN, Etat


async def _demarrer(hass: HomeAssistant, zone: str = ZONE) -> MockConfigEntry:
    entree = MockConfigEntry(
        domain=DOMAIN,
        title="Ville de test",
        unique_id=zone,
        data={"username": IDENTIFIANT, "password": MOT_DE_PASSE, CONF_CODE_ZONE: zone},
    )
    entree.add_to_hass(hass)
    await hass.config_entries.async_setup(entree.entry_id)
    await hass.async_block_till_done()
    return entree


def _etat(hass: HomeAssistant, cle: str, zone: str = ZONE):
    """État d'un capteur par sa clé (identifiant unique ``<zone>_<clé>``)."""
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{zone}_{cle}")
    return hass.states.get(entity_id) if entity_id else None


async def test_capteurs(hass: HomeAssistant, serveur, etat: Etat) -> None:
    entree = await _demarrer(hass)
    assert entree.state is ConfigEntryState.LOADED
    indice = _etat(hass, "indice_atmo")
    assert indice is not None
    assert indice.state == "moyen"
    assert indice.attributes["code"] == 2
    assert indice.attributes["couleur"] == "#50CCAA"
    assert indice.attributes["date_echeance"] == etat.aujourdhui.isoformat()
    assert indice.attributes["sous_indice_pm25"] == 2
    assert indice.attributes["options"][0] == "absent"
    assert _etat(hass, "indice_atmo_demain").state == "mauvais"
    assert _etat(hass, "sous_indice_no2").state == "moyen"
    assert _etat(hass, "sous_indice_so2").state == "bon"


async def test_pollen(hass: HomeAssistant, serveur) -> None:
    await _demarrer(hass)
    pollen = _etat(hass, "indice_pollen")
    assert pollen is not None
    assert pollen.state == "eleve"
    assert pollen.attributes["alerte"] is True
    assert pollen.attributes["bouleau"] == 4
    assert pollen.attributes["concentration_bouleau"] == 152.5


async def test_sans_pollen(hass: HomeAssistant, serveur) -> None:
    """Pas d'indice pollinique diffusé : capteur inconnu, indice ATMO intact."""
    await _demarrer(hass, ZONE_SANS_POLLEN)
    assert _etat(hass, "indice_pollen", ZONE_SANS_POLLEN).state == STATE_UNKNOWN
    assert _etat(hass, "indice_atmo", ZONE_SANS_POLLEN).state == "moyen"


async def test_panne_pollen_independante(hass: HomeAssistant, serveur) -> None:
    await _demarrer(hass, ZONE_PANNE_POLLEN)
    assert _etat(hass, "indice_atmo", ZONE_PANNE_POLLEN).state == "moyen"
    assert _etat(hass, "indice_pollen", ZONE_PANNE_POLLEN).state == STATE_UNKNOWN


async def test_api_en_panne_au_demarrage(hass: HomeAssistant, serveur, etat: Etat) -> None:
    etat.panne_indices = True
    entree = await _demarrer(hass)
    assert entree.state is ConfigEntryState.SETUP_RETRY


async def test_identifiants_refuses_reauth(hass: HomeAssistant, serveur, etat: Etat) -> None:
    etat.refuser_identifiants = True
    entree = await _demarrer(hass)
    assert entree.state is ConfigEntryState.SETUP_ERROR
    flux = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flux)


async def test_panne_puis_retour(hass: HomeAssistant, serveur, etat: Etat) -> None:
    entree = await _demarrer(hass)
    etat.panne_indices = True
    await entree.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _etat(hass, "indice_atmo").state == STATE_UNAVAILABLE
    etat.panne_indices = False
    await entree.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _etat(hass, "indice_atmo").state == "moyen"


async def test_noms_traduits(hass: HomeAssistant, serveur) -> None:
    """Les noms des capteurs viennent des traductions (fr)."""
    hass.config.language = "fr"
    await _demarrer(hass)
    assert _etat(hass, "indice_atmo").name == "Qualité de l'air Ville de test Indice ATMO"
    assert _etat(hass, "indice_pollen").name == "Qualité de l'air Ville de test Indice pollinique"


async def test_jeton_expire_en_cours(hass: HomeAssistant, serveur, etat: Etat) -> None:
    """Un jeton expiré entre deux mises à jour : reconnexion transparente."""
    entree = await _demarrer(hass)
    etat.expirer_prochain = True
    await entree.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _etat(hass, "indice_atmo").state == "moyen"
    assert etat.jetons_emis == 2


async def test_dechargement(hass: HomeAssistant, serveur) -> None:
    entree = await _demarrer(hass)
    assert await hass.config_entries.async_unload(entree.entry_id)
    assert entree.state is ConfigEntryState.NOT_LOADED
