# Contribuer : règles du projet

Ce fichier rassemble les règles que toute contribution doit respecter. Le code
y renvoie par numéro de section (par exemple « CONTRIBUTING.md §2 »).

---

## 1. Contexte

Plateforme de **surveillance et de détection de fuites de données** (Cyber
Threat Intelligence). Elle **observe** des sources du dark web, détecte les
organisations nommées comme victimes, évalue la gravité et la crédibilité de
chaque cas, et produit une **alerte** vérifiable.

L'outil **lit** des documents déjà publiés sur ces sources, il n'agit pas
dessus. Le livrable est **l'alerte**, jamais la donnée fuitée.

### Périmètre

- **Générique.** Le système surveille toute organisation déclarée par ses
  sélecteurs. Aucun nom d'organisation n'est écrit en dur dans le code.
- **Sélecteur principal : le domaine** (et les adresses `@domaine`). Les noms
  d'organisation servent de sélecteur complémentaire.
- **Pas de surveillance de surface d'exposition.** Pas de sélecteur IP ni de
  scan de ports (ce serait une action active, contraire à la règle 1).
- **Techniques d'attaque (TTP) : secondaire.** On ne relève que ce que
  l'attaquant déclare publiquement, rapporté à MITRE ATT&CK et marqué
  `declared, unverified`.

---

## 2. Règles non négociables

Ces règles priment sur toute demande de fonctionnalité. En cas de conflit, on
s'arrête et on demande.

1. **Observation uniquement.** Le système lit, détecte et alerte. Il ne doit
   jamais exploiter, déchiffrer ou tester des identifiants trouvés,
   désanonymiser des personnes, recontacter ou cibler des victimes, ni
   rediffuser des données fuitées.
2. **Jamais de donnée personnelle brute.** On ne stocke, ne journalise et ne
   transmet aucune valeur sensible en clair : seulement `value_masked`
   (affichage) et `value_hash` (corrélation). Les contrats de détection
   refusent tout champ imprévu (`extra="forbid"`).
3. **OPSEC réseau.** Tout le trafic de collecte passe par le conteneur Tor
   (réseau `collect_net`), jamais depuis l'IP de l'hôte. Rotation du circuit
   et du User-Agent, délais de politesse.
   - **On collecte depuis le dark web, on corrobore avec le clearnet.** Une
     source de collecte est un `.onion`. Un service clearnet n'est jamais une
     source, seulement un enrichisseur. Exception : les canaux Telegram
     publics, collectés via Tor.
   - Les **API d'enrichissement** (crt.sh, certspotter, HIBP, IntelX,
     RansomLook, ransomware.live) partent en clearnet du réseau applicatif.
     Seul un nom de groupe ou un domaine de sélecteur sort, jamais une
     valeur détectée.
4. **Pas de secret dans le code.** Tout passe par `.env`, qui n'est jamais
   versionné.
5. **Minimisation et traçabilité.** Les accès aux alertes sont journalisés.

Refus déjà tranchés : télécharger le contenu d'un lien de fuite pour
« vérifier » une fuite, résoudre ou contourner un dispositif anti-robot,
interroger des bots de recherche d'identifiants, utiliser HIBP Pwned Accounts,
collecter du doxxing de personnes privées.

---

## 3. Principes d'architecture

1. **Tranche verticale d'abord.** Une source, une détection, une alerte de
   bout en bout, puis on approfondit.
2. **Contrats figés entre couches.** Chaque frontière est un contrat Pydantic
   v2 (`backend/app/contracts/`).
3. **Logique pure séparée des tâches.**
   - `pipeline/` : logique métier pure, testable en isolation.
   - `worker/tasks/` : enveloppes fines qui appellent `pipeline/`.
   - `repositories/` : seul endroit qui parle à la base.
   Jamais de logique métier dans une tâche Celery ou un routeur d'API.
4. **Modèle de langue non bloquant.** Les appels au modèle de langue sont en
   bout de chaîne. Un modèle indisponible ne fait jamais échouer l'alerting
   ni un rapport.
5. **Mesurer avant de conclure.** Toute décision (source, règle, seuil)
   s'appuie sur une mesure. Un enrichissement en panne n'écrit rien plutôt
   que d'écrire un résultat faux.

---

## 4. Stack et conventions

- **Backend** : Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 et Alembic,
  PostgreSQL 16, Celery et Redis, Playwright (Patchright) via Tor, spaCy,
  ctranslate2 pour la traduction, Ollama pour le modèle de langue, fpdf2 pour
  les rapports, export STIX 2.1.
- **Frontend** : React 18, TypeScript strict, Vite, Tailwind, Three.js.
- **Base de données : jamais installée en local.** Tout passe par le service
  `db` de Docker Compose.
- **Nommage** : identifiants et code en anglais, commentaires et docstrings
  en français.
- **Qualité** : annotations de type partout, `ruff`, `black`, `mypy` sur le
  cœur, `tsc` et ESLint côté interface.
- **Tests** : `pytest`. Tout détecteur ou validateur a ses tests. Les tests
  d'intégration tournent dans une transaction annulée.
- **Migrations** : toute évolution du schéma passe par Alembic.

---

## 5. Structure du dépôt

