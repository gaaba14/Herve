"""Veille d'Hervé : détecte ce qui mérite d'être signalé à la maisonnée."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape

from . import messages as M
from .config import Config
from .sources import EvenementAlarme, SourceError, Sources
from .utilisateurs import ADMIN, INVITE

log = logging.getLogger(__name__)

PANNES_AVANT_ALERTE = 3


@dataclass
class Alerte:
    texte: str
    destinataires: str = INVITE  # rôle minimal des destinataires
    urgent: bool = False  # envoyé à tous, même à ceux qui ont coupé les notifications


def alerte_alarme(ev: EvenementAlarme, maison: str) -> Alerte:
    if ev.gravite == "urgence":
        return Alerte(f"🚨🚨 <b>{escape(ev.texte).upper()}</b> à {escape(maison)} ! 🚨🚨\n"
                      f"{M.evenement(ev)}\nJe vous suggère de vérifier immédiatement.", INVITE, urgent=True)
    return Alerte(M.evenement(ev, avec_heure=False))


@dataclass
class Surveillant:
    cfg: Config
    sources: Sources
    _froid_alerte: set[str] = field(default_factory=set)
    _pannes_chauffage: int = 0
    _centrale_muette: bool = False

    async def verifier(self) -> list[Alerte]:
        return self._silence_centrale(datetime.now(self.cfg.fuseau)) + await self._chauffage()

    # --- chauffage ----------------------------------------------------------
    async def _chauffage(self) -> list[Alerte]:
        if self.cfg.hors_gel is None:
            return []
        try:
            ths = await self.sources.chauffage.thermostats()
        except SourceError as e:
            self._pannes_chauffage += 1
            log.warning("Thermostat illisible (%d) : %s", self._pannes_chauffage, e)
            if self._pannes_chauffage == PANNES_AVANT_ALERTE:
                return [Alerte(f"⚠️ Le thermostat ne me répond plus ({escape(str(e))}). "
                               "Je continue d'essayer.", ADMIN)]
            return []
        alertes = []
        if self._pannes_chauffage >= PANNES_AVANT_ALERTE:
            alertes.append(Alerte("✅ Le thermostat me répond de nouveau.", ADMIN))
        self._pannes_chauffage = 0
        seuil = self.cfg.hors_gel
        for t in ths:
            if t.temperature is None:
                continue
            if t.temperature < seuil and t.id not in self._froid_alerte:
                self._froid_alerte.add(t.id)
                alertes.append(Alerte(f"🥶 Il ne fait que <b>{M.nombre(t.temperature)} °C</b> "
                                      f"(« {escape(t.nom)} »). Le chauffage fonctionne-t-il ?"))
            elif t.temperature >= seuil + 1:
                self._froid_alerte.discard(t.id)
        return alertes

    # --- centrale d'alarme ------------------------------------------------
    def _silence_centrale(self, maintenant: datetime) -> list[Alerte]:
        limite = self.cfg.alarme.silence_max_min
        derniere = self.sources.alarme.derniere_nouvelle
        if not limite or self.cfg.alarme.source == "demo" or derniere is None:
            return []
        muette = maintenant - derniere > timedelta(minutes=limite)
        if muette and not self._centrale_muette:
            self._centrale_muette = True
            return [Alerte(f"📵 La centrale d'alarme ne m'a rien envoyé depuis le "
                           f"{derniere.strftime('%d/%m à %H:%M')}. Coupure d'Internet ou de courant "
                           f"à {escape(self.cfg.maison)} ?", INVITE)]
        if not muette and self._centrale_muette:
            self._centrale_muette = False
            return [Alerte("✅ La centrale d'alarme a repris contact.", INVITE)]
        return []

    # --- électricité (vérifiée une fois par jour) ---------------------------
    async def electricite(self) -> list[Alerte]:
        seuil = self.cfg.electricite.seuil_journalier_kwh
        if not seuil:
            return []
        try:
            e = await self.sources.electricite.energie()
        except SourceError:
            return []
        hier = datetime.now(self.cfg.fuseau).date() - timedelta(days=1)
        v = e.jour(hier)
        if v is not None and v > seuil:
            return [Alerte(f"⚡ Hier, la maison a consommé <b>{M.nombre(v)} kWh</b>, au-delà du seuil "
                           f"de {M.nombre(seuil, 0)} kWh. Un appareil serait-il resté allumé ?")]
        return []
