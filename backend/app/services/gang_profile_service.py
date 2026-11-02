"""Mode operatoire des gangs d'une alerte : techniques MITRE ATT&CK, outils et
CVE citees, DOCUMENTES PAR UN TIERS, SUR LE GANG -- JAMAIS SUR L'INCIDENT.

Source : ransomware.live `/v2/group/<gang>` (clearnet, sans cle -- exception
« enrichisseurs » de CONTRIBUTING.md §2). Seul le NOM du gang sort de la
plateforme. Mesure du 2026-09-15 : 61 des 396 groupes y portent des TTP
structures ; sur les alertes d'alors, 14 sur 31 etaient couvertes, 12 par un
gang a CVE nommee (lockbit3 : CVE-2023-4966 / Citrix Bleed ; nightspire :
CVE-2024-55591 / FortiOS).

⚠️ CELA DIT COMMENT LE GROUPE TRAVAILLE HABITUELLEMENT, PAS COMMENT CETTE
ORGANISATION A ETE COMPROMISE. Ecrire « vous avez ete compromis via
CVE-2024-55591 » serait une invention -- meme faute que « l'organisation
Krybit a confirme ». L'interface le dit a cote de chaque profil. Sa valeur
est ailleurs : orienter la victime vers les correctifs et les journaux a
verifier en priorite.

⚠️ PAR VICTIME, pas par alerte : une alerte regionale regroupe des victimes
de gangs differents. Chaque gang est rattache aux SEULES victimes qu'il
revendique (`victim_claims`), sinon on retomberait dans « krybit revendique
Suivi Flotte » (erreur reelle du 2026-09-28).

A la demande (ouverture du dossier), cache 7 jours : aucun appel dans la
tache horaire, qui ne doit pas etre ralentie pour de l'affichage.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session

from app.db.models.alert import Alert
from app.pipeline.enrich.ransomlook_corroboration import normalise_gang
from app.pipeline.enrich.ransomware_live import GangProfile, parse_group_profile
from app.services.admiralty_service import victim_claims
from app.services.corroboration_service import payload_rwl_profile

#: Une seule formulation, reprise telle quelle par la route du dossier et l'export
#: STIX :
#: le vocabulaire est du code (lecon des resumes LLM et du rapport PDF).
MODUS_OPERANDI_CAVEAT = (
    "Mode opératoire HABITUEL du groupe, documenté par un tiers "
    "(ransomware.live) à partir d'autres incidents. Il ne dit PAS comment "
    "cette organisation a été compromise : il oriente les vérifications "
    "(correctifs, journaux) à mener en priorité."
)

# Borne : une alerte regionale peut regrouper une douzaine de victimes. Au-dela
# de quelques gangs, l'ouverture du dossier enchainerait les appels et
# heurterait le rate limit (~1/min).
MAX_GANGS = 5


class ProfileStatus(str, Enum):
    DOCUMENTED = "documented"
    # Gang suivi mais sans TTP publies (la majorite : 335 groupes sur 396).
    UNDOCUMENTED = "undocumented"
    # Reseau ou limite de debit : absence de MESURE, a ne jamais presenter
    # comme « pas de mode operatoire connu ».
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GangModusOperandi:
    gang: str
    status: ProfileStatus
    victims: tuple[str, ...]
    profile: GangProfile | None


def _gangs_et_victimes(db: Session, alerte: Alert) -> dict[str, list[str]]:
    """gang normalise -> victimes de l'alerte qu'il revendique, dans l'ordre."""
    par_gang: dict[str, list[str]] = {}
    for victime, gang in victim_claims(db, alerte):
        cle = normalise_gang(gang)
        if not cle:
            continue
        victimes = par_gang.setdefault(cle, [])
        if victime and victime not in victimes:
            victimes.append(victime)
    if not par_gang and alerte.corroborated_group:
        # Repli : alerte sans victime nommee lisible (forum), gang principal.
        par_gang[normalise_gang(alerte.corroborated_group)] = []
    return par_gang


def modus_operandi(db: Session, alerte: Alert) -> list[GangModusOperandi]:
    """Mode operatoire de chaque gang revendiquant une victime de l'alerte.

    Ne leve jamais pour une indisponibilite du tiers : un gang injoignable est
    rendu `unavailable`, les autres restent affiches."""
    resultat: list[GangModusOperandi] = []
    for gang, victimes in list(_gangs_et_victimes(db, alerte).items())[:MAX_GANGS]:
        charge = payload_rwl_profile(gang)
        if charge is None:
            resultat.append(
                GangModusOperandi(
                    gang, ProfileStatus.UNAVAILABLE, tuple(victimes), None
                )
            )
            continue
        profil = (
            parse_group_profile(gang, charge[0])
            if charge
            else GangProfile(gang=gang, techniques=(), tools=(), cves=())
        )
        statut = (
            ProfileStatus.UNDOCUMENTED if profil.is_empty else ProfileStatus.DOCUMENTED
        )
        resultat.append(GangModusOperandi(gang, statut, tuple(victimes), profil))
    return resultat
