"""Notation Admiralty (code OTAN / NATO System) et marquage TLP.

Le vocabulaire standard du renseignement, pour que l'alerte parle la langue
d'un analyste CTI : une LETTRE pour la fiabilite de la SOURCE (A-F), un
CHIFFRE pour la credibilite de l'INFORMATION (1-6). « B2 » = source
habituellement fiable, information probablement vraie.

Logique PURE. Rien n'est invente : la lettre vient de l'HISTORIQUE mesure de
la source, le chiffre de l'axe credibilite deja calcule
(`credibility.py`). Pas de migration -- calcule a la volee, comme la
geographie : une valeur persistee deviendrait fausse en silence au premier
ajustement des seuils.

⚠️ JAMAIS « A » (completement fiable). Meme un site de fuite dont 100 % des
victimes sont confirmees publie des REVENDICATIONS D'ATTAQUANTS, qui ont
interet a exagerer. Et la confirmation vient d'agregateurs qui lisent le MEME
site : elle prouve que l'annonce existe et que notre lecture est juste, pas
que la fuite est reelle (« couverture, pas independance », 2026-09-15).

⚠️ « F » N'EST PAS « MAUVAIS ». F = « la fiabilite ne peut pas etre jugee » :
un forum n'a pas d'historique mesurable par la corroboration (les domaines
cites n'y sont pas des victimes revendiquees), une source recente pas assez.
Le confondre avec « E, non fiable » serait affirmer ce qu'on n'a pas mesure.

⚠️ Le chiffre 2 (« probablement vraie ») repose sur la PUBLICATION par le
groupe + une confirmation. La validation du 2026-09-24 (phase 6) n'a pas
etabli que « publiee » predise mieux la confirmation par la presse
(Fisher p = 0,47). Le chiffre decrit donc des FAITS CONCORDANTS, il ne pretend
pas a une probabilite mesuree.
"""

from __future__ import annotations

from dataclasses import dataclass

# Seuils sur l'historique de la source (part de ses victimes confirmees par
# un agregateur). Mesure du 2026-09-26 : les sites de fuite actifs sont a
# 90-100 %, ORION a 63 %.
SEUIL_B = 0.90
SEUIL_C = 0.50
MIN_EVALUEES_B = 20
MIN_EVALUEES = 10

SOURCE_LABELS = {
    "A": "complètement fiable",
    "B": "habituellement fiable",
    "C": "assez fiable",
    "D": "pas toujours fiable",
    "E": "non fiable",
    "F": "fiabilité non évaluable",
}
INFO_LABELS = {
    1: "confirmée par d'autres sources",
    2: "probablement vraie",
    3: "possiblement vraie",
    4: "douteuse",
    5: "improbable",
    6: "véracité non évaluable",
}
_ORDRE_SOURCE = "ABCDEF"

# ⚠️ TLP 2.0 (FIRST) : AMBER+STRICT = diffusion limitee a l'organisation
# destinataire. Le rapport s'adresse a la SEULE victime : il ne doit pas
# circuler chez ses partenaires ou clients sans son accord.
TLP_RAPPORT = "TLP:AMBER+STRICT"
TLP_DEFINITION = (
    "Diffusion limitée à l'organisation destinataire, sur la base du besoin "
    "d'en connaître (FIRST TLP 2.0)."
)


@dataclass(frozen=True)
class SourceTrack:
    """Historique d'une source, tel que mesure en base."""

    publishes_victims: bool
    evaluated: int = 0
    corroborated: int = 0


@dataclass(frozen=True)
class Grade:
    valeur: str
    motif: str


def source_reliability(track: SourceTrack) -> Grade:
    if not track.publishes_victims:
        return Grade(
            "F",
            "forum ou canal : aucun historique mesurable de revendications "
            "confirmées",
        )
    if track.evaluated < MIN_EVALUEES:
        return Grade("F", f"historique trop court ({track.evaluated} victime(s))")
    taux = track.corroborated / track.evaluated
    detail = (
        f"{track.corroborated}/{track.evaluated} victimes confirmées par un "
        f"agrégateur ({taux:.0%})"
    )
    if taux >= SEUIL_B and track.evaluated >= MIN_EVALUEES_B:
        return Grade("B", detail)
    if taux >= SEUIL_C:
        return Grade("C", detail)
    return Grade("D", detail)


def best_source(grades: list[Grade]) -> Grade | None:
    """La meilleure lettre parmi les sources d'une alerte."""
    if not grades:
        return None
    return min(grades, key=lambda g: _ORDRE_SOURCE.index(g.valeur))


def information_credibility(
    credibility_level: str | None,
    corroborated: bool,
    from_victim_site: bool,
) -> Grade:
    """Chiffre 1-6, depuis l'axe credibilite (credibility.py)."""
    if credibility_level == "confirmed":
        return Grade("1", "incident rapporté par la presse ou un communiqué")
    if credibility_level == "doubtful":
        return Grade("4", "élément contradictoire relevé")
    if credibility_level == "published" and corroborated:
        return Grade(
            "2", "données publiées par le groupe, annonce confirmée par un agrégateur"
        )
    if credibility_level == "published":
        return Grade("3", "données publiées par le groupe, sans autre confirmation")
    if credibility_level == "claimed" and from_victim_site:
        return Grade("3", "revendication sur le site du groupe")
    if credibility_level == "claimed":
        return Grade("6", "annonce de forum non confirmée")
    return Grade("6", "crédibilité non évaluée")


@dataclass(frozen=True)
class AdmiraltyRating:
    source: Grade
    source_name: str | None
    information: Grade

    @property
    def code(self) -> str:
        return f"{self.source.valeur}{self.information.valeur}"

    def libelle(self) -> str:
        return (
            f"{self.code} -- source {SOURCE_LABELS[self.source.valeur]}, "
            f"information {INFO_LABELS[int(self.information.valeur)]}"
        )
