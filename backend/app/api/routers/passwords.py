"""Corroboration HIBP des mots de passe presents dans le corpus collecte.

Repond a "ces credentials sont-ils du recyclage ou du nouveau ?" -- voir
services/password_breach_service.py. Ne persiste rien : le resultat est
calcule et retourne, jamais stocke (meme regime qu'IntelX et crt.sh).

Ne remonte que des **comptages agreges** : jamais un mot de passe, jamais un
hash, jamais la liste des credentials concernes. Un analyste apprend ici
"62 % des mots de passe du corpus sont deja dans des fuites connues", pas
lesquels -- ce qui suffit a juger de la fraicheur d'une combolist sans
reexposer quoi que ce soit (CONTRIBUTING.md §2)."""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.roles import PEUT_ADMINISTRER
from app.api.deps import exige_role, get_db
from app.services.password_breach_service import check_corpus_passwords

router = APIRouter(
    prefix="/api/passwords",
    tags=["passwords"],
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)

# Borne du declenchement manuel : chaque mot de passe unique coute un appel
# HIBP, et l'appelant attend le resultat.
_MAX_DOCUMENTS = 500


class PasswordBreachResponse(BaseModel):
    model_config = {"extra": "forbid"}

    documents_scanned: int
    credentials_found: int
    unique_passwords: int
    passwords_checked: int
    breached_count: int
    unknown_count: int
    lookup_errors: int
    breached_ratio: float | None
    # Repartition par tranche d'apparitions : "100k+" = recyclage massif,
    # "1-10" = mot de passe rare, signal bien plus fort.
    breach_buckets: dict[str, int]


@router.post("/check-breaches", response_model=PasswordBreachResponse)
def check_breaches(
    db: Session = Depends(get_db),
    source_id: uuid.UUID | None = None,
    limit_documents: int = Query(default=100, ge=1, le=_MAX_DOCUMENTS),
) -> PasswordBreachResponse:
    """Extrait les mots de passe des documents recents et interroge HIBP par
    k-anonymity (voir pipeline/enrich/hibp.py).

    Le mot de passe en clair ne quitte jamais le serveur : seuls les 5
    premiers caracteres de son SHA-1 sont transmis a HIBP, la comparaison se
    fait localement. L'API "Pwned Accounts" (qui exigerait d'envoyer une
    adresse email en clair) est volontairement exclue du projet."""
    report = check_corpus_passwords(
        db, source_id=source_id, limit_documents=limit_documents
    )
    return PasswordBreachResponse(
        documents_scanned=report.documents_scanned,
        credentials_found=report.credentials_found,
        unique_passwords=report.unique_passwords,
        passwords_checked=report.passwords_checked,
        breached_count=report.breached_count,
        unknown_count=report.unknown_count,
        lookup_errors=report.lookup_errors,
        breached_ratio=report.breached_ratio,
        breach_buckets=report.breach_buckets,
    )
