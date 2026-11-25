from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from herve.bot import Herve
from herve.sources import creer_sources
from herve.utilisateurs import INVITE, MEMBRE, Registre


@pytest.fixture
def herve(cfg, tmp_path):
    h = Herve(cfg, creer_sources(cfg), Registre(tmp_path / "u.json", [1]))
    h.app = SimpleNamespace(bot=MagicMock(send_message=AsyncMock()))
    return h


def maj(uid, texte="/x", nom="Alice"):
    msg = MagicMock(reply_text=AsyncMock())
    user = SimpleNamespace(id=uid, full_name=nom, first_name=nom, username=None)
    return SimpleNamespace(effective_user=user, effective_message=msg, callback_query=None), msg


def ctx(*args, bot=None):
    return SimpleNamespace(args=list(args), bot=bot or MagicMock(send_message=AsyncMock()))


def texte(msg):
    return msg.reply_text.call_args.args[0]


async def test_inconnu_declenche_demande_aux_admins(herve):
    u, msg = maj(99)
    c = ctx()
    await herve._garde(INVITE, herve.conso)(u, c)
    assert "honneur de vous connaître" in texte(msg)
    assert 99 in herve.registre.demandes
    dest = c.bot.send_message.call_args
    assert dest.args[0] == 1 and "demande l'accès" in dest.args[1]


async def test_invite_ne_peut_pas_regler_le_chauffage(herve):
    herve.registre.autoriser(5, INVITE, "Bob")
    u, msg = maj(5)
    await herve._garde(MEMBRE, herve.consigne)(u, ctx("21"))
    assert "dépasse" in texte(msg)


async def test_consigne_par_membre(herve):
    herve.registre.autoriser(5, MEMBRE, "Bob")
    u, msg = maj(5)
    await herve._garde(MEMBRE, herve.consigne)(u, ctx("20,5"))
    assert "20,5 °C" in texte(msg)
    (t,) = await herve.sources.chauffage.thermostats()
    assert t.consigne == 20.5
    await herve._garde(MEMBRE, herve.consigne)(u, ctx("99"))
    assert (await herve.sources.chauffage.thermostats())[0].consigne == 30  # borné


async def test_conso_et_rapport(herve):
    u, msg = maj(1)
    await herve.conso(u, ctx())
    assert "Hier" in texte(msg) and "kWh" in texte(msg) and "€" in texte(msg)
    await herve.rapport(u, ctx())
    assert "compte rendu" in texte(msg) and "alarme" in texte(msg)


async def test_intrusion_previent_tout_le_monde_meme_en_silencieux(herve):
    herve.registre.autoriser(5, INVITE, "Bob")
    herve.registre.notifications(5, False)
    await herve.sources.alarme.simuler("BA", "INTRUSION détectée", "triggered", "urgence")
    envois = herve.app.bot.send_message.call_args_list
    assert sorted(c.args[0] for c in envois) == [1, 5]
    assert "INTRUSION" in envois[0].args[1]


async def test_armement_respecte_le_silence(herve):
    herve.registre.autoriser(5, INVITE, "Bob")
    herve.registre.notifications(5, False)
    await herve.sources.alarme.simuler("CL", "Alarme armée", "armed_away")
    assert [c.args[0] for c in herve.app.bot.send_message.call_args_list] == [1]


def test_application_se_construit(herve):
    app = herve.application()
    assert app.handlers[0]
