from datetime import date, datetime, timedelta

import httpx

from herve.config import ElectriciteConf
from herve.sources.enedis import EnedisConso, analyser
from tests.conftest import PARIS

ANCIEN = {
    "usage_point_id": "12345678901234",
    "reading_type": {"unit": "Wh", "measurement_kind": "energy"},
    "interval_reading": [{"value": "12500", "date": "2026-11-23"}, {"value": "9800", "date": "2026-11-24"}],
}
# Forme plausible de la nouvelle API « mesure synchrone » (champs en français)
NOUVEAU = {"meter_reading": {"grandeur": {"unite": "Wh", "points": [
    {"valeur": 7000, "dateDebut": "2026-11-22T00:00:00+01:00"},
    {"valeur": "abc", "dateDebut": "2026-11-21"},
]}}}


def test_analyser_ancien_format():
    assert analyser(ANCIEN) == {date(2026, 11, 23): 12.5, date(2026, 11, 24): 9.8}


def test_analyser_nouveau_format_et_kwh():
    assert analyser(NOUVEAU) == {date(2026, 11, 22): 7.0}
    assert analyser({"unit": "kWh", "data": [{"value": 3, "date": "2026-01-01"}]}) == {date(2026, 1, 1): 3.0}


def _source(handler):
    cfg = ElectriciteConf(source="enedis", prm="12345678901234", token="jeton")
    return EnedisConso(cfg, PARIS, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_appel_et_cache():
    hier = datetime.now(PARIS).date() - timedelta(days=1)
    appels = []

    def handler(req: httpx.Request):
        appels.append(req)
        return httpx.Response(200, json={"reading_type": {"unit": "Wh"},
                                         "interval_reading": [{"value": "15000", "date": hier.isoformat()}]})

    src = _source(handler)
    e = await src.energie()
    assert e.jour(hier) == 15.0
    req = appels[0]
    assert req.url.path == "/api/consommation_quotidienne"
    assert req.url.params["prm"] == "12345678901234"
    assert req.headers["Authorization"] == "Bearer jeton"
    await src.energie()
    assert len(appels) == 1  # la veille est connue : pas de nouvel appel


async def test_erreur_sans_donnees():
    src = _source(lambda r: httpx.Response(404, json={"error": {"error": "no_data_found"}}))
    try:
        await src.energie()
    except Exception as e:
        assert "collecte" in str(e)
    else:
        raise AssertionError("SourceError attendue")
