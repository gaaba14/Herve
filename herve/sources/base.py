"""Interfaces communes des sources (électricité, alarme, chauffage)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime


class SourceError(RuntimeError):
    """Un service extérieur est injoignable ou a refusé la demande."""


# ---------------------------------------------------------------- électricité
@dataclass
class Energie:
    jours: dict[date, float] = field(default_factory=dict)  # kWh par jour (données Enedis, J-1 max)
    reference: date | None = None  # « aujourd'hui » au moment du relevé

    def jour(self, j: date) -> float | None:
        return self.jours.get(j)

    @property
    def dernier_jour(self) -> date | None:
        return max(self.jours) if self.jours else None

    def mois_en_cours(self) -> float | None:
        if not self.reference:
            return None
        valeurs = [v for j, v in self.jours.items()
                   if j.year == self.reference.year and j.month == self.reference.month]
        return round(sum(valeurs), 2) if valeurs else None

    def sept_jours(self) -> float | None:
        if not self.jours:
            return None
        fin = self.dernier_jour
        valeurs = [v for j, v in self.jours.items() if 0 <= (fin - j).days < 7]
        return round(sum(valeurs), 2)


class SourceElectricite(ABC):
    @abstractmethod
    async def energie(self) -> Energie: ...

    async def fermer(self) -> None:
        pass


# --------------------------------------------------------------------- alarme
ALARME_ETATS = {
    "disarmed": "désarmée",
    "armed_away": "armée",
    "armed_home": "partiellement armée",
    "armed_night": "armée (mode nuit)",
    "triggered": "DÉCLENCHÉE",
    "unknown": "dans un état inconnu (aucune nouvelle de la centrale)",
}


@dataclass
class EvenementAlarme:
    horodatage: datetime
    code: str
    texte: str
    gravite: str = "info"  # info, attention, urgence
    zone: str | None = None


Ecouteur = Callable[[EvenementAlarme], Awaitable[None]]


class SourceAlarme(ABC):
    def __init__(self) -> None:
        self._ecouteurs: list[Ecouteur] = []

    def ecouter(self, fn: Ecouteur) -> None:
        self._ecouteurs.append(fn)

    async def _publier(self, ev: EvenementAlarme) -> None:
        for fn in self._ecouteurs:
            await fn(ev)

    @property
    @abstractmethod
    def etat(self) -> str: ...

    @property
    @abstractmethod
    def derniere_nouvelle(self) -> datetime | None: ...

    @abstractmethod
    def historique(self, n: int = 10) -> list[EvenementAlarme]: ...

    async def demarrer(self) -> None:
        pass

    async def fermer(self) -> None:
        pass


# ------------------------------------------------------------------ chauffage
@dataclass
class Thermostat:
    id: str
    nom: str
    temperature: float | None
    consigne: float | None
    mode: str | None  # "heat", "off", "cool", "auto"
    modes: list[str] = field(default_factory=list)
    en_chauffe: bool | None = None
    pas: float = 0.5
    consigne_min: float = 5.0
    consigne_max: float = 30.0
    humidite: float | None = None


class SourceChauffage(ABC):
    @abstractmethod
    async def thermostats(self) -> list[Thermostat]: ...

    @abstractmethod
    async def regler_consigne(self, tid: str, consigne: float) -> None: ...

    @abstractmethod
    async def regler_mode(self, tid: str, mode: str) -> None: ...

    async def fermer(self) -> None:
        pass