```
backend/
  app/
    api/routers/    routeurs FastAPI, garde de rôle posée sur le routeur
    contracts/      contrats Pydantic entre couches
    core/           configuration, sécurité, rôles, modèle de langue
    db/models/      modèles SQLAlchemy
    repositories/   seuls accès à la base
    services/       orchestration (base, réseau, cache)
    pipeline/
      collect/      collecteurs : analyseurs de sites de fuite, forums, Telegram
      process/      nettoyage, langue, déduplication
      detect/       motifs, validateurs, masquage, classement des annonces
      classify/     arbitrage des annonces incertaines par le modèle de langue
      enrich/       corroboration, renseignements, géographie, presse
      alerting/     rattachement, gravité, crédibilité, Admiralty, résumés
      reporting/    rapports PDF, STIX 2.1, vues agrégées
      evaluation/   référence annotée, mesure d'avance
    worker/         Celery : application, ordonnanceur en base, tâches
    scripts/        commandes ponctuelles (création de compte, évaluation)
    tests/          unitaires et intégration
  alembic/          migrations
frontend/           interface React
tor/                image du proxy Tor
```

Flux d'une alerte, dans la tâche horaire `alerts.generate` et dans cet ordre :
localiser les victimes, générer les alertes, corroborer, renseigner (secteur,
date, pays), presse, crédibilité, corrections d'analyste, gravité. Chaque
enrichissement est non bloquant.

---

## 6. État du projet

Le code est la référence : chaque choix non évident est expliqué en
commentaire à l'endroit où il s'applique, avec la mesure qui l'a motivé.

---

## 7. Definition of Done

- [ ] Contrat de la couche respecté.
- [ ] Aucune donnée personnelle brute stockée ou journalisée.
- [ ] Tests écrits et verts, `ruff` et `black` passent.
- [ ] `docker compose up` démarre sans erreur.
- [ ] Logique métier dans `pipeline/`.
- [ ] Aucun secret versionné, `.env.example` à jour si une variable s'ajoute.

---

## 8. Pièges connus

- **Les workers n'ont pas le code monté.** Après une modification de code ou
  une migration, reconstruire `worker`, `worker-links`, `worker-dread` et
  `beat`, un service à la fois. Un simple `restart` relance l'ancienne image.
- **`.delay()` sans worker ne signale rien.** Un identifiant de tâche prouve
  seulement que Redis a reçu le message.
- **Une tâche longue a sa propre file** et ses limites de temps (modèle :
  `link_tasks.py`), sinon elle bloque la collecte et l'alerting.
- **Rattachement par labels pour un domaine, par égalité pour un nom,
  jamais par sous-chaîne.** `not-acme.com` ne correspond pas à `acme.com`.
- **Une détection n'est pas corroborable individuellement.** Seules sa forme
  masquée et son empreinte existent. On corrobore un domaine, jamais une
  valeur masquée.
- **Vérifier un lien n'est pas télécharger ce qu'il héberge.**
  `link_health.py` ne lit que le statut et l'en-tête de la page
  (`TestNoContentRapatriation`). `link_extraction.py` reste passif.
- **`validated` ne veut pas dire vérifié**, sauf pour `card` (Luhn) et
  `iban` (mod-97).
- **Un compteur variable dans `content` casse la déduplication** (vues,
  compte à rebours, statut). Il va dans `source_meta`.
- **Un analyseur est choisi sur l'hôte.** Un site qui change d'adresse sans
  alias retombe sur le collecteur générique sans erreur visible.
- **Mesurer sur la page entière et sur deux passes.** Un sélecteur vu sur un
  seul bloc, ou un échec Tor isolé, ne prouve rien.
- **`@with_retry` ne rejoue que sur exception**, et `dict.get(k, "")` ne
  remplace pas un `null` JSON : écrire `obj.get(k) or ""`.
- **Borner la portée et simuler d'abord.** Une opération globale ou
  destructrice accepte une liste d'identifiants, tourne en simulation par
  défaut et ne touche jamais une décision d'analyste.
- **Un tiers peut retirer un champ sans erreur.** Ne jamais ramener un champ
  absent à zéro : une absence de mesure n'est pas une mesure nulle.
- **Le texte d'un prompt est du code.** Le modifier impose de remesurer.
- **Mots de passe** : `hash_password` (HMAC poivré), jamais `hash_value`.
- **Celery Beat ne rattrape pas un créneau manqué** si l'hôte était éteint.

---

## 9. Méthode de travail

1. Lire ce fichier, en particulier les sections 2, 3 et 8.
2. Proposer un plan court avant une grosse tâche, avancer par petites étapes
   testées.
3. Ne pas figer une décision structurante (gravité, architecture réseau,
   contrats) sans la signaler pour validation.
4. Ne jamais installer PostgreSQL en local.
5. En cas de doute éthique, légal ou OPSEC : s'arrêter et demander.

---

## 10. Commandes utiles

```bash
docker compose up --build                                # démarre la stack
docker compose exec backend alembic upgrade head         # migrations
docker compose exec backend pytest                       # tests (make test)
docker compose exec backend sh -c "ruff check . && black --check ."
docker compose exec backend mypy                         # types du cœur
docker compose build worker && docker compose build worker-links && \
  docker compose build worker-dread && docker compose build beat
docker compose up -d --no-deps worker worker-links worker-dread beat
```
