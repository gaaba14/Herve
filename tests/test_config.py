import pytest

from herve.config import ConfigError, charger_dict

BASE = {"telegram": {"token": "${TG}", "administrateurs": ["42"]}}


def test_substitution_et_defauts(monkeypatch):
    monkeypatch.setenv("TG", "secret")
    cfg = charger_dict({**BASE, "rapport_quotidien": "09:30"})
    assert cfg.telegram_token == "secret"
    assert cfg.administrateurs == [42]
    assert cfg.electricite.source == "demo"
    assert (cfg.rapport_quotidien.hour, cfg.rapport_quotidien.minute) == (9, 30)


def test_variable_absente_donne_none(monkeypatch):
    monkeypatch.delenv("TG", raising=False)
    assert charger_dict(BASE).telegram_token is None


@pytest.mark.parametrize("section,erreur", [
    ({"electricite": {"source": "enedis", "prm": "123", "token": "t"}}, "prm"),
    ({"electricite": {"source": "enedis", "prm": "12345678901234"}}, "token"),
    ({"alarme": {"source": "ajax_sia", "cle": "trop-courte"}}, "cle"),
    ({"alarme": {"source": "ajax_sia", "compte": "XYZ"}}, "compte"),
    ({"chauffage": {"source": "resideo"}}, "cle_api"),
    ({"chauffage": {"source": "nest"}}, "source"),
])
def test_validation(section, erreur):
    with pytest.raises(ConfigError, match=erreur):
        charger_dict({**BASE, **section})


def test_config_complete_valide():
    cfg = charger_dict({
        **BASE,
        "electricite": {"source": "enedis", "prm": "12345678901234", "token": "t"},
        "alarme": {"source": "ajax_sia", "compte": "a1b2", "cle": "0123456789abcdef"},
        "chauffage": {"source": "resideo", "cle_api": "k", "secret_api": "s"},
    })
    assert cfg.alarme.compte == "A1B2"
    assert cfg.chauffage.maintien == "TemporaryHold"
