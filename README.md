# Hervé, majordome de Montcuit

Hervé est un bot Telegram qui veille sur la maison de **Montcuit** :

- ⚡ **Électricité** : consommation du compteur Linky (relevés Enedis), coût en euros, alerte en cas de journée anormalement gourmande ;
- 🚨 **Alarme Ajax** : état (armée / désarmée / déclenchée), journal des événements, alertes immédiates (intrusion, incendie, fuite d'eau, sabotage, coupure de courant), et alerte si la centrale ne donne plus signe de vie ;
- 🌡️ **Chauffage** : température, humidité et consigne du thermostat **Resideo T6**, réglage de la consigne et du mode, alerte hors-gel ;
- 📋 **Compte rendu quotidien** envoyé chaque matin ;
- 👥 **Plusieurs personnes** via Telegram, avec des rôles.

Aucune box domotique n'est nécessaire : Hervé parle directement à chaque service.

```
            ┌──────────────── Hervé (serveur / VPS) ─────────────────┐
Telegram ◄──┤  bot  ◄── surveillance ◄── sources                      │
 (famille)  │                            ├─ Enedis (conso.boris.sh)  │──► Internet
            │                            ├─ Resideo T6 (API OAuth)   │──► Internet
            │                            └─ serveur SIA :12128  ◄────┼─── centrale Ajax
            └─────────────────────────────────────────────────────────┘
```

## Rôles

| Rôle | Peut… |
|---|---|
| **invité** | consulter la conso, l'alarme, le chauffage ; recevoir les alertes |
| **membre** | … et régler le chauffage (consigne, mode) |
| **admin** | … et accepter, refuser ou révoquer des personnes |

Quand une personne inconnue écrit à Hervé, il lui répond poliment et envoie aux administrateurs une demande avec des boutons *Invité / Membre / Admin / Refuser*.
Chacun peut couper ses notifications (`/notifications off`). Les **urgences** (intrusion, incendie, fuite d'eau…) sont envoyées à tous quand même.

## Commandes

| Commande | Effet |
|---|---|
| `/menu` | tableau de bord à boutons |
| `/conso` | consommation : hier, 7 jours, mois en cours, coût |
| `/alarme`, `/historique` | état de l'alarme, journal des événements |
| `/chauffage` | température et consigne, boutons +/− et mode |
| `/consigne 20,5` | régler la consigne |
| `/rapport` | compte rendu complet |
| `/notifications on\|off` | recevoir ou non les alertes |
| `/moi` | votre identifiant et votre rôle |
| `/utilisateurs`, `/autoriser <id> [role]`, `/revoquer <id>` | administration |
| `/simuler intrusion\|armer\|desarmer\|secteur` | (mode démo) tester les alertes d'alarme |

## Mise en route

### 1. Créer le bot Telegram
1. Sur Telegram, écrivez à **@BotFather**, puis `/newbot`. Nommez-le « Hervé ».
2. Notez le **token** : il ira dans `TELEGRAM_TOKEN`.

### 2. Configuration
```bash
cp config.example.yaml config.yaml
```
```bash
cp .env.example .env
```
Les secrets vont dans `.env`, le reste dans `config.yaml`. Mettez `source: demo` aux sections pas encore prêtes : Hervé fonctionne alors avec des données simulées.
Pour connaître votre identifiant Telegram (à mettre dans `administrateurs`), lancez Hervé et écrivez-lui : il vous le donne.

### 3. Électricité : Linky / Enedis
1. Dans votre [espace client Enedis](https://mon-compte-particulier.enedis.fr), activez l'**enregistrement et la collecte de la consommation horaire**. Sans cela, Enedis ne renvoie aucune donnée.
2. Sur **conso.boris.sh**, autorisez l'accès à votre compteur et récupérez le **jeton**. Mettez-le dans `ENEDIS_TOKEN`, et le **PRM** (14 chiffres) dans `config.yaml`.

Enedis transmet les chiffres **le lendemain, vers 8 h**. Il n'y a donc pas de temps réel, d'où le compte rendu par défaut à 9 h 30. Hervé respecte les consignes du service : au plus un appel par heure, et aucun une fois la veille reçue.

### 4. Chauffage : Resideo T6
1. Créez une application sur **developer.honeywellhome.com**, avec l'adresse de retour (*Callback URL*) `https://localhost/herve` ou celle que vous mettez dans `url_retour`.
2. Mettez la *Consumer Key* et le *Consumer Secret* dans `RESIDEO_CLE` et `RESIDEO_SECRET`.
3. Autorisez Hervé, une seule fois :
   ```bash
   docker compose run --rm herve python -m herve.resideo_auth /app/config.yaml
   ```
   Ouvrez le lien affiché et acceptez. Le navigateur arrive ensuite sur une page d'erreur `localhost`, c'est normal : copiez son adresse complète et collez-la dans le terminal. Le jeton est enregistré dans `data/resideo_jetons.json` et renouvelé automatiquement.

`maintien: TemporaryHold` garde la consigne jusqu'au prochain créneau du programme du T6 ; `PermanentHold` la garde jusqu'à nouvel ordre.

### 5. Alarme : Ajax (protocole SIA)
Ajax n'a pas d'API publique de pilotage. Hervé se déclare donc comme **centre de télésurveillance** : la centrale lui envoie chaque événement en temps réel. **Armer et désarmer restent dans l'application Ajax** ; Hervé vous prévient de tout.

1. Dans **Ajax PRO** (accès installateur requis), allez dans *Hub › Paramètres › Centre de télésurveillance* et choisissez le protocole **SIA DC-09**.
2. Indiquez l'**adresse IP publique du serveur** et le port **12128**.
3. Choisissez un **numéro d'objet / compte** (ex. `AAA`, en hexadécimal) : même valeur que `alarme.compte`.
4. Activez le **chiffrement** avec une clé de 16, 24 ou 32 caractères, la même que `SIA_CLE`. C'est fortement conseillé, puisque le port est exposé sur Internet.
5. Activez le **test périodique** (par exemple toutes les 10 minutes) : Hervé s'en sert pour savoir que la centrale est en ligne. Réglez `silence_max_min` au-dessus de cet intervalle.

Sur le serveur, ouvrez le port TCP 12128 dans le pare-feu.

### 6. Lancer
```bash
mkdir -p data && sudo chown 1000 data
```
```bash
docker compose up -d --build
```
```bash
docker compose logs -f
```

Sans Docker (Python 3.11+) :
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```
```bash
set -a && . ./.env && set +a && .venv/bin/python -m herve config.yaml
```

## Développement
```bash
.venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest
```

```
herve/
├── bot.py           # commandes et boutons Telegram, diffusion des alertes
├── surveillance.py  # hors-gel, panne du thermostat, silence de la centrale, seuil électrique
├── messages.py      # la voix d'Hervé et la mise en forme
├── utilisateurs.py  # personnes autorisées et rôles (data/utilisateurs.json)
├── config.py        # lecture de config.yaml + variables d'environnement
├── resideo_auth.py  # autorisation OAuth unique du thermostat
└── sources/
    ├── enedis.py    # Linky via conso.boris.sh
    ├── resideo.py   # thermostat T6 (API Honeywell Home)
    ├── ajax_sia.py  # réception SIA DC-09 de la centrale Ajax
    └── demo.py      # données simulées
```

### Points à vérifier en conditions réelles
- **Enedis** : conso.boris.sh est passé aux nouvelles API Enedis (« mesure synchrone ») à l'automne 2026. Hervé lit l'ancien et le nouveau format de réponse, mais le nouveau n'a pas pu être testé sur un vrai compteur. Si la conso reste vide, lancez Hervé avec `-v` et regardez la réponse. Le type d'appel se change avec `electricite.type_api`.
- **Ajax** : la correspondance des codes SIA (armement, mode nuit, armement partiel) est celle du standard. Vérifiez au premier armement que l'état affiché est le bon.
