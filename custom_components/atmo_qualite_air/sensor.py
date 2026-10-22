"""Capteurs : indice ATMO (aujourd'hui, demain), sous-indices et indice pollinique."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER, POLLUANTS, QUALIFICATIFS_ATMO, QUALIFICATIFS_POLLEN, TAXONS
from .coordinator import AtmoCoordinator, AtmoData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import AtmoConfigEntry


@dataclass(frozen=True, kw_only=True)
class AtmoSensorDescription(SensorEntityDescription):
    """Description d'un capteur : code lu dans les données, attributs associés."""

    code: Callable[[AtmoData], int | None]
    qualificatifs: dict[int, str]
    attributs: Callable[[AtmoData], dict[str, Any]] = lambda _donnees: {}


def _attributs_indice(indice: Any) -> dict[str, Any]:
    LOGGER.debug("_attributs_indice() appelée | indice=%s", indice is not None)
    if indice is None:
        LOGGER.debug("_attributs_indice() retourne un dictionnaire vide")
        return {}
    LOGGER.debug("_attributs_indice() retourne les attributs")
    return {
        "code": indice.code_qual,
        "libelle": indice.lib_qual,
        "couleur": indice.couleur,
        "date_echeance": indice.date_ech.isoformat(),
        "date_diffusion": indice.date_dif.isoformat() if indice.date_dif else None,
        "source": indice.source,
        **{f"sous_indice_{p}": indice.sous_indices.get(p) for p in POLLUANTS},
    }


def _attributs_pollen(donnees: AtmoData) -> dict[str, Any]:
    LOGGER.debug("_attributs_pollen() appelée | pollen=%s", donnees.pollen is not None)
    pollen = donnees.pollen
    if pollen is None:
        LOGGER.debug("_attributs_pollen() retourne un dictionnaire vide")
        return {}
    LOGGER.debug("_attributs_pollen() retourne les attributs")
    return {
        "code": pollen.code_qual,
        "libelle": pollen.lib_qual,
        "alerte": pollen.alerte,
        "responsables": pollen.responsables,
        "date_echeance": pollen.date_ech.isoformat(),
        "source": pollen.source,
        **{nom: pollen.taxons.get(t) for t, nom in TAXONS.items()},
        **{f"concentration_{nom}": pollen.concentrations.get(t) for t, nom in TAXONS.items()},
    }


def _sous_indice(polluant: str) -> Callable[[AtmoData], int | None]:
    LOGGER.debug("_sous_indice() appelée | polluant=%s", polluant)

    def lire(donnees: AtmoData) -> int | None:
        return donnees.aujourdhui.sous_indices.get(polluant) if donnees.aujourdhui else None

    LOGGER.debug("_sous_indice() retourne le lecteur de sous-indice")
    return lire


DESCRIPTIONS: tuple[AtmoSensorDescription, ...] = (
    AtmoSensorDescription(
        key="indice_atmo",
        translation_key="indice_atmo",
        code=lambda d: d.aujourdhui.code_qual if d.aujourdhui else None,
        qualificatifs=QUALIFICATIFS_ATMO,
        attributs=lambda d: _attributs_indice(d.aujourdhui),
    ),
    AtmoSensorDescription(
        key="indice_atmo_demain",
        translation_key="indice_atmo_demain",
        code=lambda d: d.demain.code_qual if d.demain else None,
        qualificatifs=QUALIFICATIFS_ATMO,
        attributs=lambda d: _attributs_indice(d.demain),
    ),
    *(
        AtmoSensorDescription(
            key=f"sous_indice_{p}",
            translation_key=f"sous_indice_{p}",
            code=_sous_indice(p),
            qualificatifs=QUALIFICATIFS_ATMO,
        )
        for p in POLLUANTS
    ),
    AtmoSensorDescription(
        key="indice_pollen",
        translation_key="indice_pollen",
        code=lambda d: d.pollen.code_qual if d.pollen else None,
        qualificatifs=QUALIFICATIFS_POLLEN,
        attributs=_attributs_pollen,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AtmoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crée les capteurs de la zone suivie."""
    LOGGER.debug("async_setup_entry() (capteurs) appelé")
    coordinateur = entry.runtime_data
    async_add_entities(AtmoSensor(coordinateur, description) for description in DESCRIPTIONS)
    LOGGER.debug("async_setup_entry() (capteurs) retourne | %s capteur(s)", len(DESCRIPTIONS))


class AtmoSensor(CoordinatorEntity[AtmoCoordinator], SensorEntity):
    """Indice qualitatif (énumération traduite) ; le code brut est en attribut."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    entity_description: AtmoSensorDescription

    def __init__(self, coordinator: AtmoCoordinator, description: AtmoSensorDescription) -> None:
        LOGGER.debug("AtmoSensor.__init__() appelé | zone=%s", coordinator.code_zone)
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_options = list(description.qualificatifs.values())
        self._attr_unique_id = f"{coordinator.code_zone}_{description.key}"
        libelle = coordinator.config_entry.title if coordinator.config_entry else coordinator.code_zone
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.code_zone)},
            name=f"Qualité de l'air {libelle}",
            manufacturer="Atmo France",
            model="Indices ATMO et pollinique",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.atmo-france.org",
        )
        LOGGER.debug("AtmoSensor.__init__() retourne")

    @property
    def native_value(self) -> str | None:
        """Clé du qualificatif ; None si l'indice n'est pas (encore) diffusé."""
        LOGGER.debug("native_value() appelé")
        if self.coordinator.data is None:
            LOGGER.debug("native_value() retourne None (pas de données)")
            return None
        code = self.entity_description.code(self.coordinator.data)
        if code is None:
            LOGGER.debug("native_value() retourne None (indice absent)")
            return None
        LOGGER.debug("native_value() retourne le qualificatif")
        return self.entity_description.qualificatifs.get(code)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        LOGGER.debug("extra_state_attributes() appelé")
        if self.coordinator.data is None:
            LOGGER.debug("extra_state_attributes() retourne un dictionnaire vide")
            return {}
        LOGGER.debug("extra_state_attributes() retourne les attributs")
        return self.entity_description.attributs(self.coordinator.data)
