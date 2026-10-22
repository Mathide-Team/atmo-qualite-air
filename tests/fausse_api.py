"""Faux serveur Atmo Data partagé par les tests (données entièrement fictives)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from aiohttp import web

IDENTIFIANT = "test@exemple.invalid"
MOT_DE_PASSE = "secret"
ZONE = "67482"
ZONE_SANS_POLLEN = "67218"
ZONE_PANNE_POLLEN = "68066"
ZONE_HORS = "99999"
ZONE_SANS_DEMAIN = "25056"


def indice(code_zone: str, echeance: date, code: int, diffusion: date, **sous: int) -> dict[str, Any]:
    """Propriétés d'une entité ``indices/atmo``."""
    libelles = {1: "Bon", 2: "Moyen", 3: "Dégradé", 4: "Mauvais"}
    return {
        "type": "Feature",
        "properties": {
            "aasqa": "44",
            "date_maj": f"{diffusion.isoformat()}T12:00:00+02:00",
            "code_qual": code,
            "lib_qual": libelles.get(code, "?"),
            "coul_qual": "#50CCAA",
            "source": "ATMO Grand Est",
            "type_zone": "commune",
            "code_zone": code_zone,
            "lib_zone": "Ville de test",
            "code_no2": sous.get("no2", 1),
            "code_so2": sous.get("so2", 1),
            "code_o3": sous.get("o3", code),
            "code_pm10": sous.get("pm10", 1),
            "code_pm25": sous.get("pm25", 1),
            "date_dif": diffusion.isoformat(),
            "date_ech": echeance.isoformat(),
        },
        "geometry": {"type": "Point", "coordinates": [0, 0]},
    }


def pollen(code_zone: str, echeance: date) -> dict[str, Any]:
    """Propriétés d'une entité ``indices/pollens`` (code_qual en chaîne)."""
    return {
        "type": "Feature",
        "properties": {
            "aasqa": "44",
            "date_maj": f"{echeance.isoformat()}T09:00:00+02:00",
            "alerte": True,
            "code_ambr": 1,
            "code_arm": 1,
            "code_aul": 1,
            "code_boul": 4,
            "code_gram": 2,
            "code_oliv": 0,
            "code_qual": "4",
            "conc_ambr": 0,
            "conc_arm": 0,
            "conc_aul": 6,
            "conc_boul": 152.5,
            "conc_gram": 11,
            "conc_oliv": None,
            "date_dif": echeance.isoformat(),
            "date_ech": echeance.isoformat(),
            "lib_qual": "Élevé",
            "lib_zone": "Ville de test",
            "pollen_resp": "BETULA",
            "source": "ATMO Grand Est",
            "type_zone": "commune",
            "code_zone": code_zone,
        },
    }


@dataclass
class Etat:
    """État modifiable du faux serveur."""

    aujourdhui: date
    jetons_emis: int = 0
    jeton_valide: str = "jeton-1"
    refuser_identifiants: bool = False
    panne_indices: bool = False
    json_invalide: bool = False
    expirer_prochain: bool = False
    refuser_toujours: bool = False
    refuser_pollens: bool = False
    requetes: list[dict[str, str]] = field(default_factory=list)


def construire_app(etat: Etat) -> web.Application:
    async def login(request: web.Request) -> web.Response:
        corps = await request.json()
        if etat.refuser_identifiants or corps != {"username": IDENTIFIANT, "password": MOT_DE_PASSE}:
            return web.json_response({"code": 401, "message": "Identifiants invalides."}, status=401)
        etat.jetons_emis += 1
        etat.jeton_valide = f"jeton-{etat.jetons_emis}"
        return web.json_response({"token": etat.jeton_valide})

    def _autorise(request: web.Request) -> bool:
        if etat.refuser_toujours:
            return False
        if etat.expirer_prochain:
            etat.expirer_prochain = False
            etat.jeton_valide = "expire"
            return False
        return request.headers.get("Authorization") == f"Bearer {etat.jeton_valide}"

    async def indices(request: web.Request) -> web.Response:
        etat.requetes.append(dict(request.query))
        if not _autorise(request):
            return web.json_response({"code": 401, "message": "JWT Token not found"}, status=401)
        if etat.panne_indices:
            return web.Response(status=500)
        if etat.json_invalide:
            return web.Response(text="<html>maintenance</html>", content_type="text/html")
        zone = request.query.get("code_zone", "")
        j0 = etat.aujourdhui
        j1 = j0 + timedelta(days=1)
        hier = j0 - timedelta(days=1)
        entites = []
        if zone != ZONE_HORS:
            entites = [
                # Diffusion d'hier pour aujourd'hui, remplacée par celle du jour.
                indice(zone, j0, 3, hier),
                indice(zone, j0, 2, j0, no2=2, pm25=2),
                indice(zone, j1, 4, j0, o3=4),
                # Autre zone renvoyée par erreur : ignorée.
                indice("00000", j0, 1, j0),
            ]
        if zone == ZONE_SANS_DEMAIN:
            # Prévision du lendemain pas encore diffusée.
            entites = [e for e in entites if e["properties"]["date_ech"] != j1.isoformat()]
        return web.json_response({"type": "FeatureCollection", "features": entites})

    async def pollens(request: web.Request) -> web.Response:
        # refuser_pollens : jeton valable pour les indices ATMO mais refusé
        # pour les pollens, même après reconnexion (droits du compte).
        if etat.refuser_pollens or not _autorise(request):
            return web.json_response({"code": 401}, status=401)
        zone = request.query.get("code_zone", "")
        if zone == ZONE_PANNE_POLLEN:
            return web.Response(status=503)
        entites = [] if zone in (ZONE_SANS_POLLEN, ZONE_HORS) else [pollen(zone, etat.aujourdhui)]
        return web.json_response({"type": "FeatureCollection", "features": entites})

    app = web.Application()
    app.router.add_post("/api/login", login)
    app.router.add_get("/api/v2/data/indices/atmo", indices)
    app.router.add_get("/api/v2/data/indices/pollens", pollens)
    return app
