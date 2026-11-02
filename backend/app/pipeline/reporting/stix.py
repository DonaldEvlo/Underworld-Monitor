"""Export d'une alerte au format STIX 2.1 -- le format d'echange d'un CERT.

Une alerte se traduit ainsi :
  victime            -> `identity` (organisation) [+ `location` si pays connu]
  gang               -> `intrusion-set`, relie par `targets`
  mode operatoire    -> `attack-pattern` (MITRE ATT&CK), `tool`,
                        `vulnerability` (CVE), relies par `uses`/`targets`,
                        plus une `note` portant la mise en garde
  l'alerte elle-meme -> `report`
  marquage           -> TLP:AMBER+STRICT (TLP 2.0) sur CHAQUE objet

⚠️ REGLE 2 : n'entrent QUE des donnees publiques et citables -- nom ou
domaine de l'organisation victime (un domaine n'est pas une PII, voir
detect/masking.py), nom du gang, identifiants ATT&CK/CVE, noms d'outils, URL
de preuve CLEARNET. Jamais une valeur detectee, meme masquee (une adresse
masquee reste une donnee de personne), jamais un `.onion` (ce serait pointer
vers la fuite : regle 1), jamais un extrait de contenu.

⚠️ LE MODE OPERATOIRE EST CELUI DU GANG, PAS DE L'INCIDENT : il est
documente par un tiers a partir d'autres victimes. La `note` et la
description de chaque relation le disent -- un destinataire qui lirait
« uses CVE-2024-55591 » sous sa propre victime en conclurait a tort au
vecteur de SA compromission.

Valeurs VERIFIEES A LA SOURCE le 2026-09-30, jamais ecrites de memoire :
- marquage TLP:AMBER+STRICT : objet officiel du depot OASIS
  `cti-stix-common-objects/extension-definition-specifications/tlp-2.0/
  examples/tlp-amber+strict.json` ;
- confiance : table « Admiralty Credibility » de l'annexe A de STIX 2.1
  (1 -> 90, 2 -> 70, 3 -> 50, 4 -> 30, 5 -> 10, 6 -> non specifiee).
  ⚠️ Une premiere lecture par un outil de resume avait rendu 95/75/50/25/15/0
  -- valeurs INVENTEES, l'annexe etait tronquee. Lue ensuite dans le texte
  integral de la specification ;
- secteurs : vocabulaire ouvert `industry-sector-ov` de STIX 2.1, face aux 14
  valeurs `activity` relevees dans le cache ransomware.live.

Identifiants DETERMINISTES (uuid5) : deux exports de la meme alerte, ou deux
alertes du meme gang, reutilisent les memes objets -- le destinataire
dedoublonne au lieu d'accumuler des copies.

Logique pure : aucune base, aucun reseau.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Espace de noms des identifiants de la plateforme (uuid5).
_ESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://underworld-monitor.local/stix")

TLP_AMBER_STRICT_ID = "marking-definition--939a9414-2ddd-4d32-a0cd-375ea402b003"
_TLP_AMBER_STRICT: dict[str, Any] = {
    "type": "marking-definition",
    "spec_version": "2.1",
    "id": TLP_AMBER_STRICT_ID,
    "created": "2022-10-01T00:00:00.000Z",
    "name": "TLP:AMBER+STRICT",
    "extensions": {
        "extension-definition--60a3c5c5-0d10-413e-aab3-9e08dde9e88d": {
            "extension_type": "property-extension",
            "tlp_2_0": "amber+strict",
        }
    },
}

#: STIX 2.1, annexe A, « Admiralty Credibility » -> confiance. Le chiffre 6
#: (« la verite ne peut etre jugee ») n'a PAS de valeur : la propriete est
#: alors absente, jamais 0 (0 dirait « certainement faux »).
ADMIRALTY_TO_CONFIDENCE = {"1": 90, "2": 70, "3": 50, "4": 30, "5": 10}

#: `activity` ransomware.live -> `industry-sector-ov`. Pas de correspondance
#: (Professional Services, Other, Not Found) = propriete absente, jamais un
#: secteur devine.
SECTEURS = {
    "Manufacturing": ["manufacturing"],
    "Technology": ["technology"],
    "Healthcare": ["healthcare"],
    "Retail & E-Commerce": ["retail"],
    "Financial Services": ["financial-services"],
    "Transportation": ["transportation"],
    "Agriculture and Food Production": ["agriculture"],
    "Education": ["education"],
    "Government & Defense": ["government", "defense"],
    "Energy & Utilities": ["energy", "utilities"],
    "Hospitality": ["hospitality-leisure"],
}

PRODUCTEUR = "Underworld Monitor"


@dataclass(frozen=True)
class StixVictim:
    name: str
    gang: str | None = None
    country: str | None = None  # ISO 3166-1 alpha-2
    sector: str | None = None  # valeur `activity` ransomware.live


@dataclass(frozen=True)
class StixTechnique:
    technique_id: str
    name: str
    tactic: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class StixGangProfile:
    gang: str
    techniques: tuple[StixTechnique, ...] = ()
    tools: tuple[str, ...] = ()
    cves: tuple[str, ...] = ()


@dataclass(frozen=True)
class StixAlertInput:
    alert_id: str
    subject: str
    created: datetime
    modified: datetime
    severity: str
    victims: tuple[StixVictim, ...]
    credibility_level: str | None = None
    credibility_evidence: str | None = None
    admiralty: str | None = None  # ex. « B2 »
    profiles: tuple[StixGangProfile, ...] = ()
    # (nom de la source, URL) -- CLEARNET uniquement, filtre a la construction.
    evidence: tuple[tuple[str, str], ...] = ()
    modus_operandi_caveat: str = ""


@dataclass
class _Paquet:
    horodatage: str
    producteur_id: str
    objets: dict[str, dict] = field(default_factory=dict)

    def ajouter(self, objet: dict) -> str:
        self.objets.setdefault(objet["id"], objet)
        return objet["id"]


def _id(type_: str, cle: str) -> str:
    return f"{type_}--{uuid.uuid5(_ESPACE, f'{type_}:{cle.strip().lower()}')}"


def _ts(moment: datetime) -> str:
    """Horodatage STIX : UTC, millisecondes, suffixe Z."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _url_citable(url: str | None) -> bool:
    """http(s) uniquement, jamais un `.onion` : une URL de preuve sort de
    l'outil, elle ne doit ni executer quoi que ce soit ni mener a la fuite."""
    if not url:
        return False
    bas = url.strip().lower()
    if not bas.startswith(("https://", "http://")):
        return False
    hote = bas.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
    return not hote.endswith(".onion")


