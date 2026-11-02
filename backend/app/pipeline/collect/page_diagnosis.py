"""Pourquoi une page n'a rien donne : la source est-elle morte, verrouillee,
ou a-t-elle simplement change de structure ?

⚠️ RAISON D'ETRE, mesuree le 2026-09-04. L'interface annoncait « Aucun contenu
recupere (source injoignable ou vide) » pour DRAGON FORCE et XSSF. Les deux
repondaient parfaitement :
  - DRAGON FORCE servait un avis « Migration completed » signe PGP annoncant
    sa nouvelle adresse (18,9 Ko) ;
  - XSSF servait une page « Access Verification » avec un CAPTCHA (11,5 Ko).
Deux situations opposees -- l'une se corrige en une minute, l'autre ne se
corrige pas du tout -- rendues indiscernables par un message unique. Un
diagnostic faux coute plus cher qu'une absence de diagnostic : on cherche une
panne reseau la ou le site a demenage.

Ce module ne fait que LIRE et qualifier. Il ne contourne rien : reconnaitre un
CAPTCHA sert a l'annoncer et a s'arreter, jamais a le resoudre (regle 1).
"""

from __future__ import annotations

import re

# Adresse .onion v3 : 56 caracteres en base32.
_ONION = re.compile(r"\b[a-z2-7]{56}\.onion\b")
_TITRE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# ⚠️ L'ordre compte : une page de migration peut mentionner « login », et une
# page de captcha mentionne souvent « javascript ». Le motif le plus specifique
# doit trancher en premier.
_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    (
        "anti-bot",
        (
            "captcha",
            "ddos protection",
            "verify that you're human",
            "are you human",
            # ⚠️ Barriere par EMPREINTE DE NAVIGATEUR, mesuree le 2026-10-08
            # sur le DLS de « the gentlemen » : aucun captcha, aucun
            # formulaire -- une page de 8 150 octets titree « Gentlecloud
            # Protection » qui calcule une empreinte en JavaScript puis
            # appelle `/challenge/get_challenge`. Sans ces marqueurs, le
            # diagnostic rendu etait « structure probablement modifiee » :
            # on aurait cherche un correctif de parser pour une barriere
            # qu'on ne franchira jamais (regle 1).
            "verifying your browser",
            "browser verification",
            "get_challenge",
        ),
    ),
    ("migration", ("migration completed", "we have moved", "new address", "moved to")),
    ("cloudflare", ("cloudflare", "cf-browser-verification", "attention required")),
    ("connexion", ("password", "log in to continue", "you must be logged in")),
    ("javascript", ("enable javascript", "javascript is required")),
]


def _titre(html: str) -> str:
    trouve = _TITRE.search(html or "")
    return " ".join(trouve.group(1).split())[:120] if trouve else ""


def diagnostiquer_page(html: str | None) -> str:
    """Une phrase expliquant pourquoi cette page n'a rien donne.

    Toujours factuelle : elle decrit ce qui a ete servi, jamais ce qu'il
    faudrait faire pour passer outre.
    """
    if not html or not html.strip():
        return "Aucune réponse du serveur (source injoignable)"

    minuscules = html.lower()
    titre = _titre(html)
    suffixe = f" — page servie : « {titre} »" if titre else ""

    for nature, marqueurs in _SIGNATURES:
        if not any(m in minuscules for m in marqueurs):
            continue
        if nature == "anti-bot":
            # ⚠️ Constat, pas obstacle a franchir : le projet ne resout jamais
            # un anti-bot (regle 1). Le dire clairement evite qu'on cherche
            # une panne, et evite qu'on tente de le contourner.
            return (
                "Le site répond mais exige une vérification anti-bot "
                f"(CAPTCHA ou empreinte de navigateur){suffixe}. "
                "Non contournable : la collecte s'arrête ici"
            )
        if nature == "migration":
            adresses = sorted(set(_ONION.findall(html)))
            nouvelle = f" Nouvelle adresse annoncée : {adresses[0]}" if adresses else ""
            return (
                f"Le site a déménagé et ne sert plus qu'un avis de migration{suffixe}."
                f"{nouvelle}"
            )
        if nature == "cloudflare":
            return f"Le site répond derrière une protection Cloudflare{suffixe}"
        if nature == "connexion":
            return f"Le site répond mais exige une authentification{suffixe}"
        if nature == "javascript":
            return (
                "Le site répond mais exige un navigateur (JavaScript) — le "
                f"collecteur utilisé lit du HTML brut{suffixe}"
            )

    # ⚠️ Cas le plus insidieux : la page est servie, complete, mais le parser
    # n'y reconnait plus rien. C'est un changement de structure du site, pas
    # une panne -- et cela demande un correctif de code, pas une nouvelle
    # tentative.
    return (
        f"Le site a répondu ({len(html)} octets) mais aucun contenu exploitable "
        f"n'y a été reconnu — structure probablement modifiée{suffixe}"
    )
