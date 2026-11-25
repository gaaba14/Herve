"""Autorisation unique d'Hervé auprès de Resideo (Honeywell Home).

Usage : python -m herve.resideo_auth [config.yaml]

1. Ouvrez le lien affiché, connectez-vous à votre compte Honeywell Home et
   autorisez l'accès au thermostat.
2. Le navigateur est renvoyé vers l'adresse de retour (une page d'erreur est
   normale) : copiez l'adresse complète de cette page et collez-la ici.
"""

from __future__ import annotations

import asyncio
import sys
from urllib.parse import parse_qs, urlparse

import httpx

from .config import ConfigError, charger
from .sources.resideo import Jetons, demander_jeton, url_autorisation


async def _echanger(cfg, code: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        reponse = await demander_jeton(client, cfg.chauffage, grant_type="authorization_code",
                                       code=code, redirect_uri=cfg.chauffage.url_retour)
    Jetons(cfg.dossier_donnees / "resideo_jetons.json").sauver(reponse)


def main() -> int:
    try:
        cfg = charger(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
    except ConfigError as e:
        print(f"Configuration invalide : {e}", file=sys.stderr)
        return 2
    if cfg.chauffage.source != "resideo":
        print("chauffage.source n'est pas « resideo » dans la configuration.", file=sys.stderr)
        return 2
    print("1. Ouvrez ce lien et autorisez Hervé :\n")
    print("   " + url_autorisation(cfg.chauffage) + "\n")
    saisie = input("2. Collez l'adresse de la page de retour (ou le code) : ").strip()
    code = parse_qs(urlparse(saisie).query).get("code", [saisie])[0]
    asyncio.run(_echanger(cfg, code))
    print("\nC'est fait : Hervé a désormais accès au thermostat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
