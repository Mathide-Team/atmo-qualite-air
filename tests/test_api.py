"""Tests du client Atmo Data."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer

from custom_components.atmo_qualite_air import api
from custom_components.atmo_qualite_air.api import (
    AtmoApiError,
    AtmoAuthError,
    AtmoDataClient,
    code_zone_valide,
)

from .fausse_api import IDENTIFIANT, MOT_DE_PASSE, ZONE, ZONE_HORS, ZONE_SANS_POLLEN, Etat, construire_app


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


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [(None, None), ("", None), ("4", 4), (3, 3), ("abc", None), ([1], None)],
)
def test_entier(valeur: object, attendu: int | None) -> None:
    """Code entier ou chaîne ; None si absent ou illisible (jamais d'exception)."""
    assert api._entier(valeur) == attendu


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [(None, None), ("1.5", 1.5), (11, 11.0), ("x", None), ([1], None)],
)
def test_flottant(valeur: object, attendu: float | None) -> None:
    """Concentration flottante ; None si absente ou illisible."""
    assert api._flottant(valeur) == attendu


@pytest.mark.parametrize("valeur", ["pas une date", None, "2026-13-01"])
def test_date_illisible(valeur: object) -> None:
    """Une date illisible devient None au lieu de lever."""
    assert api._date(valeur) is None


@pytest.mark.parametrize(
    "donnees",
    [
        pytest.param([], id="liste"),
        pytest.param({"type": "FeatureCollection"}, id="sans-features"),
        pytest.param({"features": {"a": 1}}, id="features-non-liste"),
    ],
)
def test_proprietes_forme_inattendue(donnees: object) -> None:
    """Tout ce qui n'est pas une FeatureCollection devient AtmoApiError."""
    with pytest.raises(AtmoApiError, match="FeatureCollection attendue"):
        api._proprietes(donnees)


def test_proprietes_entites_non_dict_ignorees() -> None:
    """Les entités qui ne sont pas des objets sont ignorées ; propriétés absentes → {}."""
    assert api._proprietes({"features": ["bruit", {"properties": {"a": 1}}, {}]}) == [{"a": 1}, {}]


def test_plus_recente_garde_la_diffusion_la_plus_fraiche() -> None:
    """Une diffusion plus ancienne qui arrive après la récente ne la remplace pas.

    Les entités sans échéance lisible ou sans code de qualité sont écartées.
    """
    j0 = date(2026, 10, 22)
    recente = {"code_zone": ZONE, "date_ech": j0.isoformat(), "code_qual": 2, "date_dif": "2026-10-22"}
    ancienne = {"code_zone": ZONE, "date_ech": j0.isoformat(), "code_qual": 3, "date_dif": "2026-10-21"}
    sans_code = {"code_zone": ZONE, "date_ech": "2026-10-23", "code_qual": None}
    sans_date = {"code_zone": ZONE, "date_ech": "illisible", "code_qual": 1}
    retenues = api._plus_recente_par_echeance([recente, ancienne, sans_code, sans_date], ZONE)
    assert retenues == {j0: recente}


def _serveur_connexion(reponse: web.Response) -> TestClient:
    async def login(request: web.Request) -> web.Response:
        return reponse

    app = web.Application()
    app.router.add_post("/api/login", login)
    return TestClient(TestServer(app))


@pytest.mark.parametrize(
    ("reponse", "message"),
    [
        pytest.param(lambda: web.Response(status=500), "a répondu 500 à la connexion", id="http-500"),
        pytest.param(
            lambda: web.Response(text="<html>maintenance</html>", content_type="text/html"),
            r"Réponse illisible d'Atmo Data \(connexion\)",
            id="json-illisible",
        ),
        pytest.param(lambda: web.json_response({"code": 200}), "pas renvoyé de jeton", id="sans-jeton"),
        pytest.param(lambda: web.json_response(["jeton"]), "pas renvoyé de jeton", id="liste"),
        pytest.param(lambda: web.json_response({"token": ""}), "pas renvoyé de jeton", id="jeton-vide"),
    ],
)
async def test_connexion_reponse_invalide(session, reponse, message: str) -> None:
    """Toute connexion sans jeton exploitable devient AtmoApiError (pas AtmoAuthError)."""
    serveur = _serveur_connexion(reponse())
    await serveur.start_server()
    try:
        client = AtmoDataClient(session, IDENTIFIANT, MOT_DE_PASSE, base_url=str(serveur.make_url("/")))
        with pytest.raises(AtmoApiError, match=message):
            await client.async_login()
    finally:
        await serveur.close()


async def test_serveur_perdu_apres_connexion(etat: Etat, session) -> None:
    """Atmo Data injoignable entre la connexion et la requête : AtmoApiError explicite."""
    serveur = TestClient(TestServer(construire_app(etat)))
    await serveur.start_server()
    client = AtmoDataClient(session, IDENTIFIANT, MOT_DE_PASSE, base_url=str(serveur.make_url("/")))
    await client.async_login()
    await serveur.close()
    with pytest.raises(AtmoApiError, match=r"injoignable \(api/v2/data/indices/atmo\)"):
        await client.async_get_indices(ZONE, etat.aujourdhui, etat.aujourdhui)
