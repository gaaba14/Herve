from datetime import datetime, timedelta

from herve.sources import Sources, creer_sources
from herve.sources.base import SourceChauffage, SourceError
from herve.surveillance import Surveillant
from tests.conftest import PARIS


async def test_hors_gel_une_seule_fois(cfg):
    s = creer_sources(cfg)
    (t,) = await s.chauffage.thermostats()
    t.temperature, t.mode = 6.0, "off"
    s.chauffage.thermostats = _fige([t])
    sv = Surveillant(cfg, s)
    alertes = await sv.verifier()
    assert len(alertes) == 1 and "6,0 °C" in alertes[0].texte
    assert await sv.verifier() == []


def _fige(liste):
    async def f():
        return liste
    return f


class Panne(SourceChauffage):
    async def thermostats(self):
        raise SourceError("hors ligne")

    async def regler_consigne(self, *a): ...

    async def regler_mode(self, *a): ...


async def test_panne_chauffage_signalee_aux_admins(cfg):
    s = creer_sources(cfg)
    sv = Surveillant(cfg, Sources(s.electricite, s.alarme, Panne()))
    resultats = [await sv.verifier() for _ in range(4)]
    assert [len(r) for r in resultats] == [0, 0, 1, 0]
    assert resultats[2][0].destinataires == "admin"


async def test_seuil_electricite(cfg):
    s = creer_sources(cfg)
    hier = datetime.now(PARIS).date() - timedelta(days=1)
    s.electricite._jours[hier] = 25.0
    (alerte,) = await Surveillant(cfg, s).electricite()
    assert "25,0 kWh" in alerte.texte
    s.electricite._jours[hier] = 12.0
    assert await Surveillant(cfg, s).electricite() == []


async def test_centrale_muette(cfg):
    cfg.alarme.source, cfg.alarme.silence_max_min = "ajax_sia", 30
    s = creer_sources(cfg)

    class Fausse:
        derniere_nouvelle = datetime.now(PARIS) - timedelta(hours=2)

    sv = Surveillant(cfg, Sources(s.electricite, Fausse(), s.chauffage))
    assert len(sv._silence_centrale(datetime.now(PARIS))) == 1
    assert sv._silence_centrale(datetime.now(PARIS)) == []
    Fausse.derniere_nouvelle = datetime.now(PARIS)
    assert "repris contact" in sv._silence_centrale(datetime.now(PARIS))[0].texte
