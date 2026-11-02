"""Limitation des tentatives de connexion (2026-10-06).

Avant, `/api/auth/login` acceptait un nombre illimité d'essais : un mot de
passe se devinait sans autre limite que la vitesse d'argon2.

Deux compteurs dans Redis, sur une fenêtre glissante de 15 minutes :
- par COMPTE (5 échecs) : protège un compte précis ;
- par ADRESSE du client (20 échecs) : freine qui essaie beaucoup de comptes.

⚠️ L'adresse n'est conservée que HACHÉE et 15 minutes dans Redis, jamais en
base ni dans un journal (minimisation, règle 5).
⚠️ Redis indisponible : on LAISSE PASSER (et on le journalise). Bloquer toute
connexion parce que le cache est tombé ferait plus de dégâts que le risque
couvert.
⚠️ Le blocage par compte permet à un tiers de bloquer temporairement un
compte en échouant exprès : c'est le prix connu de cette mesure, borné à
15 minutes.
"""

from __future__ import annotations

import hashlib
import logging

from app.core.cache import get_redis

logger = logging.getLogger(__name__)

FENETRE_SECONDES = 15 * 60
MAX_PAR_COMPTE = 5
MAX_PAR_ADRESSE = 20


def _cles(username: str, adresse: str | None) -> list[tuple[str, int]]:
    compte = hashlib.sha256(username.strip().lower().encode()).hexdigest()[:32]
    cles = [(f"login_fail:user:{compte}", MAX_PAR_COMPTE)]
    if adresse:
        ip = hashlib.sha256(adresse.encode()).hexdigest()[:32]
        cles.append((f"login_fail:ip:{ip}", MAX_PAR_ADRESSE))
    return cles


def blocked_for(username: str, adresse: str | None) -> int:
    """Secondes avant de pouvoir réessayer, 0 si les tentatives sont permises."""
    try:
        r = get_redis()
        for cle, maximum in _cles(username, adresse):
            if int(r.get(cle) or 0) >= maximum:
                return max(1, int(r.ttl(cle) or FENETRE_SECONDES))
    except Exception:
        logger.warning("Limitation des connexions indisponible (Redis)", exc_info=True)
    return 0


def record_failure(username: str, adresse: str | None) -> None:
    try:
        r = get_redis()
        for cle, _ in _cles(username, adresse):
            n = r.incr(cle)
            if n == 1:
                r.expire(cle, FENETRE_SECONDES)
    except Exception:
        logger.warning("Limitation des connexions indisponible (Redis)", exc_info=True)


def record_success(username: str) -> None:
    """Un succès remet à zéro le compteur du COMPTE (pas celui de l'adresse)."""
    try:
        get_redis().delete(_cles(username, None)[0][0])
    except Exception:
        logger.warning("Limitation des connexions indisponible (Redis)", exc_info=True)
