"""Sources simulées, pour essayer Hervé sans matériel."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from .base import Energie, EvenementAlarme, SourceAlarme, SourceChauffage, SourceElectricite, Thermostat


class ElectriciteDemo(SourceElectricite):
    def __init__(self, fuseau):
        self.fuseau = fuseau
        rnd = random.Random(42)
        auj = datetime.now(fuseau).date()
        self._jours = {auj - timedelta(days=i): round(rnd.uniform(9, 26), 2) for i in range(1, 40)}

    async def energie(self) -> Energie:
        return Energie(jours=dict(self._jours), reference=datetime.now(self.fuseau).date())


class AlarmeDemo(SourceAlarme):
    def __init__(self, fuseau):
        super().__init__()
        self.fuseau = fuseau
        self._etat = "disarmed"
        maintenant = datetime.now(fuseau)
        self._hist = [EvenementAlarme(maintenant - timedelta(hours=9), "OP", "Alarme désarmée")]
        self._vue = maintenant

    @property
    def etat(self) -> str:
        return self._etat

    @property
    def derniere_nouvelle(self):
        return datetime.now(self.fuseau)

    def historique(self, n: int = 10):
        return list(reversed(self._hist[-n:]))

    async def simuler(self, code: str, texte: str, etat: str | None = None, gravite: str = "info") -> None:
        if etat:
            self._etat = etat
        ev = EvenementAlarme(datetime.now(self.fuseau), code, texte, gravite)
        self._hist.append(ev)
        await self._publier(ev)


class ChauffageDemo(SourceChauffage):
    def __init__(self):
        self._th = {
            "t6-salon": Thermostat("t6-salon", "Salon", 19.5, 20.0, "heat", ["off", "heat"], True, humidite=48),
        }

    async def thermostats(self) -> list[Thermostat]:
        for t in self._th.values():
            cible = t.consigne if t.mode != "off" else 14.0
            t.temperature = round(t.temperature + (cible - t.temperature) * 0.2, 1)
            t.en_chauffe = t.mode == "heat" and t.temperature < t.consigne
        return list(self._th.values())

    async def regler_consigne(self, tid: str, consigne: float) -> None:
        self._th[tid].consigne = consigne

    async def regler_mode(self, tid: str, mode: str) -> None:
        self._th[tid].mode = mode
