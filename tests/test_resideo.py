import json

import httpx

from herve.config import ChauffageConf
from herve.sources.resideo import Jetons, ResideoT6, url_autorisation

CFG = ChauffageConf(source="resideo", cle_api="CLE", secret_api="SECRET")
LIEUX = [{"locationID": 77, "devices": [{
    "deviceID": "LCC-00D02D", "deviceClass": "Thermostat", "userDefinedDeviceName": "Salon",
    "indoorTemperature": 18.5, "indoorHumidity": 45, "units": "Celsius",
    "allowedModes": ["Heat", "Off"], "minHeatSetpoint": 5, "maxHeatSetpoint": 30,
    "changeableValues": {"mode": "Heat", "heatSetpoint": 19, "coolSetpoint": 30,
                         "thermostatSetpointStatus": "NoHold"},
    "operationStatus": {"mode": "Heat"},
}]}]


def test_url_autorisation():
    u = url_autorisation(CFG)
    assert u.startswith("https://api.honeywellhome.com/oauth2/authorize?")
    assert "client_id=CLE" in u and "appSelect=1" in u


async def test_rafraichit_lit_et_modifie(tmp_path):
    Jetons(tmp_path / "resideo_jetons.json").sauver(
        {"access_token": "vieux", "refresh_token": "R1", "expires_in": 0})
    requetes = []

    def handler(req: httpx.Request):
        requetes.append(req)
        if req.url.path == "/oauth2/token":
            assert b"grant_type=refresh_token" in req.content and b"refresh_token=R1" in req.content
            assert req.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "neuf", "refresh_token": "R2", "expires_in": 1799})
        assert req.headers["Authorization"] == "Bearer neuf"
        assert req.url.params["apikey"] == "CLE"
        if req.method == "GET":
            return httpx.Response(200, json=LIEUX)
        return httpx.Response(200)

    src = ResideoT6(CFG, tmp_path, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    (t,) = await src.thermostats()
    assert (t.nom, t.temperature, t.consigne, t.mode, t.en_chauffe) == ("Salon", 18.5, 19.0, "heat", True)
    assert t.modes == ["heat", "off"]
    # le nouveau jeton de rafraîchissement est conservé
    assert json.loads((tmp_path / "resideo_jetons.json").read_text())["refresh_token"] == "R2"

    await src.regler_consigne(t.id, 20.5)
    post = requetes[-1]
    assert post.method == "POST" and post.url.path == "/v2/devices/thermostats/LCC-00D02D"
    assert post.url.params["locationId"] == "77"
    corps = json.loads(post.content)
    assert corps == {"mode": "Heat", "heatSetpoint": 20.5, "coolSetpoint": 30,
                     "thermostatSetpointStatus": "TemporaryHold"}

    await src.regler_mode(t.id, "off")
    assert json.loads(requetes[-1].content)["mode"] == "Off"


async def test_sans_autorisation(tmp_path):
    src = ResideoT6(CFG, tmp_path, httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    try:
        await src.thermostats()
    except Exception as e:
        assert "resideo_auth" in str(e)
    else:
        raise AssertionError
