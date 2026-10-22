"""Client de l'API Atmo Data (Atmo France, fédération des AASQA).

Contrat vérifié sur la documentation v2 (https://admindata.atmo-france.org/api/doc/v2) :
- ``POST /api/login`` avec ``{"username", "password"}`` renvoie un jeton
  JWT (``{"token": ...}``) ; des identifiants faux donnent 401 ;
- chaque requête de données porte ``Authorization: Bearer <jeton>`` ; un
  jeton absent ou expiré donne 401 ;
- ``GET /api/v2/data/indices/atmo?format=geojson&code_zone=…&date=…&date_historique=…``
  renvoie une FeatureCollection. Chaque ``properties`` contient
  ``code_qual`` (0 à 7), ``lib_qual``, ``coul_qual``, les sous-indices
  ``code_no2``, ``code_o3``, ``code_pm10``, ``code_pm25``, ``code_so2``,
  ``date_ech`` (jour concerné), ``date_dif`` (jour de diffusion),
  ``lib_zone``, ``code_zone`` et ``source`` (AASQA) ;
- ``GET /api/v2/data/indices/pollens`` : même principe, ``code_qual`` y
  est une **chaîne**, avec ``alerte``, ``pollen_resp`` et un
  ``code_<taxon>``/``conc_<taxon>`` par taxon.

Seuls les trois derniers jours sont disponibles : l'intégration demande
la période « aujourd'hui → demain » et retient, pour chaque échéance, la
diffusion la plus récente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import LOGGER, POLLUANTS, TAXONS

BASE_URL = "https://admindata.atmo-france.org"

# Code INSEE de commune (2A/2B pour la Corse) ou SIREN d'EPCI (9 chiffres).
_MOTIF_ZONE = re.compile(r"^(?:\d{5}|2[AB]\d{3}|\d{9})$")


class AtmoError(Exception):
    """Erreur de base de l'intégration."""


class AtmoApiError(AtmoError):
    """L'API Atmo Data est injoignable ou a renvoyé une réponse invalide."""


class AtmoAuthError(AtmoError):
    """Identifiants refusés par Atmo Data."""


def code_zone_valide(code: str) -> bool:
    """Le code ressemble-t-il à un code INSEE de commune ou un SIREN d'EPCI ?"""
    return bool(_MOTIF_ZONE.match(code or ""))


def _entier(valeur: Any) -> int | None:
    """Convertit un code (entier ou chaîne) ; None si absent ou illisible."""
    LOGGER.debug("_entier() appelée")
    if valeur is None or valeur == "":
        LOGGER.debug("_entier() retourne None (valeur absente)")
        return None
    try:
        entier = int(valeur)
    except (TypeError, ValueError) as erreur:
        LOGGER.debug("code illisible, ignoré : %s", erreur)
        LOGGER.debug("_entier() retourne None (valeur illisible)")
        return None
    LOGGER.debug("_entier() retourne %s", entier)
    return entier


def _date(valeur: Any) -> date | None:
    LOGGER.debug("_date() appelée")
    try:
        lue = date.fromisoformat(str(valeur)[:10])
    except ValueError as erreur:
        LOGGER.debug("date illisible, ignorée : %s", erreur)
        LOGGER.debug("_date() retourne None")
        return None
    LOGGER.debug("_date() retourne %s", lue)
    return lue


@dataclass(frozen=True)
class IndiceAtmo:
    """Indice ATMO d'une zone pour une échéance."""

    code_zone: str
    lib_zone: str
    source: str | None
    date_ech: date
    date_dif: date | None
    code_qual: int
    lib_qual: str | None
    couleur: str | None
    sous_indices: dict[str, int | None] = field(default_factory=dict)


@dataclass(frozen=True)
class IndicePollen:
    """Indice pollinique d'une commune pour une échéance."""

    code_zone: str
    lib_zone: str
    source: str | None
    date_ech: date
    code_qual: int
    lib_qual: str | None
    alerte: bool
    responsables: str | None
    taxons: dict[str, int | None] = field(default_factory=dict)
    concentrations: dict[str, float | None] = field(default_factory=dict)


def _proprietes(donnees: Any) -> list[dict[str, Any]]:
    """Propriétés des entités d'une FeatureCollection, contrôle de forme."""
    LOGGER.debug("_proprietes() appelée")
    if not isinstance(donnees, dict) or not isinstance(donnees.get("features"), list):
        msg = "Réponse Atmo Data inattendue (FeatureCollection attendue)"
        LOGGER.debug("réponse inattendue : FeatureCollection attendue")
        raise AtmoApiError(msg)
    proprietes = [f.get("properties") or {} for f in donnees["features"] if isinstance(f, dict)]
    LOGGER.debug("_proprietes() retourne %s entité(s)", len(proprietes))
    return proprietes


