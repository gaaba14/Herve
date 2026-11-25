"""Fabrique des sources selon la configuration."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Config
from .base import (ALARME_ETATS, Energie, EvenementAlarme, SourceAlarme, SourceChauffage,
                   SourceElectricite, SourceError, Thermostat)


@dataclass
class Sources:
    electricite: SourceElectricite
    alarme: SourceAlarme
    chauffage: SourceChauffage

    async def demarrer(self) -> None:
        await self.alarme.demarrer()

    async def fermer(self) -> None:
        for s in (self.electricite, self.alarme, self.chauffage):
            await s.fermer()


def creer_sources(cfg: Config) -> Sources:
    from . import demo

    if cfg.electricite.source == "enedis":
        from .enedis import EnedisConso
        elec = EnedisConso(cfg.electricite, cfg.fuseau)
    else:
        elec = demo.ElectriciteDemo(cfg.fuseau)

    if cfg.alarme.source == "ajax_sia":
        from .ajax_sia import AjaxSIA
        alarme = AjaxSIA(cfg.alarme, cfg.dossier_donnees, cfg.fuseau)
    else:
        alarme = demo.AlarmeDemo(cfg.fuseau)

    if cfg.chauffage.source == "resideo":
        from .resideo import ResideoT6
        chauffage = ResideoT6(cfg.chauffage, cfg.dossier_donnees)
    else:
        chauffage = demo.ChauffageDemo()

    return Sources(elec, alarme, chauffage)


__all__ = ["ALARME_ETATS", "Energie", "EvenementAlarme", "SourceAlarme", "SourceChauffage",
           "SourceElectricite", "SourceError", "Sources", "Thermostat", "creer_sources"]
