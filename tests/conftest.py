"""Configuration commune des tests."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer
from homeassistant.util import dt as dt_util

from .fausse_api import Etat, construire_app

pytest_plugins = ("pytest_homeassistant_custom_component",)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Active le chargement des intégrations personnalisées."""
    yield


@pytest.fixture(autouse=True)
def _socket_autorise(socket_enabled):
    """Autorise le serveur HTTP local des tests."""
    yield


@pytest.fixture
def etat() -> Etat:
    return Etat(aujourdhui=dt_util.now().date())


@pytest.fixture
async def serveur(etat: Etat, monkeypatch: pytest.MonkeyPatch):
    """Faux Atmo Data ; l'intégration y est redirigée."""
    client = TestClient(TestServer(construire_app(etat)))
    await client.start_server()
    monkeypatch.setattr("custom_components.atmo_qualite_air.api.BASE_URL", str(client.make_url("/")))
    yield client
    await client.close()
