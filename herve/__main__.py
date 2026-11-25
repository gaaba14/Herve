"""Point d'entrée : python -m herve [chemin/config.yaml]"""

from __future__ import annotations

import argparse
import logging
import sys

from .bot import Herve
from .config import ConfigError, charger
from .sources import creer_sources
from .utilisateurs import Registre


def main() -> int:
    p = argparse.ArgumentParser(prog="herve", description="Hervé, majordome de Montcuit")
    p.add_argument("config", nargs="?", default="config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        cfg = charger(args.config)
    except ConfigError as e:
        print(f"Configuration invalide : {e}", file=sys.stderr)
        return 2
    if not cfg.telegram_token:
        print("Configuration invalide : telegram.token manquant (variable TELEGRAM_TOKEN ?)", file=sys.stderr)
        return 2

    registre = Registre(cfg.dossier_donnees / "utilisateurs.json", cfg.administrateurs)
    herve = Herve(cfg, creer_sources(cfg), registre)
    logging.getLogger("herve").info(
        "Hervé prend son service à %s (électricité : %s, alarme : %s, chauffage : %s)",
        cfg.maison, cfg.electricite.source, cfg.alarme.source, cfg.chauffage.source)
    herve.application().run_polling(drop_pending_updates=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
