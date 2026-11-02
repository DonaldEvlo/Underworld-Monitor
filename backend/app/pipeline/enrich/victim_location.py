"""Pays d'une victime publiee SANS domaine localisable. Logique pure.

⚠️ Le trou mesure le 2026-09-28 : la localisation ne passait que par le ccTLD
du domaine (`geo.locate_domain`). Une victime que le site de fuite nomme par
sa seule raison sociale -- « Exemple Defence Force » (ransomhouse),
« Exemple Insurance Group » et « Exemple Risk » (the gentlemen) -- entrait au
corpus mais n'atteignait JAMAIS la passe regionale : elle n'avait pas de
domaine, donc pas de pays. Ransomware.live, lui, publie pour ces memes
victimes un champ `country` (et souvent un `domain`) : `NA` / `defense-exemple.gov.na`,
`ZA` / `exemple-risk.co.za`.

⚠️ Le pays est DECLARE par l'agregateur, pas mesure par nous. Il est
conserve avec sa provenance et n'est jamais « deduit » autrement : pas de DNS,
pas de GeoIP (requete active vers la victime, regle 1).

⚠️ Rapprochement par NOM borne au GANG, comme la corroboration : un meme nom
chez un autre gang peut designer une autre organisation. Egalite apres
normalisation (`name_key`), jamais inclusion.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.pipeline.enrich.geo import locate_domain
from app.pipeline.enrich.ransomlook_corroboration import (
    domain_candidates,
    name_key,
    normalise_gang,
)

_CODE_PAYS = re.compile(r"^[A-Z]{2}$")

# Un prefixe de gang plus court que ceci ne rapproche rien : « in » ne doit
# pas rejoindre « incransom ».
_PREFIXE_GANG_MIN = 4


@dataclass(frozen=True)
class VictimLocation:
    country: str
    # Domaine declare par l'agregateur, normalise -- None s'il n'en donne pas.
    domain: str | None


def gangs_equivalents(a: str | None, b: str | None) -> bool:
    """Meme gang sous deux graphies ? « inc ransom » == « incransom » ;
    « vexy » == « Vexy Ransomware » (RansomLook et ransomware.live ne nomment
    pas les gangs pareil). Egalite, ou prefixe d'au moins 4 caracteres."""
    ga, gb = normalise_gang(a), normalise_gang(b)
    if not ga or not gb:
        return False
    if ga == gb:
        return True
    court, long_ = sorted((ga, gb), key=len)
    return len(court) >= _PREFIXE_GANG_MIN and long_.startswith(court)


def pays_contredit(pays: str, domaines: Iterable[str]) -> bool:
    """Le pays declare contredit-il le ccTLD du domaine declare ?

    ⚠️ Cas reel du 2026-09-29 : « Exemple IVF » (everest), declaree `ZA` par
    ransomware.live avec le domaine `fertilite-exemple.co.id` -- un reseau de cliniques
    INDONESIEN. Sans cette garde, elle est entree dans l'alerte regionale
    Afrique. Deux indices qui se contredisent ne localisent rien : une
    localisation fausse est pire qu'une absence de localisation.
    Un gTLD (`.com`) ne dit rien et ne contredit donc rien."""
    for domaine in domaines:
        pays_du_domaine, _ = locate_domain(domaine)
        if pays_du_domaine and pays_du_domaine != pays:
            return True
    return False


# Index : cle (nom normalise ou domaine) -> [(gang, localisation)]
LocationIndex = dict[str, list[tuple[str, VictimLocation]]]


def build_location_index(entries: Iterable[tuple[str, dict]]) -> LocationIndex:
    """Index des victimes de l'agregateur qui portent un pays valide.

    `entries` : (gang, victime brute ransomware.live). Tolerant : une entree
    mal formee est ignoree, jamais une exception."""
    index: LocationIndex = {}
    for gang, victime in entries:
        if not isinstance(victime, dict):
            continue
        pays = (victime.get("country") or "").strip().upper()
        if not _CODE_PAYS.match(pays):
            continue
        domaines = domain_candidates(victime.get("domain"))
        if pays_contredit(pays, domaines):
            continue
        localisation = VictimLocation(
            country=pays, domain=min(domaines) if domaines else None
        )
        cles = set(domaines)
        cle_nom = name_key(victime.get("victim"))
        if cle_nom:
            cles.add(cle_nom)
        cles |= domain_candidates(victime.get("victim"))
        for cle in cles:
            index.setdefault(cle, []).append((gang, localisation))
    return index


def locate_victim(
    title: str | None, gang: str | None, index: LocationIndex
) -> VictimLocation | None:
    """Localisation de la victime nommee `title` chez `gang`, ou None.

    None aussi quand l'agregateur est AMBIGU (deux pays pour la meme
    victime) : une localisation fausse ferait signaler une victime dans le
    mauvais perimetre -- pire qu'une victime non localisee."""
    if not title or not gang:
        return None
    cles = set(domain_candidates(title))
    cle_nom = name_key(title)
    if cle_nom:
        cles.add(cle_nom)
    trouvees = {
        localisation
        for cle in cles
        for gang_index, localisation in index.get(cle, [])
        if gangs_equivalents(gang, gang_index)
    }
    if len({t.country for t in trouvees}) != 1:
        return None
    # Pays unique : on prefere l'entree qui porte un domaine.
    return max(trouvees, key=lambda t: t.domain is not None)
