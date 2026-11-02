"""Masquage de valeurs sensibles avant stockage/affichage/log. Logique pure
(voir CONTRIBUTING.md). Regle non negociable du projet : aucune PII brute stockee ni
loggee -- seuls `value_masked` (affichage) et `value_hash` (correlation, voir
hash_value ci-dessous) circulent au-dela de cette fonction. Un detecteur ne
doit JAMAIS retourner la valeur brute matchee, uniquement le resultat de ces
deux fonctions.
"""

import hashlib
import hmac

from app.core.config import settings


def hash_value(value: str) -> str:
    """SHA-256 de la valeur brute, pour deduplication/correlation (deux
    detections du meme secret partagent le meme hash) sans jamais reexposer
    la valeur elle-meme.

    Convient aux valeurs a forte entropie (email, IBAN, domaine, wallet) ou
    l'espace des valeurs possibles est trop grand pour etre enumere. **Ne
    convient PAS a un mot de passe** -- voir hash_password ci-dessous."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(value: str) -> str:
    """HMAC-SHA256 poivre d'un mot de passe, pour correlation.

    Pourquoi pas `hash_value` : un mot de passe humain a une entropie faible.
    `sha256("azerty123")` se retrouve instantanement dans une rainbow table ou
    par dictionnaire -- "hache" n'y signifie pas "protege". Le poivre
    (PASSWORD_HASH_PEPPER, stocke HORS base, voir core/config.py) casse cette
    attaque : sans lui, un dump de la table `detections` ne permet pas de
    tester des candidats.

    Poivre plutot que sel : le sel (par valeur, stocke a cote) protege contre
    les rainbow tables mais empeche justement la correlation qu'on cherche ici
    (deux occurrences du meme mot de passe doivent partager le meme hash). Un
    poivre global conserve cette propriete tout en restant secret.

    Ce hash est distinct du SHA-1 k-anonymity de pipeline/enrich/hibp.py :
    celui-la est calcule en memoire pour interroger l'API et jamais persiste,
    celui-ci est persiste et jamais transmis. Ne pas les confondre."""
    pepper = settings.PASSWORD_HASH_PEPPER
    if not pepper:
        # Echouer bruyamment plutot que retomber silencieusement sur un hash
        # non poivre : un mot de passe stocke avec une protection degradee
        # sans que personne ne le sache est pire qu'une erreur visible.
        raise ValueError(
            "PASSWORD_HASH_PEPPER n'est pas configure -- impossible de hacher "
            "un mot de passe sans poivre (voir .env.example)"
        )
    return hmac.new(
        pepper.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def mask_email(value: str) -> str:
    """j***@exemple.com -- garde le premier caractere local + le domaine (utile
    a l'analyste pour distinguer deux emails differents sans les reidentifier)."""
    local, _, domain = value.partition("@")
    if not domain:
        return mask_generic(value)
    visible = local[0] if local else ""
    return f"{visible}***@{domain}"


def mask_card(value: str) -> str:
    """4***-****-****-1234 -- garde les 4 premiers et les 4 derniers chiffres
    (format standard d'affichage carte, ne permet pas de reconstituer le PAN)."""
    digits = [c for c in value if c.isdigit()]
    if len(digits) < 8:
        return mask_generic(value)
    return f"{''.join(digits[:1])}***-****-****-{''.join(digits[-4:])}"


def mask_iban(value: str) -> str:
    """FR**...****1234 -- garde le code pays + les 4 derniers caracteres."""
    cleaned = value.replace(" ", "")
    if len(cleaned) < 8:
        return mask_generic(value)
    country = cleaned[:2]
    return f"{country}{'*' * (len(cleaned) - 6)}{cleaned[-4:]}"


def mask_generic(value: str) -> str:
    """Repli pour toute valeur trop courte pour un masquage specifique, ou pour
    les types sans regle dediee (api_key, crypto_wallet...) : garde les 2
    premiers et 2 derniers caracteres, masque le reste."""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


def mask_domain(value: str) -> str:
    """Un domaine n'est pas une PII (voir pipeline/detect/patterns/domain.py) :
    contrairement a mask_generic, reste lisible meme pour les valeurs courtes
    -- masquer un domaine legitime de 6 caracteres en "******" (constate
    empiriquement sur "ibb.co") ne protege personne et rend la detection
    inutilisable pour l'analyste. Les .onion (56 caracteres, illisibles de
    toute facon en clair) gardent un masquage partiel pour rester distinguables
    entre eux sans encombrer l'affichage."""
    if value.endswith(".onion"):
        prefix = value[: -len(".onion")]
        return f"{prefix[:8]}...{prefix[-4:]}.onion"
    return value
