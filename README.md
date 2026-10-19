# Atmo Data (qualité de l'air)

Intégration Home Assistant qui suit l'**indice ATMO** de qualité de l'air
d'une commune française (aujourd'hui et demain), ses **sous-indices** par
polluant et l'**indice pollinique**, par défaut à **Strasbourg** (`67482`).

Les données proviennent de l'API [Atmo Data](https://admindata.atmo-france.org)
d'[Atmo France](https://www.atmo-france.org), qui regroupe les indices
diffusés par les associations agréées de surveillance de la qualité de l'air
(AASQA : ATMO Grand Est, Airparif, AtmoSud…). Un **compte gratuit** Atmo Data
est nécessaire.

## Fonctionnalités

- **Indice ATMO du jour** et **indice ATMO de demain** : Bon, Moyen, Dégradé,
  Mauvais, Très mauvais, Extrêmement mauvais (plus Absent et Événement),
  selon l'[indice ATMO en vigueur depuis 2021](https://www.atmo-france.org/article/lindice-atmo).
- **Sous-indices du jour** : NO₂, O₃, PM10, PM2,5 et SO₂, sur la même échelle.
- **Indice pollinique du jour**, avec l'alerte, les taxons responsables, et
  pour chaque taxon (ambroisie, armoise, aulne, bouleau, graminées, olivier)
  son sous-indice et sa concentration. Là où il n'est pas diffusé, le capteur
  reste « inconnu » sans gêner l'indice ATMO.
- Les capteurs sont des **énumérations traduites** : l'état est stable
  (`bon`, `moyen`, `degrade`…) pour les automatisations, et le code brut
  (`code`, 0 à 7), la couleur officielle (`couleur`), la date d'échéance, la
  date de diffusion et l'AASQA source sont en attributs.
- Mise à jour toutes les heures. Pour chaque jour, la **diffusion la plus
  récente** est retenue (une AASQA peut corriger sa prévision).
- **Jeton JWT renouvelé automatiquement** à son expiration. Si le compte est
  refusé (mot de passe changé), Home Assistant propose la
  **réauthentification** sans supprimer l'intégration.

## Installation

### HACS (recommandé)

1. Ajoutez ce dépôt dans HACS (« Dépôts personnalisés », catégorie
   « Intégration »).
2. Recherchez « Atmo Data (qualité de l'air) » et installez-la.
3. Redémarrez Home Assistant.

### Manuel

Copiez le dossier `custom_components/atmo_qualite_air` dans le dossier
`custom_components` de votre installation, puis redémarrez Home Assistant.

## Configuration

1. Créez un compte sur [admindata.atmo-france.org](https://admindata.atmo-france.org)
   (gratuit).
2. Ajoutez l'intégration « Atmo Data (qualité de l'air) ».
3. Saisissez l'identifiant et le mot de passe du compte, puis le territoire :
   - le **code INSEE** de la commune (5 caractères, `2A`/`2B` pour la Corse),
     prérempli avec `67482` (Strasbourg) ;
   - ou le **SIREN** d'une intercommunalité (9 chiffres).

   Attention : le code INSEE n'est pas le code postal. Il se trouve sur la
   fiche de la commune de l'[INSEE](https://www.insee.fr/fr/recherche/recherche-geographique).
4. L'intégration vérifie le compte et la présence d'indices récents pour le
   territoire, puis crée un appareil « Qualité de l'air <commune> ».

Plusieurs territoires peuvent être suivis avec le même compte : ajoutez une
entrée par territoire.

## Capteurs

| Capteur | État | Attributs principaux |
|---|---|---|
| Indice ATMO | qualificatif du jour | `code`, `libelle`, `couleur`, `date_echeance`, `date_diffusion`, `source`, `sous_indice_*` |
| Indice ATMO demain | qualificatif de demain | idem |
| Sous-indice NO₂, O₃, PM10, PM2,5, SO₂ | qualificatif du polluant (jour) | — |
| Indice pollinique | qualificatif du jour | `alerte`, `responsables`, un attribut par taxon, `concentration_<taxon>` |

L'indice de demain est diffusé en fin de matinée : avant cela, son capteur
est « inconnu ».

### Exemple d'automatisation

```yaml
automation:
  - alias: Alerte qualité de l'air dégradée
    triggers:
      - trigger: state
        entity_id: sensor.qualite_de_l_air_strasbourg_indice_atmo
        to:
          - mauvais
          - tres_mauvais
          - extremement_mauvais
    actions:
      - action: notify.notify
        data:
          message: >-
            Qualité de l'air {{ state_translated(trigger.entity_id) | lower }}
            aujourd'hui à Strasbourg.
```

## Développement

Socle qualité [Mathide-Team](https://github.com/Mathide-Team/.github/blob/main/SOCLE.md) :
PR vers `dev`, livraison par PR `dev` → `main`.

```bash
uvx yamllint==1.38.0 --strict -c .yamllint.yaml .
uv run --only-group lint ruff check .
uv run --only-group lint ruff format --check .
uv run -p 3.13 --only-group test pytest --cov
```

Les tests utilisent un faux serveur Atmo Data local (`tests/fausse_api.py`) :
aucune donnée ni aucun identifiant réel.

Publication : dater la section de `CHANGELOG.md`, puis pousser un tag
`vX.Y.Z` égal à la version de `manifest.json` ; la release HACS
(`atmo_qualite_air.zip`) est construite automatiquement.

## Licence

[MIT](LICENSE). Les données restent la propriété d'Atmo France et des AASQA,
sous leurs propres conditions d'utilisation.
