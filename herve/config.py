"""Chargement de la configuration (YAML + variables d'environnement)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


class ConfigError(ValueError):
    pass


def _substituer(valeur):
    """Remplace récursivement ${VAR} par la variable d'environnement."""
    if isinstance(valeur, str):
        complet = _VAR.fullmatch(valeur.strip())
        if complet:
            return os.environ.get(complet.group(1)) or None
        return _VAR.sub(lambda m: os.environ.get(m.group(1), ""), valeur)
    if isinstance(valeur, list):
        return [_substituer(v) for v in valeur]
    if isinstance(valeur, dict):
        return {k: _substituer(v) for k, v in valeur.items()}
    return valeur


@dataclass
class ElectriciteConf:
    source: str = "demo"
    prm: str | None = None
    token: str | None = None
    prix_kwh: float = 0.0
    seuil_journalier_kwh: float | None = None
    url_api: str = "https://conso.boris.sh/api"
    type_api: str = "consommation_quotidienne"


@dataclass
class AlarmeConf:
    source: str = "demo"
    port: int = 12128
    compte: str = "AAA"
    cle: str | None = None
    silence_max_min: int | None = 30


@dataclass
class ChauffageConf:
    source: str = "demo"
    cle_api: str | None = None
    secret_api: str | None = None
    url_retour: str = "https://localhost/herve"
    maintien: str = "TemporaryHold"


@dataclass
class Config:
    maison: str
    fuseau: ZoneInfo
    dossier_donnees: Path
    telegram_token: str | None
    administrateurs: list[int]
    electricite: ElectriciteConf = field(default_factory=ElectriciteConf)
    alarme: AlarmeConf = field(default_factory=AlarmeConf)
    chauffage: ChauffageConf = field(default_factory=ChauffageConf)
    intervalle_s: int = 300
    hors_gel: float | None = 10.0
    rapport_quotidien: time | None = None


def _source(section: dict, nom: str, valides: tuple[str, ...]) -> str:
    s = section.get("source", "demo")
    if s not in valides:
        raise ConfigError(f"{nom}.source doit valoir {' ou '.join(valides)} (reçu : {s})")
    return s


def charger_dict(brut: dict) -> Config:
    d = _substituer(brut or {})
    tg = d.get("telegram") or {}
    el = d.get("electricite") or {}
    al = d.get("alarme") or {}
    ch = d.get("chauffage") or {}
    su = d.get("surveillance") or {}
    fuseau = ZoneInfo(d.get("fuseau_horaire", "Europe/Paris"))

    rapport = None
    if d.get("rapport_quotidien"):
        try:
            h, m = str(d["rapport_quotidien"]).split(":")
            rapport = time(int(h), int(m), tzinfo=fuseau)
        except ValueError as e:
            raise ConfigError("rapport_quotidien doit être au format HH:MM") from e

    admins_brut = tg.get("administrateurs") or []
    if isinstance(admins_brut, (str, int)):  # ex. ${TELEGRAM_CHAT_IDS} = "123,456"
        admins_brut = [a for a in str(admins_brut).split(",") if a.strip()]
    try:
        admins = [int(a) for a in admins_brut]
    except (TypeError, ValueError) as e:
        raise ConfigError("telegram.administrateurs : identifiants numériques attendus") from e

    elec = ElectriciteConf(
        source=_source(el, "electricite", ("enedis", "demo")),
        prm=str(el["prm"]) if el.get("prm") else None,
        token=el.get("token"),
        prix_kwh=float(el.get("prix_kwh") or 0),
        seuil_journalier_kwh=float(el["seuil_journalier_kwh"]) if el.get("seuil_journalier_kwh") else None,
        url_api=(el.get("url_api") or ElectriciteConf.url_api).rstrip("/"),
        type_api=el.get("type_api") or ElectriciteConf.type_api,
    )
    if elec.source == "enedis":
        if not (elec.prm and len(elec.prm) == 14 and elec.prm.isdigit()):
            raise ConfigError("electricite.prm : 14 chiffres attendus")
        if not elec.token:
            raise ConfigError("electricite.token manquant (variable ENEDIS_TOKEN ?)")

    alarme = AlarmeConf(
        source=_source(al, "alarme", ("ajax_sia", "demo")),
        port=int(al.get("port", 12128)),
        compte=str(al.get("compte", "AAA")).upper(),
        cle=al.get("cle"),
        silence_max_min=int(al["silence_max_min"]) if al.get("silence_max_min") else None,
    )
    if alarme.cle and len(alarme.cle) not in (16, 24, 32):
        raise ConfigError("alarme.cle : 16, 24 ou 32 caractères attendus")
    if not re.fullmatch(r"[0-9A-F]{3,16}", alarme.compte):
        raise ConfigError("alarme.compte : 3 à 16 caractères hexadécimaux (0-9, A-F)")

    chauffage = ChauffageConf(
        source=_source(ch, "chauffage", ("resideo", "demo")),
        cle_api=ch.get("cle_api"),
        secret_api=ch.get("secret_api"),
        url_retour=ch.get("url_retour") or ChauffageConf.url_retour,
        maintien=ch.get("maintien") or ChauffageConf.maintien,
    )
    if chauffage.source == "resideo" and not (chauffage.cle_api and chauffage.secret_api):
        raise ConfigError("chauffage : cle_api et secret_api Resideo requis")

    return Config(
        maison=d.get("maison", "Montcuit"),
        fuseau=fuseau,
        dossier_donnees=Path(d.get("dossier_donnees", "./data")),
        telegram_token=tg.get("token"),
        administrateurs=admins,
        electricite=elec,
        alarme=alarme,
        chauffage=chauffage,
        intervalle_s=int(su.get("intervalle_s", 300)),
        hors_gel=float(su["temperature_hors_gel"]) if su.get("temperature_hors_gel") is not None else None,
        rapport_quotidien=rapport,
    )


def charger(chemin: str | Path) -> Config:
    chemin = Path(chemin)
    if not chemin.exists():
        raise ConfigError(f"Fichier de configuration introuvable : {chemin}")
    with chemin.open(encoding="utf-8") as f:
        return charger_dict(yaml.safe_load(f))