def _commun(paquet: _Paquet, type_: str, identifiant: str) -> dict:
    return {
        "type": type_,
        "spec_version": "2.1",
        "id": identifiant,
        "created": paquet.horodatage,
        "modified": paquet.horodatage,
        "created_by_ref": paquet.producteur_id,
        "object_marking_refs": [TLP_AMBER_STRICT_ID],
    }


def _relation(paquet: _Paquet, source: str, type_: str, cible: str, **extra) -> str:
    identifiant = _id("relationship", f"{source}|{type_}|{cible}")
    objet = _commun(paquet, "relationship", identifiant)
    objet.update(relationship_type=type_, source_ref=source, target_ref=cible)
    objet.update({k: v for k, v in extra.items() if v is not None})
    return paquet.ajouter(objet)


def _phase(tactique: str) -> str:
    """« Initial Access » -> « initial-access » (kill chain MITRE ATT&CK)."""
    return "-".join(tactique.strip().lower().split())


def build_bundle(alerte: StixAlertInput) -> dict:
    """Paquet STIX 2.1 d'une alerte. Voir la docstring du module."""
    horodatage = _ts(alerte.modified)
    producteur: dict[str, Any] = {
        "type": "identity",
        "spec_version": "2.1",
        "id": _id("identity", f"producteur:{PRODUCTEUR}"),
        "created": horodatage,
        "modified": horodatage,
        "name": PRODUCTEUR,
        "identity_class": "system",
        "object_marking_refs": [TLP_AMBER_STRICT_ID],
    }
    paquet = _Paquet(horodatage=horodatage, producteur_id=producteur["id"])
    confiance = ADMIRALTY_TO_CONFIDENCE.get((alerte.admiralty or "")[-1:])

    references: list[str] = []
    gangs: dict[str, str] = {}

    def intrusion_set(nom: str) -> str:
        cle = nom.strip().lower()
        if cle not in gangs:
            objet = _commun(paquet, "intrusion-set", _id("intrusion-set", cle))
            objet["name"] = nom.strip()
            gangs[cle] = paquet.ajouter(objet)
            references.append(gangs[cle])
        return gangs[cle]

    for victime in alerte.victims:
        identite = _commun(
            paquet, "identity", _id("identity", f"victime:{victime.name}")
        )
        identite.update(name=victime.name, identity_class="organization")
        secteurs = SECTEURS.get((victime.sector or "").strip())
        if secteurs:
            identite["sectors"] = list(secteurs)
        identite_id = paquet.ajouter(identite)
        references.append(identite_id)
        if victime.country and len(victime.country.strip()) == 2:
            pays = victime.country.strip().upper()
            lieu = _commun(paquet, "location", _id("location", f"pays:{pays}"))
            lieu["country"] = pays
            references.append(paquet.ajouter(lieu))
            references.append(_relation(paquet, identite_id, "located-at", lieu["id"]))
        if victime.gang:
            references.append(
                _relation(
                    paquet,
                    intrusion_set(victime.gang),
                    "targets",
                    identite_id,
                    description=(
                        "Victime revendiquee par le groupe sur son site de fuite "
                        "(declaration de l'attaquant, non verifiee par nous)."
                    ),
                    confidence=confiance,
                )
            )

    mode_operatoire: list[str] = []
    precaution = alerte.modus_operandi_caveat or (
        "Mode operatoire habituel du groupe, documente par un tiers : ce n'est "
        "pas le vecteur de cet incident."
    )
    for profil in alerte.profiles:
        gang_id = intrusion_set(profil.gang)
        for technique in profil.techniques:
            motif = _commun(
                paquet, "attack-pattern", _id("attack-pattern", technique.technique_id)
            )
            reference = {
                "source_name": "mitre-attack",
                "external_id": technique.technique_id,
            }
            if technique.url and _url_citable(technique.url):
                reference["url"] = technique.url
            motif.update(
                name=technique.name or technique.technique_id,
                external_references=[reference],
            )
            if technique.tactic:
                motif["kill_chain_phases"] = [
                    {
                        "kill_chain_name": "mitre-attack",
                        "phase_name": _phase(technique.tactic),
                    }
                ]
            mode_operatoire.append(paquet.ajouter(motif))
            mode_operatoire.append(
                _relation(paquet, gang_id, "uses", motif["id"], description=precaution)
            )
        for nom in profil.tools:
            outil = _commun(paquet, "tool", _id("tool", nom))
            outil["name"] = nom
            mode_operatoire.append(paquet.ajouter(outil))
            mode_operatoire.append(
                _relation(paquet, gang_id, "uses", outil["id"], description=precaution)
            )
        for cve in profil.cves:
            vuln = _commun(paquet, "vulnerability", _id("vulnerability", cve))
            vuln.update(
                name=cve,
                external_references=[{"source_name": "cve", "external_id": cve}],
            )
            mode_operatoire.append(paquet.ajouter(vuln))
            mode_operatoire.append(
                _relation(
                    paquet, gang_id, "targets", vuln["id"], description=precaution
                )
            )

    references.extend(mode_operatoire)
    if mode_operatoire:
        note = _commun(
            paquet, "note", _id("note", f"mode-operatoire:{alerte.alert_id}")
        )
        note.update(
            abstract="Mode operatoire du groupe -- pas le vecteur de cet incident",
            content=precaution,
            object_refs=list(dict.fromkeys(mode_operatoire)),
        )
        references.append(paquet.ajouter(note))

    rapport = _commun(paquet, "report", _id("report", f"alerte:{alerte.alert_id}"))
    lignes = [f"Gravite : {alerte.severity}."]
    if alerte.credibility_level:
        lignes.append(
            f"Credibilite : {alerte.credibility_level}"
            + (
                f" -- {alerte.credibility_evidence}"
                if alerte.credibility_evidence
                else ""
            )
            + "."
        )
    if alerte.admiralty:
        lignes.append(f"Notation Admiralty : {alerte.admiralty}.")
    lignes.append(
        "Revendication publiee par l'attaquant ; la plateforme lit, elle ne "
        "telecharge ni ne verifie le contenu de la fuite."
    )
    rapport.update(
        created=_ts(alerte.created),
        name=alerte.subject,
        description=" ".join(lignes),
        report_types=["threat-report"],
        published=_ts(alerte.created),
        object_refs=list(dict.fromkeys(references)) or [producteur["id"]],
        labels=[
            etiquette
            for etiquette in (
                f"severite:{alerte.severity}",
                (
                    f"credibilite:{alerte.credibility_level}"
                    if alerte.credibility_level
                    else None
                ),
                f"admiralty:{alerte.admiralty}" if alerte.admiralty else None,
            )
            if etiquette
        ],
    )
    if confiance is not None:
        rapport["confidence"] = confiance
    preuves = [
        {"source_name": nom, "url": url.strip()}
        for nom, url in alerte.evidence
        if _url_citable(url)
    ]
    if preuves:
        rapport["external_references"] = preuves
    paquet.ajouter(rapport)

    return {
        "type": "bundle",
        "id": _id("bundle", f"{alerte.alert_id}:{horodatage}"),
        "objects": [_TLP_AMBER_STRICT, producteur, *paquet.objets.values()],
    }
