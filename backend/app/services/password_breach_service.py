"""Passe de corroboration HIBP sur les mots de passe presents dans les
documents deja collectes (voir pipeline/enrich/hibp.py).

Repond a "les credentials detectes sont-ils du recyclage ou du nouveau ?" --
un mot de passe deja vu des milliers de fois dans des fuites connues indique
une combolist recyclee sans valeur ; un mot de passe inconnu de HIBP sur un
domaine surveille est un signal bien plus fort (fuite potentiellement
recente et specifique).

**Pourquoi une passe qui relit les documents, et pas un traitement des
detections existantes** : une detection `credentials` ne conserve que
`value_masked` (`au****...87`) et un HMAC non reversible. Le mot de passe en
clair n'existe nulle part en base -- c'est la regle 2, et c'est voulu.
Interroger HIBP exige le clair. Le seul endroit ou il existe encore est le
**texte du document collecte**, d'ou cette passe qui le re-extrait en memoire.

**Le clair ne survit jamais a la fonction** : il est extrait, hache en SHA-1
pour la requete k-anonymity (5 caracteres transmis), puis abandonne. Aucun
retour, aucun log, aucune persistance -- les resultats sont agreges par
comptage, jamais par valeur.

Ne persiste rien (choix assume, comme IntelX/crt.sh) : le resultat est
retourne a l'appelant qui l'affiche. Aucune migration, le contrat
`DetectionContract` (extra="forbid") reste intact."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models.raw_document import RawDocument
from app.pipeline.enrich.hibp import HibpLookupError, check_password

logger = logging.getLogger(__name__)

# Meme motif que pipeline/detect/patterns/credentials.py -- duplique
# volontairement plutot qu'importe : ce module a besoin du groupe de capture
# du mot de passe (que find_credentials ne renvoie jamais, par conception).
_EMAIL_PASSWORD_RE = re.compile(
    r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}):([^\s:]{4,})\b"
)

# Plafond de requetes par execution. HIBP est gratuit et sans quota strict,
# mais reste un service tiers benevole : une passe non bornee sur un corpus
# grandissant reviendrait a le marteler.
_MAX_LOOKUPS_PER_RUN = 200


@dataclass(frozen=True)
class PasswordBreachReport:
    """Comptages agreges. Ne contient aucun mot de passe ni aucun hash --
    seulement des nombres."""

    documents_scanned: int
    credentials_found: int
    unique_passwords: int
    passwords_checked: int
    breached_count: int
    unknown_count: int
    lookup_errors: int
    # Repartition des mots de passe compromis par tranche d'apparitions, pour
    # distinguer "recyclage massif" (vu des millions de fois) de "fuite ciblee"
    # (vu quelques fois seulement).
    breach_buckets: dict[str, int]

    @property
    def breached_ratio(self) -> float | None:
        """Part des mots de passe deja connus de HIBP. `None` si rien n'a ete
        verifie (pas 0.0 : "aucune mesure" n'est pas "aucun compromis")."""
        if not self.passwords_checked:
            return None
        return self.breached_count / self.passwords_checked


def _bucket_for(count: int) -> str:
    if count >= 100_000:
        return "100k+"
    if count >= 1_000:
        return "1k-100k"
    if count >= 10:
        return "10-1k"
    return "1-10"


def check_corpus_passwords(
    db: Session, *, source_id=None, limit_documents: int | None = None
) -> PasswordBreachReport:
    """Extrait les mots de passe des documents collectes et interroge HIBP.

    Les mots de passe sont dedupliques **par leur valeur en clair, en memoire
    uniquement** (un `set` local, detruit a la sortie de la fonction) : une
    combolist repete souvent le meme mot de passe, l'interroger une fois
    suffit et divise d'autant le trafic vers HIBP."""
    query = db.query(RawDocument.content)
    if source_id is not None:
        query = query.filter(RawDocument.source_id == source_id)
    if limit_documents is not None:
        query = query.order_by(RawDocument.fetched_at.desc()).limit(limit_documents)

    documents_scanned = 0
    credentials_found = 0
    # Vit uniquement dans cette portee -- jamais retourne, jamais logge.
    unique_passwords: set[str] = set()

    for (content,) in query.all():
        documents_scanned += 1
        for match in _EMAIL_PASSWORD_RE.finditer(content or ""):
            credentials_found += 1
            unique_passwords.add(match.group(2))

    to_check = sorted(unique_passwords)[:_MAX_LOOKUPS_PER_RUN]
    if len(unique_passwords) > _MAX_LOOKUPS_PER_RUN:
        logger.warning(
            "Corroboration HIBP tronquee: %d mots de passe uniques, plafond %d",
            len(unique_passwords),
            _MAX_LOOKUPS_PER_RUN,
        )

    breached_count = 0
    lookup_errors = 0
    breach_buckets: dict[str, int] = {}

    for password in to_check:
        try:
            result = check_password(password)
        except HibpLookupError:
            # Un echec ponctuel ne doit pas interrompre la passe -- il est
            # compte et signale dans le rapport. Pas de `exc_info` : la trace
            # pourrait contenir l'URL interrogee (donc le prefixe).
            lookup_errors += 1
            continue
        if result.is_breached:
            breached_count += 1
            bucket = _bucket_for(result.breach_count)
            breach_buckets[bucket] = breach_buckets.get(bucket, 0) + 1

    passwords_checked = len(to_check) - lookup_errors
    logger.info(
        "Corroboration HIBP: %d document(s), %d credential(s), %d mot(s) de passe "
        "unique(s), %d verifie(s), %d compromis",
        documents_scanned,
        credentials_found,
        len(unique_passwords),
        passwords_checked,
        breached_count,
    )

    return PasswordBreachReport(
        documents_scanned=documents_scanned,
        credentials_found=credentials_found,
        unique_passwords=len(unique_passwords),
        passwords_checked=passwords_checked,
        breached_count=breached_count,
        unknown_count=max(passwords_checked - breached_count, 0),
        lookup_errors=lookup_errors,
        breach_buckets=breach_buckets,
    )
