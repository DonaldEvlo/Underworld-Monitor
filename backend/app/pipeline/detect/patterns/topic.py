"""Detection de la rubrique de classement declaree par la source (section de
forum, categorie). Logique pure (voir CONTRIBUTING.md).

Troisieme detecteur de la famille "exploiter ce que la source declare" apres
patterns/victim.py (nom de victime) et patterns/distribution.py (canal de
diffusion) : les forums classent eux-memes leurs publications, et les
collecteurs capturent deja ce classement en tete de `content` (voir
collect/xssf/adapter.py -- "Section: ...", collect/xenforo_latest/adapter.py --
"Forum: ..."). C'est une taxonomie ecrite par l'ecosysteme observe, plus fiable
que n'importe quelle categorisation qu'on inferrerait du texte.

Ce que ca apporte a l'analyste : le contexte de publication. Une annonce postee
dans "CARDING" ou "Leaks of courses and training materials" n'a pas la meme
portee qu'un article de la rubrique presse -- constate en base, les 196
documents XSSF proviennent tous de la section "СМИ / NEWS" (medias/actualites)
et leurs detections `email` les plus frequentes sont des adresses d'un
fournisseur grand public citees dans des articles, pas des identifiants
fuites. Sans cette rubrique, rien ne distingue ces deux natures de signal.

`validated=True` : la valeur est lue a l'endroit ou la source l'a mise, ce
n'est pas une inference. Pas une PII : c'est un libelle de rubrique publique,
jamais une donnee personnelle -- value_masked reste en clair.

Perimetre volontairement etroit, comme victim.py : seuls les marqueurs poses
par les adaptateurs sont reconnus. Un collecteur qui n'en pose pas ne produit
rien (pas de categorisation inventee)."""

from __future__ import annotations

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.raw_match import RawMatch

# Marqueurs poses en tete de `content` par les adaptateurs de collecte.
# Ancres en debut de ligne (^ + MULTILINE) pour ne jamais capturer le mot
# "Section:" cite au fil d'une discussion.
_TOPIC_LINE_RE = re.compile(r"^(?:Section|Forum):\s*(?P<topic>.+?)\s*$", re.MULTILINE)

# Un libelle de rubrique exploitable n'est ni vide ni reduit a de la
# ponctuation. Seuil bas (2) volontairement : certaines rubriques reelles sont
# tres courtes ("CC", "Web"), contrairement a un nom d'organisation.
_MIN_LENGTH = 2

# Libelle anormalement long : ce n'est plus une rubrique mais une phrase happee
# par le marqueur (garde-fou, pas un cas constate).
_MAX_LENGTH = 80


def find_source_topics(text: str) -> list[RawMatch]:
    """Retourne les rubriques de classement declarees dans `text`.

    Un document appartient generalement a une seule rubrique ; la dedup par
    libelle normalise couvre le cas d'un document agregeant plusieurs
    publications."""
    matches = []
    seen: set[str] = set()

    for match in _TOPIC_LINE_RE.finditer(text):
        value = " ".join(match.group("topic").split()).strip()
        if not _MIN_LENGTH <= len(value) <= _MAX_LENGTH:
            continue
        dedup_key = value.casefold()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        matches.append(
            RawMatch(
                type=DetectionType.SOURCE_TOPIC,
                value_masked=value,
                # casefold plutot que lower : les rubriques peuvent etre en
                # cyrillique (constate : "СМИ / NEWS"), ou lower() ne suffit
                # pas toujours a normaliser deux graphies equivalentes.
                value_hash=hash_value(dedup_key),
                validated=True,
            )
        )

    return matches
