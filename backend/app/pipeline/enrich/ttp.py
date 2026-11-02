"""Extraction de TTP DECLARES (CVE + techniques nommees) -> MITRE ATT&CK.

⚠️ RENDEMENT FAIBLE, MESURE (2026-09-15). Sur 5 012 documents : **4 seulement**
citent une CVE (0 %), et elles viennent des FORUMS (BREACH FORUMS, SPEAR), pas
des sites de fuite -- un DLS nomme la victime et se vante du volume, il ne dit
presque jamais COMMENT il est entre. Ce module existe donc comme brique
optionnelle et secondaire (CONTRIBUTING.md : « TTPs -> jamais un axe central »),
pas comme un type de detection. Il n'est volontairement NI persiste NI cable :
le rendement ne le justifie pas encore, et la decision de le brancher est a
prendre separement (§9.3). Le signal de methode le plus exploitable vient
plutot de l'enrichisseur (ransomware.live : champ `infostealer`, secteur) que
du texte scrape.

⚠️ TOUJOURS `declared, unverified` : on rapporte ce que l'acteur ECRIT, jamais
ce qu'on aurait teste (regle 1 -- observation, pas exploitation). Fonctions
PURES, sans reseau ni base.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Un identifiant CVE bien forme. Le suffixe va de 4 a 7 chiffres (NVD).
_CVE_RE = re.compile(r"\bCVE-(\d{4})-(\d{4,7})\b", re.IGNORECASE)

# Plafond : un document pathologique (dump de bulletins) ne doit pas produire
# une liste sans fin.
_MAX_CVES = 50


def extract_cves(text: str | None) -> list[str]:
    """CVE distinctes citees, en forme canonique majuscule, triees."""
    if not text:
        return []
    trouvees = {f"CVE-{annee}-{num}".upper() for annee, num in _CVE_RE.findall(text)}
    return sorted(trouvees)[:_MAX_CVES]


@dataclass(frozen=True)
class DeclaredTechnique:
    technique_id: str  # identifiant MITRE ATT&CK (ex: T1566)
    name: str
    keyword: str  # le marqueur reel trouve dans le texte


# Marqueurs -> technique MITRE ATT&CK. Volontairement CONSERVATEUR : uniquement
# des termes non ambigus. « exploit » seul n'y est PAS (321 documents, trop
# bruite -- il apparait dans « exploit kit for sale », un tutoriel, etc.).
# Chaque motif utilise des frontieres de mot pour ne pas matcher en sous-chaine.
_TECHNIQUES: tuple[tuple[str, str, str], ...] = (
    (r"spear[\s-]?phish|phishing", "T1566", "Phishing"),
    (r"\bRDP\b|remote desktop protocol", "T1021.001", "Remote Services: RDP"),
    (r"cobalt strike", "T1071", "Application Layer Protocol (Cobalt Strike)"),
    (r"\bmimikatz\b", "T1003", "OS Credential Dumping"),
    (r"\bpsexec\b", "T1021.002", "Remote Services: SMB/Windows Admin Shares"),
    (r"\bpowershell\b", "T1059.001", "Command and Scripting: PowerShell"),
    (
        r"exploit(ing|ed)?\s+(a\s+)?(public[- ]facing|internet[- ]facing)",
        "T1190",
        "Exploit Public-Facing Application",
    ),
    (
        r"valid accounts|stolen credentials|leaked credentials",
        "T1078",
        "Valid Accounts",
    ),
    (r"\bvpn\b\s+(access|credential|compromise)", "T1133", "External Remote Services"),
)

_COMPILED = tuple(
    (re.compile(p, re.IGNORECASE), tid, name) for p, tid, name in _TECHNIQUES
)


def extract_declared_techniques(text: str | None) -> list[DeclaredTechnique]:
    """Techniques MITRE DECLAREES dans le texte, une par identifiant.

    On retient le PREMIER marqueur rencontre par technique. Rien d'infere :
    seulement des termes ecrits explicitement, toujours `declared, unverified`."""
    if not text:
        return []
    trouvees: dict[str, DeclaredTechnique] = {}
    for motif, tid, name in _COMPILED:
        if tid in trouvees:
            continue
        m = motif.search(text)
        if m:
            trouvees[tid] = DeclaredTechnique(
                technique_id=tid, name=name, keyword=m.group(0).strip()
            )
    return [trouvees[k] for k in sorted(trouvees)]


# ⚠️ Les identifiants viennent d'un TIERS et finissent dans un `href` : seule
# une forme stricte produit un lien (jamais `javascript:` ni un domaine
# arbitraire). Meme doctrine que le filtre d'URL de la couverture presse.
_TECHNIQUE_ID_STRICT = re.compile(r"^T(\d{4})(?:\.(\d{3}))?$")
_CVE_ID_STRICT = re.compile(r"^CVE-\d{4}-\d{4,7}$")


def mitre_technique_url(technique_id: str | None) -> str | None:
    """Page MITRE ATT&CK d'une technique : `T1190` -> `/techniques/T1190/`,
    `T1059.001` -> `/techniques/T1059/001/`. None si la forme est inattendue."""
    m = _TECHNIQUE_ID_STRICT.match((technique_id or "").strip().upper())
    if not m:
        return None
    base = f"https://attack.mitre.org/techniques/T{m.group(1)}/"
    return f"{base}{m.group(2)}/" if m.group(2) else base


def cve_url(cve: str | None) -> str | None:
    """Fiche NVD d'une CVE. None si la forme est inattendue."""
    ident = (cve or "").strip().upper()
    if not _CVE_ID_STRICT.match(ident):
        return None
    return f"https://nvd.nist.gov/vuln/detail/{ident}"
