"""Niveau de credibilite d'une alerte (plan de credibilite, phase 5).

Repond a « la fuite est-elle reelle ? », une question DISTINCTE de la gravite
(« quel impact si elle l'est ? ») : une confirmation par la presse ne rend pas
une fuite plus grave, elle la rend plus sure. Les deux axes ne se melangent
pas -- une echelle unique s'est effondree en constante a quatre reprises.

Chaque niveau porte sa PREUVE, affichee avec lui : un niveau sans preuve
consultable ne serait qu'une affirmation de plus.

Ordre de decision (le premier qui s'applique l'emporte) :

  confirmed    article de presse / declaration officielle (phase 1) -- seule
               preuve exterieure au gang ; aucun doute ne la dement.
  doubtful     lien de telechargement mort alors qu'il etait annonce
               (phase 3).
               ⚠️ Les revendications MULTIPLES (phase 4) ne rendent PAS une
               alerte douteuse -- mesure du 2026-09-30, voir
               `claim_history.py` : ce sont des republications (la fuite est
               reelle, c'est sa nouveaute qui est fausse) ou des attributions
               disputees (l'incident est reel, c'est l'auteur qui est
               incertain). Elles deviennent des QUALIFICATIFS de la preuve,
               sans changer le niveau.
               `download_link_gone` reste NON alimente, et c'est une decision
               MESUREE (2026-09-30), pas un oubli : les liens externes cites
               dans les documents des victimes alertees sont leurs PROPRES
               sites (domaine-exemple.co.za, telecom-exemple.ma...) et LinkedIn, jamais
               une archive de dump -- celle-ci vit sur le .onion du gang (meme
               hote que le document, exclu) ou en torrent/JS. Verifier la
               vivacite du site de la victime ne dit RIEN de la realite de la
               fuite. Le signal ne redeviendrait utile que pour des annonces
               de FORUM (« dump sur mega.nz/... »), hors de notre perimetre
               geographique. La regle reste ecrite et testee pour ne pas avoir
               a changer d'echelle si une telle source entre un jour.
  published    le site du gang affiche les donnees comme mises en ligne
               (phase 2).
  claimed      annonce seule : victime en attente de publication (menace),
               statut non expose par le site, ou annonce de forum.
  not_evaluated aucun document source.

⚠️ `published` reste une DECLARATION DU GANG (« les donnees sont en ligne »),
jamais une verification : le projet ne telecharge pas le contenu des fuites.
Elle pese plus qu'une simple annonce parce qu'elle est verifiable par un
tiers, pas parce que nous l'avons verifiee.

⚠️ VALIDATION MESUREE (phase 6, 2026-09-24) : `published` N'EST PAS un
predicteur etabli de confirmation exterieure. Contre la presse
(`app.scripts.evaluate_credibility`, 1 350 victimes, 69 confirmees) : 5,7 %
des victimes publiees contre 3,3 % des victimes en attente, Fisher p = 0,47 ;
ajuste sur le gang, rapport de cotes 0,32, IC95 [0,05-2,19] -- l'intervalle
contient 1. La presse suit le GANG (LockBit 47 des 69 cas), pas le statut.
`published` reste donc un CONSTAT (le site l'affiche), jamais un score : ne
pas le presenter comme « plus credible » sans nouvelle mesure.

Logique pure : aucune base, aucun reseau.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Credibility(str, Enum):
    CONFIRMED = "confirmed"
    DOUBTFUL = "doubtful"
    PUBLISHED = "published"
    CLAIMED = "claimed"
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class CredibilityInput:
    """Faits observes sur une alerte, deja agreges par victime."""

    has_documents: bool
    press_confirmed: bool = False
    # Meilleur statut parmi TOUS les documents de la victime (meme source,
    # meme URL) -- pas seulement ceux qui portent la detection : la
    # completion des descriptions cree un second document par victime.
    publication_status: str | None = None
    publication_evidence: str | None = None
    publication_source: str | None = None
    # Phase 3 ; None = non mesure, JAMAIS « sain ».
    download_link_gone: bool | None = None
    from_victim_site: bool = False
    # Phase 4, qualificatifs (voir claim_history.py) -- vide = rien observe OU
    # non mesure, jamais « revendication unique prouvee ».
    # (victime, gang d'origine, date AAAA-MM-JJ de sa publication)
    republications: tuple[tuple[str, str, str], ...] = ()
    # (victime, autres gangs l'ayant publiee a moins de 30 jours de nous)
    disputes: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class CredibilityResult:
    level: Credibility
    evidence: str


#: Au-dela, les qualificatifs sont resumes : la preuve est tronquee a 500
#: caracteres en base, et une liste coupee au milieu d'un nom serait fausse.
MAX_QUALIFIERS = 3


def qualifiers(faits: CredibilityInput) -> list[str]:
    """Republications et attributions disputees, formulees pour l'analyste."""
    textes = [
        f"republication : {victime} déjà revendiquée par {gang} le {date}"
        for victime, gang, date in faits.republications
    ]
    textes += [
        f"attribution disputée : {victime} ({', '.join(gangs)})"
        for victime, gangs in faits.disputes
    ]
    if len(textes) > MAX_QUALIFIERS:
        reste = len(textes) - MAX_QUALIFIERS
        textes = textes[:MAX_QUALIFIERS] + [f"et {reste} autre(s)"]
    return textes


def assess(faits: CredibilityInput) -> CredibilityResult:
    """Niveau de credibilite et sa preuve, suivie des qualificatifs de
    revendication (phase 4). Les qualificatifs ne changent JAMAIS le niveau :
    voir la docstring du module."""
    resultat = _niveau(faits)
    if resultat.level is Credibility.NOT_EVALUATED:
        return resultat
    extra = qualifiers(faits)
    if not extra:
        return resultat
    return CredibilityResult(
        resultat.level, resultat.evidence + " ; " + " ; ".join(extra)
    )


def _niveau(faits: CredibilityInput) -> CredibilityResult:
    """Niveau et preuve principale. Voir l'ordre dans la docstring du module."""
    if not faits.has_documents:
        return CredibilityResult(
            Credibility.NOT_EVALUATED, "aucun document source rattache"
        )
    if faits.press_confirmed:
        return CredibilityResult(
            Credibility.CONFIRMED,
            "incident rapporté par la presse ou une déclaration officielle",
        )
    if faits.download_link_gone:
        return CredibilityResult(
            Credibility.DOUBTFUL,
            "le lien de téléchargement annoncé ne répond plus",
        )
    chez = f" ({faits.publication_source})" if faits.publication_source else ""
    if faits.publication_status == "published":
        return CredibilityResult(
            Credibility.PUBLISHED,
            f"le site du groupe affiche les données comme publiées{chez}"
            + (
                f" : {faits.publication_evidence}" if faits.publication_evidence else ""
            ),
        )
    if faits.publication_status == "pending":
        return CredibilityResult(
            Credibility.CLAIMED,
            f"menace : publication annoncée, pas encore effective{chez}"
            + (
                f" : {faits.publication_evidence}" if faits.publication_evidence else ""
            ),
        )
    if faits.from_victim_site:
        return CredibilityResult(
            Credibility.CLAIMED,
            f"victime annoncée, statut de publication non exposé par le site{chez}",
        )
    return CredibilityResult(
        Credibility.CLAIMED, "annonce publiée sur un forum, non vérifiée"
    )
