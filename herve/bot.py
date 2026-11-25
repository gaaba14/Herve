"""Hervé sur Telegram : commandes, boutons et diffusion des alertes."""

from __future__ import annotations

import functools
import logging
import unicodedata
from datetime import datetime
from html import escape

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from . import messages as M
from .config import Config
from .sources import EvenementAlarme, SourceError, Sources
from .surveillance import Alerte, Surveillant, alerte_alarme
from .utilisateurs import ADMIN, INVITE, MEMBRE, ROLES, ROLES_LIBELLES, Registre

log = logging.getLogger(__name__)

EXCUSE_PANNE = "Je suis navré, je n'obtiens pas de réponse pour le moment. ({})"


def _sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _clavier(lignes) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[B(t, callback_data=d) for t, d in ligne] for ligne in lignes if ligne])


CLAVIER_MENU = _clavier([
    [("⚡ Électricité", "conso"), ("🚨 Alarme", "alarme")],
    [("🌡️ Chauffage", "th"), ("📋 Compte rendu", "rapport")],
])
RETOUR = [("↩️ Menu", "menu")]


class Herve:
    def __init__(self, cfg: Config, sources: Sources, registre: Registre):
        self.cfg = cfg
        self.sources = sources
        self.registre = registre
        self.surveillant = Surveillant(cfg, sources)
        self.app: Application | None = None
        sources.alarme.ecouter(self._sur_evenement_alarme)

    # ------------------------------------------------------------------ outils
    def _autorise(self, update: Update, requis: str) -> bool:
        u = update.effective_user
        return u is not None and self.registre.autorise(u.id, requis)

    @staticmethod
    async def _repondre(update: Update, texte: str, clavier: InlineKeyboardMarkup | None = None) -> None:
        """Répond à une commande, ou met à jour le message d'origine d'un bouton."""
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    texte, parse_mode=ParseMode.HTML, reply_markup=clavier)
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    raise
        else:
            await update.effective_message.reply_text(texte, parse_mode=ParseMode.HTML, reply_markup=clavier)

    async def diffuser(self, bot, alerte: Alerte) -> None:
        dest = (list(self.registre.utilisateurs.values()) if alerte.urgent
                else self.registre.a_notifier(alerte.destinataires))
        for u in dest:
            try:
                await bot.send_message(u.id, alerte.texte, parse_mode=ParseMode.HTML)
            except Forbidden:
                log.info("%s (%s) a bloqué Hervé", u.nom, u.id)
            except TelegramError as e:
                log.warning("Envoi impossible à %s : %s", u.id, e)

    async def _sur_evenement_alarme(self, ev: EvenementAlarme) -> None:
        if self.app is not None:
            await self.diffuser(self.app.bot, alerte_alarme(ev, self.cfg.maison))

    # ------------------------------------------------------- accès / identité
    async def start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        if self.registre.autorise(u.id):
            self.registre.renommer(u.id, u.full_name or u.username or str(u.id))
            bonjour = M.salutation(datetime.now(self.cfg.fuseau))
            await update.effective_message.reply_text(
                f"{bonjour} {escape(u.first_name or '')}. Hervé, pour vous servir. "
                f"Que puis-je faire pour vous à {escape(self.cfg.maison)} ?",
                parse_mode=ParseMode.HTML, reply_markup=CLAVIER_MENU)
            return
        await self._demande_acces(update, ctx)

    async def _demande_acces(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        nom = u.full_name or u.username or str(u.id)
        nouvelle = self.registre.demander(u.id, nom)
        await update.effective_message.reply_text(
            f"Je suis Hervé, majordome de {escape(self.cfg.maison)}. Je crains de ne pas avoir "
            f"l'honneur de vous connaître.\nJ'ai transmis votre demande aux maîtres des lieux. "
            f"(Votre identifiant : <code>{u.id}</code>)",
            parse_mode=ParseMode.HTML)
        if not nouvelle:
            return
        clavier = _clavier([
            [("👁️ Invité", f"acc:{u.id}:{INVITE}"), ("🏠 Membre", f"acc:{u.id}:{MEMBRE}")],
            [("👑 Admin", f"acc:{u.id}:{ADMIN}"), ("❌ Refuser", f"ref:{u.id}")],
        ])
        pseudo = f" (@{escape(u.username)})" if u.username else ""
        for admin in self.registre.admins():
            try:
                await ctx.bot.send_message(
                    admin.id,
                    f"🛎️ <b>{escape(nom)}</b>{pseudo} demande l'accès à {escape(self.cfg.maison)}.\n"
                    f"Identifiant : <code>{u.id}</code>. Quel rôle lui accorder ?",
                    parse_mode=ParseMode.HTML, reply_markup=clavier)
            except TelegramError as e:
                log.warning("Impossible de prévenir l'admin %s : %s", admin.id, e)

    async def aide(self, update: Update, ctx) -> None:
        await self._repondre(update, M.AIDE.format(maison=escape(self.cfg.maison)))

    async def menu(self, update: Update, ctx) -> None:
        await self._repondre(update, f"Que souhaitez-vous savoir sur {escape(self.cfg.maison)} ?", CLAVIER_MENU)

    async def moi(self, update: Update, ctx) -> None:
        u = self.registre.get(update.effective_user.id)
        await self._repondre(update, (
            f"<b>{escape(u.nom)}</b>\nIdentifiant : <code>{u.id}</code>\n"
            f"Rôle : {ROLES_LIBELLES[u.role]}\nNotifications : {'oui' if u.notifications else 'non'}"))

    async def notifications(self, update: Update, ctx) -> None:
        arg = ctx.args[0].lower() if ctx.args else ""
        if arg not in ("on", "off", "oui", "non"):
            await self._repondre(update, "Dites-moi <code>/notifications on</code> ou <code>/notifications off</code>.")
            return
        actif = arg in ("on", "oui")
        self.registre.notifications(update.effective_user.id, actif)
        await self._repondre(update, f"{M.bien()} " + (
            "Je vous tiendrai au courant de ce qui se passe à la maison." if actif else
            "Je ne vous dérangerai plus, sauf urgence (alarme, incendie, fuite d'eau)."))

    # ----------------------------------------------------------- électricité
    async def conso(self, update: Update, ctx) -> None:
        try:
            e = await self.sources.electricite.energie()
        except SourceError as err:
            await self._repondre(update, EXCUSE_PANNE.format(escape(str(err))), _clavier([RETOUR]))
            return
        await self._repondre(update, M.electricite(e, self.cfg.electricite.prix_kwh, self.cfg.maison),
                             _clavier([RETOUR]))

    # ---------------------------------------------------------------- alarme
    def _texte_alarme(self, n: int = 5) -> str:
        a = self.sources.alarme
        return M.alarme(a.etat, a.derniere_nouvelle, a.historique(n))

    async def alarme(self, update: Update, ctx) -> None:
        await self._repondre(update, self._texte_alarme(),
                             _clavier([[("📜 Historique", "hist"), ("🔄 Actualiser", "alarme")], RETOUR]))

    async def historique(self, update: Update, ctx) -> None:
        evs = self.sources.alarme.historique(20)
        texte = ("📜 <b>Journal de l'alarme</b>\n" + "\n".join(M.evenement(e) for e in evs)
                 if evs else "Le journal de l'alarme est vide.")
        await self._repondre(update, texte, _clavier([[("↩️ Alarme", "alarme"), *RETOUR]]))

    async def simuler(self, update: Update, ctx) -> None:
        """Mode démo uniquement : simule un événement d'alarme pour tester les notifications."""
        alarme = self.sources.alarme
        if not hasattr(alarme, "simuler"):
            await self._repondre(update, "La simulation n'est possible qu'en mode démo.")
            return
        quoi = (ctx.args[0].lower() if ctx.args else "intrusion")
        scenarios = {
            "armer": ("CL", "Alarme armée", "armed_away", "info"),
            "desarmer": ("OP", "Alarme désarmée", "disarmed", "info"),
            "intrusion": ("BA", "INTRUSION détectée", "triggered", "urgence"),
            "secteur": ("AT", "Coupure de courant secteur sur la centrale", None, "attention"),
        }
        if quoi not in scenarios:
            await self._repondre(update, "Scénarios : " + ", ".join(scenarios))
            return
        code, texte, etat, gravite = scenarios[quoi]
        await alarme.simuler(code, texte, etat, gravite)

    # ------------------------------------------------------------- chauffage
    async def chauffage(self, update: Update, ctx) -> None:
        try:
            ths = await self.sources.chauffage.thermostats()
        except SourceError as err:
            await self._repondre(update, EXCUSE_PANNE.format(escape(str(err))), _clavier([RETOUR]))
            return
        lignes = []
        if self._autorise(update, MEMBRE):
            for i, t in enumerate(ths):
                prefixe = f"{t.nom} " if len(ths) > 1 else ""
                lignes.append([(f"{prefixe}− {t.pas:g}°", f"tc:{i}:-"), (f"{prefixe}+ {t.pas:g}°", f"tc:{i}:+")])
                modes = [(("✓ " if m == t.mode else "") + M.MODES_THERMOSTAT.get(m, m), f"tm:{i}:{m}")
                         for m in t.modes if m in M.MODES_THERMOSTAT]
                if len(modes) > 1:
                    lignes.append(modes)
        lignes += [[("🔄 Actualiser", "th")], RETOUR]
        await self._repondre(update, M.thermostats(ths), _clavier(lignes))

    async def _regler_consigne(self, t, consigne: float) -> str:
        consigne = round(min(t.consigne_max, max(t.consigne_min, consigne)) / t.pas) * t.pas
        await self.sources.chauffage.regler_consigne(t.id, consigne)
        return f"{M.bien()} Consigne de « {escape(t.nom)} » réglée à {M.nombre(consigne)} °C."

    async def consigne(self, update: Update, ctx) -> None:
        args = list(ctx.args)
        try:
            valeur = float(args.pop().replace(",", ".").rstrip("°cC")) if args else None
        except ValueError:
            valeur = None
        if valeur is None:
            await self._repondre(update, "Indiquez-moi la température souhaitée, par exemple "
                                         "<code>/consigne 20,5</code>.")
            return
        piece = _sans_accents(" ".join(args))
        try:
            ths = await self.sources.chauffage.thermostats()
            choix = [t for t in ths if _sans_accents(t.nom).startswith(piece)]
            if len(choix) != 1:
                noms = ", ".join(t.nom for t in ths) or "aucun"
                await self._repondre(update, f"Quel thermostat, je vous prie ? Je connais : {escape(noms)}.")
                return
            await self._repondre(update, await self._regler_consigne(choix[0], valeur))
        except SourceError as err:
            await self._repondre(update, EXCUSE_PANNE.format(escape(str(err))))

    # --------------------------------------------------------------- rapport
    async def _rapport_texte(self) -> str:
        try:
            e = await self.sources.electricite.energie()
        except SourceError:
            e = None
        try:
            ths = await self.sources.chauffage.thermostats()
        except SourceError:
            ths = None
        salut = M.salutation(datetime.now(self.cfg.fuseau))
        return M.rapport(self.cfg.maison, salut, e, self._texte_alarme(3), ths, self.cfg.electricite.prix_kwh)

    async def rapport(self, update: Update, ctx) -> None:
        await self._repondre(update, await self._rapport_texte(), _clavier([RETOUR]))

    # ------------------------------------------------------- administration
    async def liste_utilisateurs(self, update: Update, ctx) -> None:
        lignes = ["👥 <b>Personnes de la maison</b>"]
        for u in sorted(self.registre.utilisateurs.values(), key=lambda u: (-ROLES.index(u.role), u.nom)):
            cloche = "🔔" if u.notifications else "🔕"
            lignes.append(f"{cloche} {escape(u.nom)} — {ROLES_LIBELLES[u.role]} — <code>{u.id}</code>")
        if self.registre.demandes:
            lignes.append("\n⏳ <b>Demandes en attente</b>")
            lignes += [f"{escape(n)} — <code>{i}</code>" for i, n in self.registre.demandes.items()]
        await self._repondre(update, "\n".join(lignes))

    async def autoriser(self, update: Update, ctx) -> None:
        try:
            uid = int(ctx.args[0])
            role = ctx.args[1].lower() if len(ctx.args) > 1 else MEMBRE
            u = self.registre.autoriser(uid, role)
        except (IndexError, ValueError):
            await self._repondre(update, "Usage : <code>/autoriser &lt;id&gt; [invite|membre|admin]</code>")
            return
        await self._repondre(update, f"{M.bien()} {escape(u.nom)} est désormais {ROLES_LIBELLES[u.role]}.")
        await self._accueillir(ctx, u)

    async def _accueillir(self, ctx, u) -> None:
        try:
            await ctx.bot.send_message(
                u.id, f"Bienvenue à {escape(self.cfg.maison)}. Je suis Hervé, et je serai heureux de "
                      f"vous servir en tant que {ROLES_LIBELLES[u.role]}. Tapez /aide pour commencer.",
                parse_mode=ParseMode.HTML, reply_markup=CLAVIER_MENU)
        except TelegramError:
            pass

    async def revoquer(self, update: Update, ctx) -> None:
        try:
            uid = int(ctx.args[0])
        except (IndexError, ValueError):
            await self._repondre(update, "Usage : <code>/revoquer &lt;id&gt;</code>")
            return
        try:
            u = self.registre.revoquer(uid)
        except PermissionError as e:
            await self._repondre(update, str(e))
            return
        await self._repondre(update, f"{M.bien()} {escape(u.nom)} n'a plus accès à la maison." if u
                             else "Je ne connais personne sous cet identifiant.")

    # --------------------------------------------------------------- boutons
    async def bouton(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        data = q.data or ""
        requis = (ADMIN if data.startswith(("acc:", "ref:"))
                  else MEMBRE if data.startswith(("tc:", "tm:"))
                  else INVITE)
        if not self._autorise(update, requis):
            await q.answer("Vous n'avez pas l'autorisation, je regrette.", show_alert=True)
            return
        await q.answer()
        try:
            await self._router_bouton(update, ctx, data)
        except SourceError as err:
            await self._repondre(update, EXCUSE_PANNE.format(escape(str(err))), _clavier([RETOUR]))

    async def _router_bouton(self, update: Update, ctx, data: str) -> None:
        simples = {"menu": self.menu, "conso": self.conso, "alarme": self.alarme, "hist": self.historique,
                   "th": self.chauffage, "rapport": self.rapport}
        if data in simples:
            await simples[data](update, ctx)
        elif data.startswith(("tc:", "tm:")):
            _, idx, val = data.split(":", 2)
            ths = await self.sources.chauffage.thermostats()
            if not 0 <= int(idx) < len(ths):
                return
            t = ths[int(idx)]
            if data.startswith("tc:"):
                base = t.consigne if t.consigne is not None else 19.0
                await self._regler_consigne(t, base + (t.pas if val == "+" else -t.pas))
            elif val in t.modes:
                await self.sources.chauffage.regler_mode(t.id, val)
            await self.chauffage(update, ctx)
        elif data.startswith("acc:"):
            _, uid, role = data.split(":")
            u = self.registre.autoriser(int(uid), role)
            await self._repondre(update, f"✅ {escape(u.nom)} est désormais {ROLES_LIBELLES[u.role]}.")
            await self._accueillir(ctx, u)
        elif data.startswith("ref:"):
            nom = self.registre.refuser(int(data[4:]))
            await self._repondre(update, f"❌ Demande de {escape(nom or data[4:])} refusée.")

    # ------------------------------------------------------- tâches de fond
    async def tache_veille(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        for alerte in await self.surveillant.verifier():
            await self.diffuser(ctx.bot, alerte)

    async def tache_rapport(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        texte = await self._rapport_texte()
        for u in self.registre.a_notifier(INVITE):
            try:
                await ctx.bot.send_message(u.id, texte, parse_mode=ParseMode.HTML)
            except TelegramError as e:
                log.warning("Rapport non remis à %s : %s", u.id, e)
        for alerte in await self.surveillant.electricite():
            await self.diffuser(ctx.bot, alerte)

    async def erreur(self, update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("Erreur non gérée", exc_info=ctx.error)

    # ---------------------------------------------------------- assemblage
    def _garde(self, requis: str, fn):
        @functools.wraps(fn)
        async def enveloppe(update: Update, ctx):
            if self._autorise(update, requis):
                await fn(update, ctx)
            elif self._autorise(update, INVITE):
                await self._repondre(update, "Je regrette, cela dépasse ce que je suis autorisé à faire pour vous.")
            else:
                await self._demande_acces(update, ctx)
        return enveloppe

    def application(self) -> Application:
        async def apres_demarrage(app: Application) -> None:
            await self.sources.demarrer()

        async def apres_arret(app: Application) -> None:
            await self.sources.fermer()

        app = (Application.builder().token(self.cfg.telegram_token)
               .post_init(apres_demarrage).post_shutdown(apres_arret).build())
        self.app = app

        commandes = {
            "aide": (INVITE, self.aide), "help": (INVITE, self.aide),
            "menu": (INVITE, self.menu), "moi": (INVITE, self.moi),
            "notifications": (INVITE, self.notifications),
            "conso": (INVITE, self.conso), "electricite": (INVITE, self.conso),
            "alarme": (INVITE, self.alarme), "historique": (INVITE, self.historique),
            "chauffage": (INVITE, self.chauffage), "thermostat": (INVITE, self.chauffage),
            "consigne": (MEMBRE, self.consigne),
            "rapport": (INVITE, self.rapport),
            "utilisateurs": (ADMIN, self.liste_utilisateurs),
            "autoriser": (ADMIN, self.autoriser), "revoquer": (ADMIN, self.revoquer),
            "simuler": (ADMIN, self.simuler),
        }
        app.add_handler(CommandHandler("start", self.start))
        for nom, (requis, fn) in commandes.items():
            app.add_handler(CommandHandler(nom, self._garde(requis, fn)))
        app.add_handler(CallbackQueryHandler(self.bouton))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._garde(INVITE, self.menu)))
        app.add_error_handler(self.erreur)

        app.job_queue.run_repeating(self.tache_veille, interval=self.cfg.intervalle_s, first=10)
        if self.cfg.rapport_quotidien:
            app.job_queue.run_daily(self.tache_rapport, time=self.cfg.rapport_quotidien)
        return app
