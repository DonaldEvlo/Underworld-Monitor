from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class SelectorType(str, Enum):
    """Type d'un selecteur d'entite surveillee (voir CONTRIBUTING.md §1 Perimetre).

    Volontairement pas d'IP : repoussee du MVP (scan de surface = actif,
    contraire a la regle d'observation seule). `domain`/`email_domain`
    portent 83% du signal reel observe sur le corpus (domain 61% + email
    22%), `keyword` couvre le reste (nom de marque, alias...)."""

    DOMAIN = "domain"
    EMAIL_DOMAIN = "email_domain"
    KEYWORD = "keyword"


class VerificationMethod(str, Enum):
    """Comment la preuve-de-controle d'une entite a ete etablie."""

    DNS_TXT = "dns_txt"
    MANUAL = "manual"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


class EntitySelector(BaseModel):
    """Un critere de rattachement d'une detection a une entite.

    `value` est un identifiant public declare par l'entite elle-meme (son
    domaine, un mot-cle de marque...), pas une donnee de tiers -- rien a
    masquer ici (voir CONTRIBUTING.md règle 2, qui concerne les *detections*, pas
    les selecteurs). Le matching effectif (normalisation, comparaison par
    labels de domaine plutot que sous-chaine) est la responsabilite de
    `pipeline/`, pas de ce contrat -- voir CONTRIBUTING.md §8.
    """

    model_config = {"extra": "forbid"}

    type: SelectorType
    value: str


class EntityContract(BaseModel):
    """Une entite surveillee, generique (voir CONTRIBUTING.md §1 : jamais de nom
    d'organisation en dur dans le code -- `name` est une donnee, pas une
    constante).

    `selectors` est une liste extensible de criteres typés
    (`EntitySelector`) plutot que des champs `domain`/`email_domain` fixes
    sur ce contrat : une entite peut declarer plusieurs domaines ou
    mots-cles sans multiplier les champs, et un type de selecteur
    supplementaire s'ajoute a `SelectorType` sans casser ce contrat.

    La preuve-de-controle (`verification_*`) est portee au niveau de
    l'entite entiere, pas par selecteur : un statut global suffit pour ce
    MVP (voir CONTRIBUTING.md §6 priorite n°1).
    """

    model_config = {"extra": "forbid"}

    id: UUID
    name: str
    active: bool = True
    selectors: list[EntitySelector]

    verification_method: VerificationMethod | None = None
    verification_status: VerificationStatus = VerificationStatus.PENDING
    verified_at: datetime | None = None

    # Migration 0033 (2026-10-05) -- ⚠️ modification d'un contrat réel, pour
    # une raison forte : les multinationales (Acme au Sénégal, au Mali…).
    # `parent_id` relie une filiale à son groupe ; `country` et `sector` sont
    # DÉCLARÉS par l'analyste et priment sur ceux d'un tiers. Tous optionnels :
    # aucun producteur existant n'est cassé.
    parent_id: UUID | None = None
    country: str | None = None
    sector: str | None = None

    created_at: datetime
