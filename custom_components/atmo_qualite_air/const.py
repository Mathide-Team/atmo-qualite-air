"""Constantes de l'intégration Atmo Data (qualité de l'air)."""

from __future__ import annotations

import logging

DOMAIN = "atmo_qualite_air"
LOGGER = logging.getLogger(__name__)

# Code INSEE (commune) ou SIREN (EPCI) du territoire suivi.
CONF_CODE_ZONE = "code_zone"
# Suggestion initiale : Strasbourg. N'importe quelle commune française
# couverte par une AASQA peut être suivie.
DEFAULT_CODE_ZONE = "67482"

# Les indices sont diffusés une fois par jour (vers 11 h et 14 h), avec
# parfois une mise à jour l'après-midi : une heure suffit largement.
UPDATE_INTERVAL_MIN = 60

# Indice ATMO (arrêté du 10 juillet 2020) : code → clé de traduction.
QUALIFICATIFS_ATMO: dict[int, str] = {
    0: "absent",
    1: "bon",
    2: "moyen",
    3: "degrade",
    4: "mauvais",
    5: "tres_mauvais",
    6: "extremement_mauvais",
    7: "evenement",
}

# Indice pollinique : code → clé de traduction.
QUALIFICATIFS_POLLEN: dict[int, str] = {
    0: "indisponible",
    1: "tres_faible",
    2: "faible",
    3: "modere",
    4: "eleve",
    5: "tres_eleve",
    6: "extremement_eleve",
}

# Sous-indices de l'indice ATMO (propriété ``code_<polluant>``).
POLLUANTS: tuple[str, ...] = ("no2", "o3", "pm10", "pm25", "so2")

# Taxons de l'indice pollinique (propriétés ``code_<taxon>`` et ``conc_<taxon>``).
TAXONS: dict[str, str] = {
    "ambr": "ambroisie",
    "arm": "armoise",
    "aul": "aulne",
    "boul": "bouleau",
    "gram": "graminees",
    "oliv": "olivier",
}
