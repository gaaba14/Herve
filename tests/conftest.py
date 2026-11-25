import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from herve.config import charger_dict  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture
def cfg(tmp_path):
    return charger_dict({
        "maison": "Montcuit",
        "dossier_donnees": str(tmp_path),
        "telegram": {"token": "x", "administrateurs": [1]},
        "electricite": {"source": "demo", "prix_kwh": 0.25, "seuil_journalier_kwh": 20},
        "alarme": {"source": "demo"},
        "chauffage": {"source": "demo"},
        "surveillance": {"temperature_hors_gel": 10},
    })
