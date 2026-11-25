"""Alarme Ajax : Hervé joue le rôle de « centre de télésurveillance » SIA DC-09.

La centrale Ajax envoie chaque événement (armement, désarmement, intrusion,
sabotage, coupure secteur, test périodique…) au serveur d'Hervé. Ajax ne
propose pas d'API publique de pilotage : l'armement se fait dans l'appli Ajax.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ..config import AlarmeConf
from .base import EvenementAlarme, SourceAlarme

log = logging.getLogger(__name__)

# code SIA -> (nouvel état ou None, gravité, texte en français)
CODES = {
    "CL": ("armed_away", "info", "Alarme armée"),
    "CQ": ("armed_away", "info", "Alarme armée à distance"),
    "CF": ("armed_away", "attention", "Alarme armée (certaines zones n'étaient pas prêtes)"),
    "CG": ("armed_home", "info", "Alarme partiellement armée"),
    "NL": ("armed_night", "info", "Mode nuit activé"),
    "OP": ("disarmed", "info", "Alarme désarmée"),
    "OQ": ("disarmed", "info", "Alarme désarmée à distance"),
    "OG": ("disarmed", "info", "Alarme partiellement désarmée"),
    "NP": ("disarmed", "info", "Mode nuit désactivé"),
    "BA": ("triggered", "urgence", "INTRUSION détectée"),
    "BV": ("triggered", "urgence", "Intrusion confirmée"),
    "PA": ("triggered", "urgence", "Bouton panique / demande d'assistance"),
    "HA": ("triggered", "urgence", "Alarme contrainte (agression)"),
    "FA": (None, "urgence", "INCENDIE / fumée détectée"),
    "GA": (None, "urgence", "Gaz détecté"),
    "WA": (None, "urgence", "Fuite d'eau détectée"),
    "KA": (None, "urgence", "Chaleur excessive détectée"),
    "MA": (None, "urgence", "Alerte médicale"),
    "TA": (None, "attention", "Sabotage d'un appareil"),
    "JA": (None, "attention", "Trop de codes erronés saisis"),
    "AT": (None, "attention", "Coupure de courant secteur sur la centrale"),
    "AR": (None, "info", "Courant secteur rétabli"),
    "YT": (None, "attention", "Batterie faible"),
    "YR": (None, "info", "Batterie rétablie"),
    "XT": (None, "attention", "Pile faible sur un détecteur"),
    "XR": (None, "info", "Pile d'un détecteur rétablie"),
    "YP": (None, "attention", "Problème d'alimentation"),
    "YQ": (None, "info", "Alimentation rétablie"),
    "BR": (None, "info", "Fin d'alarme intrusion"),
    "FR": (None, "info", "Fin d'alarme incendie"),
    "WR": (None, "info", "Fin d'alarme fuite d'eau"),
    "TR": (None, "info", "Fin de sabotage"),
    "BB": (None, "info", "Zone exclue de la surveillance"),
    "BU": (None, "info", "Zone réintégrée"),
}
SILENCIEUX = {"RP", "YK", "RX"}  # tests périodiques / liaison : mis à jour, pas de message


def traduire(code: str, description: str | None) -> tuple[str | None, str, str]:
    if code in CODES:
        return CODES[code]
    return None, "info", description or f"Événement {code}"


class AjaxSIA(SourceAlarme):
    TAILLE_HISTORIQUE = 50

    def __init__(self, cfg: AlarmeConf, dossier: Path, fuseau):
        super().__init__()
        self.cfg = cfg
        self.fuseau = fuseau
        self.fichier = Path(dossier) / "alarme.json"
        self._etat = "unknown"
        self._derniere_nouvelle: datetime | None = None
        self._historique: list[EvenementAlarme] = []
        self._client = None
        self._charger()

    # --- persistance ------------------------------------------------------
    def _charger(self) -> None:
        if not self.fichier.exists():
            return
        try:
            d = json.loads(self.fichier.read_text(encoding="utf-8"))
            self._etat = d.get("etat", "unknown")
            if d.get("derniere_nouvelle"):
                self._derniere_nouvelle = datetime.fromisoformat(d["derniere_nouvelle"])
            self._historique = [
                EvenementAlarme(datetime.fromisoformat(e["horodatage"]), e["code"], e["texte"],
                                e.get("gravite", "info"), e.get("zone"))
                for e in d.get("historique", [])
            ]
        except (ValueError, KeyError) as e:
            log.warning("État de l'alarme illisible, on repart de zéro : %s", e)

    def _sauver(self) -> None:
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        d = {
            "etat": self._etat,
            "derniere_nouvelle": self._derniere_nouvelle.isoformat() if self._derniere_nouvelle else None,
            "historique": [
                {"horodatage": e.horodatage.isoformat(), "code": e.code, "texte": e.texte,
                 "gravite": e.gravite, "zone": e.zone}
                for e in self._historique[-self.TAILLE_HISTORIQUE:]
            ],
        }
        tmp = self.fichier.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.fichier)

    # --- consultation -----------------------------------------------------
    @property
    def etat(self) -> str:
        return self._etat

    @property
    def derniere_nouvelle(self) -> datetime | None:
        return self._derniere_nouvelle

    def historique(self, n: int = 10) -> list[EvenementAlarme]:
        return list(reversed(self._historique[-n:]))

    # --- réception --------------------------------------------------------
    async def recevoir(self, code: str | None, description: str | None = None,
                       zone: str | None = None) -> EvenementAlarme | None:
        """Traite un événement reçu de la centrale (indépendant de la bibliothèque SIA)."""
        maintenant = datetime.now(self.fuseau)
        self._derniere_nouvelle = maintenant
        if not code or code in SILENCIEUX:
            self._sauver()
            return None
        nouvel_etat, gravite, texte = traduire(code, description)
        if nouvel_etat:
            self._etat = nouvel_etat
        ev = EvenementAlarme(maintenant, code, texte, gravite, zone)
        self._historique.append(ev)
        self._historique = self._historique[-self.TAILLE_HISTORIQUE:]
        self._sauver()
        await self._publier(ev)
        return ev

    async def _sur_evenement(self, event) -> None:
        try:
            desc = event.sia_code.description if event.sia_code else None
            zone = event.ri if event.ri and event.ri not in ("0", "00", "000") else None
            log.info("SIA reçu : code=%s zone=%s message=%s", event.code, zone, event.message)
            await self.recevoir(event.code, desc, zone)
        except Exception:  # ne jamais faire tomber le serveur SIA
            log.exception("Erreur au traitement d'un événement SIA")

    async def demarrer(self) -> None:
        from pysiaalarm import SIAAccount
        from pysiaalarm.aio import CommunicationsProtocol, SIAClient

        compte = SIAAccount(self.cfg.compte, self.cfg.cle)
        self._client = SIAClient("", self.cfg.port, [compte], self._sur_evenement,
                                 protocol=CommunicationsProtocol.TCP)
        await self._client.async_start()
        log.info("Écoute SIA sur le port %s (compte %s, chiffrement %s)",
                 self.cfg.port, self.cfg.compte, "oui" if self.cfg.cle else "NON")

    async def fermer(self) -> None:
        if self._client:
            await self._client.async_stop()
