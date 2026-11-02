# Guide de configuration

Ce guide décrit l'installation, chaque variable de `.env`, les composants
facultatifs et les points d'attention pour un déploiement durable.

---

## 1. Prérequis

| Outil | Version | Usage |
|---|---|---|
| Docker et Docker Compose | récent | toute la partie serveur |
| Node.js | 24 | interface web |
| Ollama | récent, facultatif | résumés, arbitrage des annonces incertaines |

Prévoir environ 8 Go de disque pour les images (le navigateur de collecte et
les bibliothèques de traduction sont volumineux). PostgreSQL n'est **jamais**
installé sur l'hôte : la base tourne dans le service `db`.

---

## 2. Installation

```bash
cp .env.example .env
# éditer .env (section 3)
docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.create_user admin --role admin
cd frontend && npm ci && npm run dev
```

Le premier compte doit être créé avec `--role admin`. Sans cela, personne ne
peut gérer les comptes, les sources ni la planification. Les comptes suivants
se créent depuis la page **Comptes** de l'interface.

Rôles disponibles :

| Rôle | Accès |
|---|---|
| `admin` | tout, y compris la configuration et les gestes destructeurs |
| `analyst` (défaut) | alertes, documents, détections, sources en lecture |
| `viewer` | vues agrégées seulement (cartographie, gouvernance, périmètre), pour un RSSI |

---

## 3. Variables d'environnement

### Obligatoires

| Variable | Rôle | Comment la remplir |
|---|---|---|
| `JWT_SECRET_KEY` | signe les jetons de connexion | `openssl rand -hex 32`. L'API refuse de démarrer si elle est vide ou vaut `changeme`. |
| `PASSWORD_HASH_PEPPER` | poivre du hachage des mots de passe trouvés dans les documents | `openssl rand -hex 32`. Ne plus le changer une fois des données collectées. |
| `POSTGRES_PASSWORD` | mot de passe de la base | valeur forte, à reporter aussi dans `DATABASE_URL` |
| `TOR_CONTROL_PASSWORD` | protège le port de contrôle de Tor | valeur forte. Elle est hachée à la construction de l'image `tor` : la changer impose `docker compose build tor`. |

⚠️ Une fois la base initialisée, changer `POSTGRES_PASSWORD` dans `.env` ne
suffit plus : le volume a gardé l'ancien mot de passe. Il faut aussi exécuter
`ALTER ROLE` dans la base.

### API et sessions

| Variable | Défaut | Rôle |
|---|---|---|
| `API_ENV` | `development` | `production` réduit le niveau de journalisation |
| `API_CORS_ORIGINS` | `http://localhost:5173` | adresses autorisées à appeler l'API (l'interface web), séparées par des virgules |
| `JWT_ALGORITHM` | `HS256` | |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `10` | durée du jeton d'accès, renouvelé automatiquement tant que l'utilisateur est actif |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | durée maximale du jeton de renouvellement |
| `SESSION_IDLE_TIMEOUT_MINUTES` | `10` | déconnexion après cette durée sans activité |
| `SESSION_MAX_HOURS` | `12` | durée maximale d'une session |

### Base, Redis et Celery

