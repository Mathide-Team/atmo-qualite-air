"""Tests du client Atmo Data."""

from __future__ import annotations

from datetime import timedelta

import pytest
from aiohttp import ClientSession

from custom_components.atmo_qualite_air import api
from custom_components.atmo_qualite_air.api import (
    AtmoApiError,
    AtmoAuthError,
    AtmoDataClient,
    code_zone_valide,
)

from .fausse_api import IDENTIFIANT, MOT_DE_PASSE, ZONE, ZONE_HORS, ZONE_SANS_POLLEN, Etat


@pytest.fixture
async def session():
    async with ClientSession() as s:
        yield s


def _client(session: ClientSession, mot_de_passe: str = MOT_DE_PASSE) -> AtmoDataClient:
    return AtmoDataClient(session, IDENTIFIANT, mot_de_passe, base_url=api.BASE_URL)


@pytest.mark.parametrize(
    ("code", "attendu"),
    [("67482", True), ("2A004", True), ("246700488", True), ("6748", False), ("abcde", False), ("", False)],
)
def test_code_zone_valide(code: str, attendu: bool) -> None:
    assert code_zone_valide(code) is attendu


async def test_connexion(serveur, etat: Etat, session) -> None:
    client = _client(session)
    await client.async_login()
    assert etat.jetons_emis == 1


async def test_connexion_refusee(serveur, session) -> None:
    with pytest.raises(AtmoAuthError):
        await _client(session, "faux").async_login()


async def test_injoignable(session) -> None:
    client = AtmoDataClient(session, IDENTIFIANT, MOT_DE_PASSE, base_url="http://127.0.0.1:9")
    with pytest.raises(AtmoApiError):
        await client.async_login()


async def test_indices_diffusion_la_plus_recente(serveur, etat: Etat, session) -> None:
    j0 = etat.aujourdhui
    indices = await _client(session).async_get_indices(ZONE, j0, j0 + timedelta(days=1))
    assert set(indices) == {j0, j0 + timedelta(days=1)}
    aujourdhui = indices[j0]
    # La diffusion du jour (code 2) remplace celle de la veille (code 3).
    assert aujourdhui.code_qual == 2
    assert aujourdhui.date_dif == j0
    assert aujourdhui.sous_indices == {"no2": 2, "o3": 2, "pm10": 1, "pm25": 2, "so2": 1}
    assert aujourdhui.lib_zone == "Ville de test"
    assert aujourdhui.source == "ATMO Grand Est"
    assert indices[j0 + timedelta(days=1)].code_qual == 4


async def test_indices_parametres(serveur, etat: Etat, session) -> None:
    j0 = etat.aujourdhui
    await _client(session).async_get_indices(ZONE, j0, j0 + timedelta(days=1))
    assert etat.requetes[-1] == {
        "format": "geojson",
        "code_zone": ZONE,
        "date": (j0 + timedelta(days=1)).isoformat(),
        "date_historique": j0.isoformat(),
    }


async def test_jeton_reutilise(serveur, etat: Etat, session) -> None:
    client = _client(session)
    j0 = etat.aujourdhui
    await client.async_get_indices(ZONE, j0, j0)
    await client.async_get_indices(ZONE, j0, j0)
    assert etat.jetons_emis == 1


async def test_jeton_expire_reconnexion(serveur, etat: Etat, session) -> None:
    client = _client(session)
    j0 = etat.aujourdhui
    await client.async_get_indices(ZONE, j0, j0)
    etat.expirer_prochain = True
    indices = await client.async_get_indices(ZONE, j0, j0)
    assert indices[j0].code_qual == 2
    assert etat.jetons_emis == 2


async def test_jeton_toujours_refuse(serveur, etat: Etat, session) -> None:
    etat.refuser_toujours = True
    with pytest.raises(AtmoAuthError):
        await _client(session).async_get_indices(ZONE, etat.aujourdhui, etat.aujourdhui)


async def test_erreur_serveur(serveur, etat: Etat, session) -> None:
    etat.panne_indices = True
    with pytest.raises(AtmoApiError):
        await _client(session).async_get_indices(ZONE, etat.aujourdhui, etat.aujourdhui)


async def test_json_invalide(serveur, etat: Etat, session) -> None:
    etat.json_invalide = True
    with pytest.raises(AtmoApiError):
        await _client(session).async_get_indices(ZONE, etat.aujourdhui, etat.aujourdhui)


async def test_zone_sans_indice(serveur, etat: Etat, session) -> None:
    assert await _client(session).async_get_indices(ZONE_HORS, etat.aujourdhui, etat.aujourdhui) == {}


async def test_pollens(serveur, etat: Etat, session) -> None:
    j0 = etat.aujourdhui
    pollens = await _client(session).async_get_pollens(ZONE, j0, j0)
    indice = pollens[j0]
    assert indice.code_qual == 4  # chaîne "4" convertie
    assert indice.alerte is True
    assert indice.responsables == "BETULA"
    assert indice.taxons["boul"] == 4
    assert indice.concentrations["boul"] == 152.5
    assert indice.concentrations["oliv"] is None


async def test_pollens_absents(serveur, etat: Etat, session) -> None:
    j0 = etat.aujourdhui
    assert await _client(session).async_get_pollens(ZONE_SANS_POLLEN, j0, j0) == {}
