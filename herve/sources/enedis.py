"""Consommation du Linky via l'API Enedis, au travers de la passerelle conso.boris.sh.

Les données arrivent une fois par jour (J+1, vers 8 h). Hervé interroge donc
l'API au plus une fois par heure tant que la veille manque, puis plus du tout
jusqu'au lendemain : c'est ce que demande l'opérateur du service.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

import httpx

from ..config import ElectriciteConf
from .base import Energie, SourceElectricite, SourceError

log = logging.getLogger(__name__)

RE_DATE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
CLES_VALEUR = ("value", "valeur")
CLES_UNITE = ("unit", "unite", "unité")


def _date_de(point: dict) -> date | None:
    for cle, v in point.items():
        if isinstance(v, str) and ("date" in cle.lower() or "horodatage" in cle.lower()):
            m = RE_DATE.search(v)
            if m:
                return date(int(m[1]), int(m[2]), int(m[3]))
    return None


def _unite(data) -> str | None:
    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() in CLES_UNITE and isinstance(v, str):
                return v
        for v in data.values():
            u = _unite(v)
            if u:
                return u
    elif isinstance(data, list):
        for v in data:
            u = _unite(v)
            if u:
                return u
    return None


def _points(data):
    """Parcourt la réponse et renvoie tous les {date, valeur} rencontrés."""
    if isinstance(data, dict):
        cle_v = next((k for k in data if k.lower() in CLES_VALEUR), None)
        if cle_v is not None:
            j = _date_de(data)
            try:
                v = float(data[cle_v])
            except (TypeError, ValueError):
                v = None
            if j is not None and v is not None:
                yield j, v
                return
        for v in data.values():
            yield from _points(v)
    elif isinstance(data, list):
        for v in data:
            yield from _points(v)


def analyser(data) -> dict[date, float]:
    """Convertit une réponse Enedis (ancien ou nouveau format) en kWh par jour."""
    unite = (_unite(data) or "Wh").strip().lower()
    facteur = 1.0 if unite == "kwh" else 0.001
    return {j: round(v * facteur, 3) for j, v in _points(data)}


class EnedisConso(SourceElectricite):
    def __init__(self, cfg: ElectriciteConf, fuseau, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self.fuseau = fuseau
        self.client = client or httpx.AsyncClient(
            timeout=30, headers={"User-Agent": "herve-majordome/0.1"})
        self._cache: Energie | None = None
        self._derniere_tentative: datetime | None = None

    async def fermer(self) -> None:
        await self.client.aclose()

    def _a_jour(self, maintenant: datetime) -> bool:
        if self._cache is None:
            return False
        hier = maintenant.date() - timedelta(days=1)
        if self._cache.reference == maintenant.date() and hier in self._cache.jours:
            return True  # la veille est connue : rien de neuf avant demain
        # Sinon, on ne retente pas plus d'une fois par heure
        return self._derniere_tentative is not None and maintenant - self._derniere_tentative < timedelta(hours=1)

    async def energie(self) -> Energie:
        maintenant = datetime.now(self.fuseau)
        if self._a_jour(maintenant):
            return self._cache
        aujourdhui = maintenant.date()
        debut = min(aujourdhui.replace(day=1), aujourdhui - timedelta(days=8))
        self._derniere_tentative = maintenant
        try:
            r = await self.client.get(
                f"{self.cfg.url_api}/{self.cfg.type_api}",
                params={"prm": self.cfg.prm, "start": debut.isoformat(), "end": aujourdhui.isoformat()},
                headers={"Authorization": f"Bearer {self.cfg.token}"},
            )
        except httpx.HTTPError as e:
            if self._cache:
                return self._cache
            raise SourceError(f"Enedis injoignable : {e}") from e
        if r.status_code >= 400:
            detail = r.text[:200]
            log.warning("Enedis a répondu %s : %s", r.status_code, detail)
            if self._cache:
                return self._cache
            if r.status_code == 404 and "no_data_found" in detail:
                raise SourceError("Enedis n'a aucune donnée : la collecte doit être activée dans l'espace client Enedis")
            raise SourceError(f"Enedis a répondu {r.status_code}")
        jours = analyser(r.json())
        if self._cache:  # conserve les jours déjà connus
            jours = {**self._cache.jours, **jours}
        self._cache = Energie(jours=jours, reference=aujourdhui)
        return self._cache