def _fraicheur(prop: dict[str, Any]) -> tuple[str, str]:
    """Clé de tri : jour de diffusion, puis horodatage de mise à jour (ISO)."""
    return (str(prop.get("date_dif") or ""), str(prop.get("date_maj") or ""))


def _plus_recente_par_echeance(
    proprietes: list[dict[str, Any]], code_zone: str
) -> dict[date, dict[str, Any]]:
    """Pour chaque date d'échéance, la diffusion la plus récente de la zone."""
    LOGGER.debug("_plus_recente_par_echeance() appelée | zone=%s", code_zone)
    retenues: dict[date, dict[str, Any]] = {}
    for prop in proprietes:
        if str(prop.get("code_zone")) != code_zone:
            continue
        echeance = _date(prop.get("date_ech"))
        if echeance is None or _entier(prop.get("code_qual")) is None:
            continue
        actuelle = retenues.get(echeance)
        if actuelle is None or _fraicheur(prop) > _fraicheur(actuelle):
            retenues[echeance] = prop
    LOGGER.debug("_plus_recente_par_echeance() retourne %s échéance(s)", len(retenues))
    return retenues


def _parse_indice(prop: dict[str, Any]) -> IndiceAtmo:
    return IndiceAtmo(
        code_zone=str(prop["code_zone"]),
        lib_zone=str(prop.get("lib_zone") or prop["code_zone"]),
        source=prop.get("source"),
        date_ech=_date(prop["date_ech"]),  # type: ignore[arg-type]  # filtré en amont
        date_dif=_date(prop.get("date_dif")),
        code_qual=_entier(prop["code_qual"]),  # type: ignore[arg-type]
        lib_qual=prop.get("lib_qual"),
        couleur=prop.get("coul_qual"),
        sous_indices={p: _entier(prop.get(f"code_{p}")) for p in POLLUANTS},
    )


def _flottant(valeur: Any) -> float | None:
    LOGGER.debug("_flottant() appelée")
    try:
        lu = None if valeur is None else float(valeur)
    except (TypeError, ValueError) as erreur:
        LOGGER.debug("valeur illisible, ignorée : %s", erreur)
        LOGGER.debug("_flottant() retourne None")
        return None
    LOGGER.debug("_flottant() retourne %s", lu)
    return lu


def _parse_pollen(prop: dict[str, Any]) -> IndicePollen:
    return IndicePollen(
        code_zone=str(prop["code_zone"]),
        lib_zone=str(prop.get("lib_zone") or prop["code_zone"]),
        source=prop.get("source"),
        date_ech=_date(prop["date_ech"]),  # type: ignore[arg-type]
        code_qual=_entier(prop["code_qual"]),  # type: ignore[arg-type]
        lib_qual=prop.get("lib_qual"),
        alerte=prop.get("alerte") in (True, "true", "True", 1),
        responsables=prop.get("pollen_resp") or None,
        taxons={t: _entier(prop.get(f"code_{t}")) for t in TAXONS},
        concentrations={t: _flottant(prop.get(f"conc_{t}")) for t in TAXONS},
    )