| Variable | Défaut |
|---|---|
| `POSTGRES_USER`, `POSTGRES_DB` | `tip_user`, `threat_intel` |
| `DATABASE_URL` | `postgresql+psycopg://tip_user:changeme@db:5432/threat_intel` |
| `REDIS_URL` | `redis://redis:6379/0` |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` |

### Tor

| Variable | Défaut |
|---|---|
| `TOR_SOCKS_HOST`, `TOR_SOCKS_PORT` | `tor`, `9050` |
| `TOR_CONTROL_HOST`, `TOR_CONTROL_PORT` | `tor`, `9051` |

Vérifier que la sortie passe bien par Tor :

```bash
docker compose exec tor curl --socks5 tor:9050 https://check.torproject.org
```

### Modèle de langue

| Variable | Défaut | Rôle |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | adresse d'Ollama sur l'hôte |
| `LLM_MODEL` | `ollama:qwen3:8b` | modèle des résumés et de l'analyse |
| `OPENAI_API_KEY`, `GOOGLE_API_KEY` | vides | fournisseurs en ligne, facultatifs |

### Enrichissement et alertes

| Variable | Défaut | Rôle |
|---|---|---|
| `INTELX_API_KEY` | vide | corroboration IntelX à la demande (compte gratuit possible) |
| `ALERT_WATCHED_CONTINENTS` | `Afrique` | continents pour lesquels une victime non déclarée produit une alerte régionale. Vide : seules les organisations déclarées alertent. |

### Telegram (facultatif)

| Variable | Défaut | Rôle |
|---|---|---|
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | vides | Client API. Vides, les canaux publics sont lus par l'aperçu web `t.me/s/`, limité aux messages récents. |

### Planification initiale

`COLLECT_SCHEDULE_HOURS`, `COLLECT_SCHEDULE_MINUTE`, `ALERT_SCHEDULE_MINUTE`,
`LINK_CHECK_SCHEDULE_HOUR`, `LINK_CHECK_SCHEDULE_MINUTE`,
`DREAD_COLLECT_SCHEDULE_HOUR`, `DREAD_COLLECT_SCHEDULE_MINUTE` (heures UTC).

Ces valeurs ne servent qu'à remplir la table des tâches au **premier**
démarrage de l'ordonnanceur. Ensuite, les horaires se modifient depuis la page
**Planification** de l'interface, et la modification prend effet en moins
d'une minute.

---

## 4. Premiers pas dans l'interface

1. **Sources** (administrateur) : déclarer les adresses `.onion` à collecter,
   ou les importer depuis une liste publique. Le bouton « Tester la
   disponibilité » vérifie qu'une adresse répond via Tor. Une source déclarée
   reste inactive tant qu'on ne l'active pas.
2. **Organisations** : déclarer les organisations surveillées et leurs
   sélecteurs (domaine, domaine d'adresse, nom). Une organisation sans
   sélecteur ne peut jamais produire d'alerte, l'interface le signale.
3. **Collecte** : lancer une collecte à la demande, ou attendre la
   planification.
4. **Alertes** : la génération tourne chaque heure. Le bouton « Relancer la
   génération » la déclenche immédiatement.

Un analyseur dédié est choisi d'après l'adresse du site. Un site sans
analyseur dédié est lu par le collecteur générique, qui produit un seul
document par page au lieu d'un document par victime.

---

## 5. Composants facultatifs

### Modèle de langue (Ollama)

```bash
ollama pull qwen3:8b
```

Sans modèle disponible, la plateforme fonctionne : les alertes sont produites,
seuls les résumés et l'arbitrage des annonces incertaines manquent.

### Telegram par le Client API

1. Créer une application sur https://my.telegram.org (API development tools)
   avec un compte **dédié** à la lecture.
2. Renseigner `TELEGRAM_API_ID` et `TELEGRAM_API_HASH`, puis redémarrer
   `backend` et `worker`.
3. Connecter le compte depuis la page **Compte Telegram** (administrateur) en
   scannant le QR code, ou en ligne de commande :
   `docker compose exec backend python -m app.scripts.telegram_login --qr`.

La session est un secret : elle vit dans le volume Docker `telegram_session`,
jamais dans le dépôt. Le compte ne fait que lire des canaux publics.

### Traduction

La traduction des documents utilise des modèles convertis au format
ctranslate2, stockés dans le volume `translation_models`. Pour installer la
paire « toutes langues vers l'anglais » :

```bash
docker compose exec backend pip install -r requirements-convert.txt
docker compose exec backend python -m app.scripts.convert_translation_model mul en
```

Sans modèle, le bouton de traduction répond qu'aucune paire n'est disponible.

---

## 6. Déploiement durable

- **Lancer sans les surcharges de développement** :
  `docker compose -f docker-compose.yml up -d`. Le fichier
  `docker-compose.override.yml` expose des ports, monte le code et ajoute
  Adminer. Il est réservé au développement.
- **Exposer l'API derrière un proxy inverse** (HTTPS). Le fichier principal ne
  publie aucun port : seul le proxy doit être joignable. Construire
  l'interface avec `VITE_API_BASE_URL=https://<adresse de l'API> npm run build`
  et servir le dossier `frontend/dist`. Ajouter cette adresse à
  `API_CORS_ORIGINS`.
- **Machine allumée en continu** : l'ordonnanceur ne rattrape pas un créneau
  manqué pendant un arrêt.
- **Sauvegardes** : `docker compose exec db pg_dump -U <utilisateur> -Fc <base> > sauvegarde.dump`.
  Une sauvegarde contient des données collectées : la traiter comme sensible.
- **Après une mise à jour du code** : reconstruire les workers un par un, puis
  appliquer les migrations.

```bash
docker compose build backend
docker compose build worker && docker compose build worker-links
docker compose build worker-dread && docker compose build beat
docker compose up -d
docker compose exec backend alembic upgrade head
```

Construire les images en parallèle peut épuiser la mémoire de la machine
virtuelle de Docker Desktop.
