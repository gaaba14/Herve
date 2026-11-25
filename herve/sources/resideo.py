"""Thermostat Resideo / Honeywell Home T6 (API officielle « Lyric »).

L'accès passe par OAuth2 : une autorisation unique (python -m herve.resideo_auth)
fournit un jeton de rafraîchissement, conservé dans le dossier de données.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from ..config import ChauffageConf
from .base import SourceChauffage, SourceError, Thermostat

log = logging.getLogger(__name__)

URL_BASE = "https://api.honeywellhome.com"
URL_AUTORISATION = f"{URL_BASE}/oauth2/authorize"
URL_JETON = f"{URL_BASE}/oauth2/token"
URL_API = f"{URL_BASE}/v2"
DUREE_CACHE_S = 30

# Modes Resideo <-> modes internes
MODES = {"Heat": "heat", "Off": "off", "Cool": "cool", "Auto": "auto"}
MODES_INV = {v: k for k, v in MODES.items()}


def url_autorisation(cfg: ChauffageConf) -> str:
    return URL_AUTORISATION + "?" + urlencode({
        "response_type": "code", "client_id": cfg.cle_api,
        "redirect_uri": cfg.url_retour, "appSelect": "1",
    })


class Jetons:
    """Jetons OAuth persistés sur disque (le jeton de rafraîchissement peut changer)."""

    def __init__(self, fichier: Path):
        self.fichier = Path(fichier)
        self.data: dict = json.loads(self.fichier.read_text()) if self.fichier.exists() else {}

    def sauver(self, reponse: dict) -> None:
        self.data["access_token"] = reponse["access_token"]
        if reponse.get("refresh_token"):
            self.data["refresh_token"] = reponse["refresh_token"]
        self.data["expire_a"] = time.time() + int(reponse.get("expires_in", 1799)) - 60
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.fichier.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.fichier)

    @property
    def valide(self) -> bool:
        return bool(self.data.get("access_token")) and time.time() < self.data.get("expire_a", 0)


async def demander_jeton(client: httpx.AsyncClient, cfg: ChauffageConf, **form) -> dict:
    r = await client.post(
        URL_JETON, data={**form, "client_id": cfg.cle_api, "client_secret": cfg.secret_api},
        auth=(cfg.cle_api, cfg.secret_api))
    if r.status_code >= 400:
        raise SourceError(f"Resideo a refusé le jeton ({r.status_code}) : {r.text[:200]}")
    return r.json()


def _nombre(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class ResideoT6(SourceChauffage):
    def __init__(self, cfg: ChauffageConf, dossier: Path, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self.jetons = Jetons(Path(dossier) / "resideo_jetons.json")
        self.client = client or httpx.AsyncClient(timeout=20)
        self._verrou = asyncio.Lock()
        self._cache: tuple[float, list[Thermostat], dict] | None = None

    async def fermer(self) -> None:
        await self.client.aclose()

    async def _jeton(self) -> str:
        async with self._verrou:
            if not self.jetons.valide:
                rt = self.jetons.data.get("refresh_token")
                if not rt:
                    raise SourceError("Resideo n'est pas encore autorisé : lancez python -m herve.resideo_auth")
                self.jetons.sauver(await demander_jeton(
                    self.client, self.cfg, grant_type="refresh_token", refresh_token=rt))
            return self.jetons.data["access_token"]

    async def _requete(self, methode: str, chemin: str, params: dict | None = None, json_=None):
        for tentative in range(2):
            try:
                r = await self.client.request(
                    methode, URL_API + chemin, params={"apikey": self.cfg.cle_api, **(params or {})},
                    json=json_, headers={"Authorization": f"Bearer {await self._jeton()}"})
            except httpx.HTTPError as e:
                raise SourceError(f"Resideo injoignable : {e}") from e
            if r.status_code == 401 and tentative == 0:
                self.jetons.data["expire_a"] = 0  # jeton expiré côté serveur : on le renouvelle
                continue
            if r.status_code >= 400:
                raise SourceError(f"Resideo a répondu {r.status_code} : {r.text[:200]}")
            return r.json() if r.content else None
        raise SourceError("Resideo refuse l'authentification")

    async def _lire(self) -> tuple[list[Thermostat], dict]:
        if self._cache and time.monotonic() - self._cache[0] < DUREE_CACHE_S:
            return self._cache[1], self._cache[2]
        lieux = await self._requete("GET", "/locations")
        liste, bruts = [], {}
        for lieu in lieux or []:
            for d in lieu.get("devices", []):
                if d.get("deviceClass", "Thermostat") != "Thermostat":
                    continue
                cv = d.get("changeableValues") or {}
                bruts[d["deviceID"]] = {**d, "locationID": lieu.get("locationID")}
                temp = _nombre(d.get("indoorTemperature"))
                if d.get("units") == "Fahrenheit" and temp is not None:
                    temp = round((temp - 32) / 1.8, 1)
                liste.append(Thermostat(
                    id=d["deviceID"],
                    nom=d.get("userDefinedDeviceName") or d.get("name") or d["deviceID"],
                    temperature=temp,
                    consigne=_nombre(cv.get("heatSetpoint")),
                    mode=MODES.get(cv.get("mode"), (cv.get("mode") or "").lower() or None),
                    modes=[MODES.get(m, m.lower()) for m in d.get("allowedModes", [])],
                    en_chauffe=(d.get("operationStatus") or {}).get("mode") == "Heat",
                    consigne_min=_nombre(d.get("minHeatSetpoint")) or 5.0,
                    consigne_max=_nombre(d.get("maxHeatSetpoint")) or 30.0,
                    humidite=_nombre(d.get("indoorHumidity")),
                ))
        self._cache = (time.monotonic(), liste, bruts)
        return liste, bruts

    async def thermostats(self) -> list[Thermostat]:
        return (await self._lire())[0]

    async def _modifier(self, tid: str, **changements) -> None:
        _, bruts = await self._lire()
        d = bruts.get(tid)
        if d is None:
            raise SourceError("Thermostat inconnu")
        cv = d.get("changeableValues") or {}
        corps = {
            "mode": cv.get("mode", "Heat"),
            "heatSetpoint": cv.get("heatSetpoint"),
            "coolSetpoint": cv.get("coolSetpoint"),
            "thermostatSetpointStatus": self.cfg.maintien,
            **changements,
        }
        await self._requete("POST", f"/devices/thermostats/{tid}",
                            params={"locationId": d["locationID"]}, json_=corps)
        self._cache = None

    async def regler_consigne(self, tid: str, consigne: float) -> None:
        await self._modifier(tid, heatSetpoint=consigne)

    async def regler_mode(self, tid: str, mode: str) -> None:
        if mode not in MODES_INV:
            raise SourceError(f"Mode inconnu : {mode}")
        await self._modifier(tid, mode=MODES_INV[mode])
