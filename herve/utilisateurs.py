"""Gestion des personnes autorisées à parler à Hervé."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# Rôles, du moins au plus privilégié
INVITE, MEMBRE, ADMIN = "invite", "membre", "admin"
ROLES = (INVITE, MEMBRE, ADMIN)
ROLES_LIBELLES = {INVITE: "invité (consultation)", MEMBRE: "membre (pilotage)", ADMIN: "administrateur"}


def role_suffisant(role: str, requis: str) -> bool:
    return ROLES.index(role) >= ROLES.index(requis)


@dataclass
class Utilisateur:
    id: int
    nom: str
    role: str = INVITE
    notifications: bool = True
    depuis: str = ""


class Registre:
    """Stockage JSON des utilisateurs et des demandes d'accès en attente."""

    def __init__(self, fichier: Path, administrateurs: list[int]):
        self.fichier = Path(fichier)
        self.admins_config = set(administrateurs)
        self.utilisateurs: dict[int, Utilisateur] = {}
        self.demandes: dict[int, str] = {}
        self._charger()
        for a in self.admins_config:
            u = self.utilisateurs.get(a)
            if u is None:
                self.utilisateurs[a] = Utilisateur(a, f"admin {a}", ADMIN, True, self._maintenant())
            else:
                u.role = ADMIN
        self.sauver()

    @staticmethod
    def _maintenant() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _charger(self) -> None:
        if not self.fichier.exists():
            return
        data = json.loads(self.fichier.read_text(encoding="utf-8"))
        for u in data.get("utilisateurs", []):
            self.utilisateurs[int(u["id"])] = Utilisateur(**u)
        self.demandes = {int(k): v for k, v in data.get("demandes", {}).items()}

    def sauver(self) -> None:
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "utilisateurs": [asdict(u) for u in self.utilisateurs.values()],
            "demandes": {str(k): v for k, v in self.demandes.items()},
        }
        fd, tmp = tempfile.mkstemp(dir=self.fichier.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.fichier)

    # --- consultation -----------------------------------------------------
    def get(self, uid: int) -> Utilisateur | None:
        return self.utilisateurs.get(uid)

    def autorise(self, uid: int, requis: str = INVITE) -> bool:
        u = self.get(uid)
        return u is not None and role_suffisant(u.role, requis)

    def admins(self) -> list[Utilisateur]:
        return [u for u in self.utilisateurs.values() if u.role == ADMIN]

    def a_notifier(self, requis: str = INVITE) -> list[Utilisateur]:
        return [u for u in self.utilisateurs.values() if u.notifications and role_suffisant(u.role, requis)]

    # --- modification -----------------------------------------------------
    def demander(self, uid: int, nom: str) -> bool:
        """Enregistre une demande d'accès. Renvoie False si déjà en attente."""
        if uid in self.demandes:
            return False
        self.demandes[uid] = nom
        self.sauver()
        return True

    def autoriser(self, uid: int, role: str = MEMBRE, nom: str | None = None) -> Utilisateur:
        if role not in ROLES:
            raise ValueError(f"Rôle inconnu : {role}")
        nom = nom or self.demandes.get(uid) or str(uid)
        self.demandes.pop(uid, None)
        u = self.utilisateurs.get(uid)
        if u:
            u.role = role
        else:
            u = self.utilisateurs[uid] = Utilisateur(uid, nom, role, True, self._maintenant())
        self.sauver()
        return u

    def refuser(self, uid: int) -> str | None:
        nom = self.demandes.pop(uid, None)
        self.sauver()
        return nom

    def revoquer(self, uid: int) -> Utilisateur | None:
        if uid in self.admins_config:
            raise PermissionError("Un administrateur défini dans la configuration ne peut être révoqué.")
        u = self.utilisateurs.pop(uid, None)
        self.sauver()
        return u

    def notifications(self, uid: int, actif: bool) -> None:
        self.utilisateurs[uid].notifications = actif
        self.sauver()

    def renommer(self, uid: int, nom: str) -> None:
        u = self.utilisateurs.get(uid)
        if u and u.nom != nom:
            u.nom = nom
            self.sauver()
