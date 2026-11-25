"""La voix d'Hervé : formules et mise en forme des comptes rendus (HTML Telegram)."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from html import escape

from .sources.base import ALARME_ETATS, Energie, EvenementAlarme, Thermostat

ACQUIESCEMENTS = ["Bien.", "C'est fait.", "Je m'en occupe.", "Ce sera fait.", "Entendu."]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


def bien() -> str:
    return random.choice(ACQUIESCEMENTS)


def salutation(maintenant: datetime) -> str:
    h = maintenant.hour
    if 5 <= h < 12:
        return "Bonjour"
    if 12 <= h < 18:
        return "Bon après-midi"
    return "Bonsoir"


def nombre(v: float, decimales: int = 1) -> str:
    return f"{v:,.{decimales}f}".replace(",", " ").replace(".", ",")


def date_longue(j: date) -> str:
    return f"{JOURS[j.weekday()]} {j.day} {MOIS[j.month - 1]}"


def _kwh(v: float | None, prix: float) -> str:
    if v is None:
        return "—"
    cout = f" · {nombre(v * prix, 2)} €" if prix else ""
    return f"<b>{nombre(v)} kWh</b>{cout}"


def electricite(e: Energie, prix_kwh: float, maison: str) -> str:
    lignes = [f"⚡ <b>Électricité de {escape(maison)}</b>"]
    if not e.jours:
        return lignes[0] + "\nEnedis ne m'a encore transmis aucun relevé."
    auj = e.reference or e.dernier_jour + timedelta(days=1)
    hier = auj - timedelta(days=1)
    dernier = e.dernier_jour
    if hier in e.jours:
        lignes.append(f"Hier ({date_longue(hier)}) : {_kwh(e.jour(hier), prix_kwh)}")
    else:
        lignes.append(f"Les chiffres d'hier ne sont pas encore arrivés d'Enedis.\n"
                      f"Dernier relevé, {date_longue(dernier)} : {_kwh(e.jour(dernier), prix_kwh)}")
    lignes.append(f"7 derniers jours : {_kwh(e.sept_jours(), prix_kwh)}")
    mois = e.mois_en_cours()
    if mois is not None:
        nb = len([j for j in e.jours if j.month == auj.month and j.year == auj.year])
        lignes.append(f"{MOIS[auj.month - 1].capitalize()} (à ce jour) : {_kwh(mois, prix_kwh)}"
                      f"\n   soit {nombre(mois / nb)} kWh par jour en moyenne")
    lignes.append("<i>Relevés Enedis, transmis chaque matin pour la veille.</i>")
    return "\n".join(lignes)


ICONES_GRAVITE = {"info": "🔔", "attention": "⚠️", "urgence": "🚨"}


def evenement(ev: EvenementAlarme, avec_heure: bool = True) -> str:
    heure = ev.horodatage.strftime("%d/%m %H:%M") + " · " if avec_heure else ""
    zone = f" (zone/util. {escape(ev.zone)})" if ev.zone else ""
    return f"{ICONES_GRAVITE.get(ev.gravite, '🔔')} {heure}{escape(ev.texte)}{zone}"


def alarme(etat: str, derniere_nouvelle: datetime | None = None,
           historique: list[EvenementAlarme] | None = None) -> str:
    icone = {"disarmed": "🔓", "triggered": "🚨", "unknown": "❔"}.get(etat, "🔒")
    lignes = [f"{icone} L'alarme est <b>{ALARME_ETATS.get(etat, etat)}</b>."]
    if derniere_nouvelle:
        lignes.append(f"<i>Dernière nouvelle de la centrale : {derniere_nouvelle.strftime('%d/%m à %H:%M')}</i>")
    if historique:
        lignes.append("\n<b>Derniers événements</b>")
        lignes += [evenement(ev) for ev in historique]
    return "\n".join(lignes)


MODES_THERMOSTAT = {"off": "arrêt", "heat": "chauffage", "cool": "climatisation", "auto": "auto"}


def thermostat_ligne(t: Thermostat) -> str:
    flamme = " 🔥" if t.en_chauffe else ""
    temp = "—" if t.temperature is None else f"{nombre(t.temperature)} °C"
    consigne = "—" if t.consigne is None else f"{nombre(t.consigne)} °C"
    hum = f" · {nombre(t.humidite, 0)} % d'humidité" if t.humidite is not None else ""
    mode = MODES_THERMOSTAT.get(t.mode or "", t.mode or "?")
    return f"<b>{escape(t.nom)}</b> : {temp}{flamme}{hum}\n   consigne {consigne} · {mode}"


def thermostats(liste: list[Thermostat]) -> str:
    if not liste:
        return "🌡️ Aucun thermostat n'est confié à mes soins."
    return "🌡️ <b>Chauffage</b>\n" + "\n".join(thermostat_ligne(t) for t in liste)


def rapport(maison: str, salut: str, e: Energie | None, alarme_txt: str | None,
            ths: list[Thermostat] | None, prix_kwh: float) -> str:
    parties = [f"📋 {salut}. Voici le compte rendu de <b>{escape(maison)}</b>."]
    parties.append(electricite(e, prix_kwh, maison) if e is not None
                   else "⚡ Enedis ne m'a pas répondu ce matin.")
    if alarme_txt is not None:
        parties.append(alarme_txt)
    parties.append(thermostats(ths) if ths is not None else "🌡️ Le thermostat ne me répond pas.")
    parties.append("<i>Je reste à votre disposition.</i>")
    return "\n\n".join(parties)


AIDE = """Je suis <b>Hervé</b>, majordome de {maison}. Voici ce que je sais faire :

/menu — le tableau de bord
/conso — la consommation électrique (relevés Enedis)
/alarme — l'état de l'alarme et ses derniers événements
/chauffage — température et consigne du thermostat
/consigne &lt;°C&gt; — régler la consigne (ex. /consigne 20,5)
/rapport — un compte rendu complet
/notifications on|off — recevoir ou non mes alertes
/moi — vos informations

<b>Administration</b>
/utilisateurs — les personnes de la maison
/autoriser &lt;id&gt; [invite|membre|admin]
/revoquer &lt;id&gt;

<i>L'alarme Ajax s'arme et se désarme depuis l'application Ajax ; je vous préviens de tout ce qu'elle signale.</i>"""
