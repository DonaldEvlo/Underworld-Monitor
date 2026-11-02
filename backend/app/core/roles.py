"""Roles et droits d'acces -- socle de la separation des profils.

⚠️ AVANT CE MODULE, IL N'Y AVAIT AUCUN ROLE. La table `users` ne portait que
`username`, `password_hash`, `active`, `created_at` : **tout utilisateur
authentifie accedait aux 80 endpoints**, y compris vider les alertes et
supprimer une source. Les trois profils du dossier de conception (analyste
SOC/CERT, administrateur, RSSI) decrivaient une cible, pas l'implementation.

Trois roles, et la frontiere entre eux n'est pas administrative mais
DOCTRINALE :

  - `analyst`  -- le poste de travail. Consulte, qualifie, investigue. C'est
    lui qui a besoin de la VERIFIABILITE : remonter de l'alerte au document
    d'origine. Il voit donc le corpus.
  - `admin`    -- installe, configure, maintient. Tout ce que fait l'analyste,
    PLUS la configuration : sources, planification, comptes, operations
    destructrices.
  - `viewer`   -- RSSI / decideur. ⚠️ **Ne voit PAS le detail des contenus**,
    par conception et non par oubli : le dossier de conception pose qu'il
    « ne consulte pas le detail des contenus » et attend « une vue agregee ».
    Lui ouvrir le corpus reviendrait a exposer des valeurs masquees et des
    adresses `.onion` a quelqu'un qui n'en a pas l'usage -- exactement le
    contraire de la minimisation (regle 5).

⚠️ LE DEFAUT EST `analyst`, PAS `admin`. Un compte cree sans role explicite ne
doit pas pouvoir supprimer des sources. Moindre privilege : le role qui
administre se donne, il ne s'herite pas.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    ANALYST = "analyst"
    ADMIN = "admin"
    VIEWER = "viewer"


# Role par defaut d'un compte cree sans precision -- voir l'avertissement en
# tete de module.
DEFAULT_ROLE = Role.ANALYST

# ⚠️ L'ADMIN N'EST PAS UN SUR-ANALYSTE PAR MAGIE : l'inclusion est ecrite ici,
# explicitement, parce qu'un `Depends` qui compare une egalite stricte
# exclurait l'administrateur de son propre outil. Le VIEWER n'est inclus nulle
# part ailleurs que dans la vue agregee : son perimetre est une RESTRICTION,
# pas un sous-ensemble de confort.
PEUT_TRAITER_LES_ALERTES = frozenset({Role.ANALYST, Role.ADMIN})
PEUT_VOIR_LE_CORPUS = frozenset({Role.ANALYST, Role.ADMIN})
PEUT_ADMINISTRER = frozenset({Role.ADMIN})
TOUS = frozenset({Role.ANALYST, Role.ADMIN, Role.VIEWER})


def role_de(valeur: str | None) -> Role:
    """Role d'un utilisateur, tolerant a une valeur inconnue en base.

    ⚠️ Une valeur non reconnue retombe sur le role le MOINS puissant, jamais
    sur `admin`. Une ligne alteree ou un futur role non deploye ne doit pas
    ouvrir l'administration -- c'est la meme doctrine que la liste blanche
    d'actions planifiables, ou une entree inconnue est ignoree plutot
    qu'executee."""
    try:
        return Role(str(valeur or "").strip().lower())
    except ValueError:
        return Role.VIEWER