class AtmoDataClient:
    """Client en lecture seule d'Atmo Data (URL injectable pour les tests)."""

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        base_url: str | None = None,
    ) -> None:
        LOGGER.debug("AtmoDataClient.__init__() appelé | url=%s", base_url or BASE_URL)
        self._session = session
        self._username = username
        self._password = password
        # Lue à l'instanciation : les tests peuvent surcharger api.BASE_URL.
        self._base_url = (base_url or BASE_URL).rstrip("/")
        self._jeton: str | None = None
        LOGGER.debug("AtmoDataClient.__init__() retourne")

    async def async_login(self) -> None:
        """Obtient un jeton JWT ; AtmoAuthError si les identifiants sont refusés."""
        LOGGER.debug("async_login() appelé")
        url = f"{self._base_url}/api/login"
        try:
            async with self._session.post(
                url, json={"username": self._username, "password": self._password}
            ) as response:
                if response.status in (400, 401, 403):
                    msg = "Identifiants Atmo Data refusés"
                    LOGGER.debug("identifiants refusés (statut %s)", response.status)
                    raise AtmoAuthError(msg)
                response.raise_for_status()
                donnees = await response.json(content_type=None)
        except ClientResponseError as erreur:
            msg = f"Atmo Data a répondu {erreur.status} à la connexion"
            LOGGER.debug("Atmo Data a répondu %s à la connexion", erreur.status)
            raise AtmoApiError(msg) from erreur
        except (ClientError, TimeoutError) as erreur:
            msg = "Atmo Data est injoignable (connexion)"
            LOGGER.debug("Atmo Data injoignable (connexion) : %s", erreur)
            raise AtmoApiError(msg) from erreur
        except ValueError as erreur:
            msg = "Réponse illisible d'Atmo Data (connexion)"
            LOGGER.debug("réponse illisible d'Atmo Data (connexion) : %s", erreur)
            raise AtmoApiError(msg) from erreur
        jeton = donnees.get("token") if isinstance(donnees, dict) else None
        if not jeton:
            msg = "Atmo Data n'a pas renvoyé de jeton"
            LOGGER.debug("aucun jeton dans la réponse d'Atmo Data")
            raise AtmoApiError(msg)
        self._jeton = str(jeton)
        LOGGER.debug("async_login() retourne (jeton obtenu)")

    async def _async_get_json(self, chemin: str, params: dict[str, Any], *, relance: bool = True) -> Any:
        """GET authentifié ; une seule reconnexion si le jeton a expiré."""
        LOGGER.debug("_async_get_json() appelé | chemin=%s relance=%s", chemin, relance)
        if self._jeton is None:
            LOGGER.debug("_async_get_json() : pas de jeton, connexion d'abord")
            await self.async_login()
        url = f"{self._base_url}/{chemin}"
        try:
            async with self._session.get(
                url, params=params, headers={"Authorization": f"Bearer {self._jeton}"}
            ) as response:
                if response.status == 401:
                    self._jeton = None
                    if not relance:
                        msg = "Jeton Atmo Data refusé après reconnexion"
                        LOGGER.debug("jeton refusé après reconnexion (%s)", chemin)
                        raise AtmoAuthError(msg)
                else:
                    response.raise_for_status()
                    LOGGER.debug("_async_get_json() retourne la réponse (%s)", chemin)
                    return await response.json(content_type=None)
        except ClientResponseError as erreur:
            msg = f"Atmo Data a répondu {erreur.status} pour {chemin}"
            LOGGER.debug("Atmo Data a répondu %s pour %s", erreur.status, chemin)
            raise AtmoApiError(msg) from erreur
        except (ClientError, TimeoutError) as erreur:
            msg = f"Atmo Data est injoignable ({chemin})"
            LOGGER.debug("Atmo Data injoignable (%s) : %s", chemin, erreur)
            raise AtmoApiError(msg) from erreur
        except ValueError as erreur:
            msg = f"Réponse illisible d'Atmo Data ({chemin})"
            LOGGER.debug("réponse illisible d'Atmo Data (%s) : %s", chemin, erreur)
            raise AtmoApiError(msg) from erreur
        # Jeton expiré : reconnexion puis une seule nouvelle tentative.
        LOGGER.debug("_async_get_json() relance une fois après reconnexion (%s)", chemin)
        return await self._async_get_json(chemin, params, relance=False)

    async def async_get_indices(self, code_zone: str, debut: date, fin: date) -> dict[date, IndiceAtmo]:
        """Indices ATMO de la zone, par date d'échéance, entre ``debut`` et ``fin``."""
        LOGGER.debug("async_get_indices() appelé | zone=%s", code_zone)
        donnees = await self._async_get_json(
            "api/v2/data/indices/atmo",
            {
                "format": "geojson",
                "code_zone": code_zone,
                "date": fin.isoformat(),
                "date_historique": debut.isoformat(),
            },
        )
        retenues = _plus_recente_par_echeance(_proprietes(donnees), code_zone)
        indices = {echeance: _parse_indice(prop) for echeance, prop in retenues.items()}
        LOGGER.debug("async_get_indices() retourne %s échéance(s)", len(indices))
        return indices

    async def async_get_pollens(self, code_zone: str, debut: date, fin: date) -> dict[date, IndicePollen]:
        """Indices polliniques de la commune, par date d'échéance."""
        LOGGER.debug("async_get_pollens() appelé | zone=%s", code_zone)
        donnees = await self._async_get_json(
            "api/v2/data/indices/pollens",
            {
                "format": "geojson",
                "code_zone": code_zone,
                "date": fin.isoformat(),
                "date_historique": debut.isoformat(),
                "with_geom": "false",
            },
        )
        retenues = _plus_recente_par_echeance(_proprietes(donnees), code_zone)
        pollens = {echeance: _parse_pollen(prop) for echeance, prop in retenues.items()}
        LOGGER.debug("async_get_pollens() retourne %s échéance(s)", len(pollens))
        return pollens
