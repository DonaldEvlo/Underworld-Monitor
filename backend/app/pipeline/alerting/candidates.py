"""Filtrage des candidats "entite decouverte" (voir pipeline/detect/patterns/
organization.py) deja couverts par une entite surveillee existante. Logique
pure (voir CONTRIBUTING.md §3.3) : prend des tuples deja agreges
(DetectionRepository.top_organization_candidates) et des EntityContract, ne
touche ni la DB ni Celery.

Un candidat est exclu s'il correspond deja, de facon insensible a la casse, a
une entite active -- que ce soit par son nom, un selecteur `keyword` declare,
ou le label principal d'un selecteur `domain`/`email_domain` (ex : selecteur
"telco.sn" -> label "telco" exclut le candidat "Telco"). Objectif :
n'exposer a l'analyste que des candidats reellement nouveaux, pas des entites
deja surveillees sous une autre forme."""

from __future__ import annotations

from app.contracts.entity import EntityContract, SelectorType


def _normalize(value: str) -> str:
    return " ".join(value.split()).strip().lower()


def _domain_label(domain: str) -> str:
    """Label principal d'un domaine ("mail.telco.sn" -> "telco", le label
    juste avant le TLD) -- comparaison volontairement approximative (un nom
    d'organisation en texte libre n'a pas la structure d'un domaine), sert
    juste a eviter un candidat evident deja couvert via un selecteur domaine."""
    labels = _normalize(domain).rstrip(".").split(".")
    return labels[-2] if len(labels) >= 2 else labels[0]


def _known_names(entities: list[EntityContract]) -> set[str]:
    known: set[str] = set()
    for entity in entities:
        if not entity.active:
            continue
        known.add(_normalize(entity.name))
        for selector in entity.selectors:
            if selector.type == SelectorType.KEYWORD:
                known.add(_normalize(selector.value))
            elif selector.type in (SelectorType.DOMAIN, SelectorType.EMAIL_DOMAIN):
                known.add(_domain_label(selector.value))
    return known


def filter_new_candidates(
    candidates: list[tuple[str, str, int]],
    entities: list[EntityContract],
) -> list[tuple[str, str, int]]:
    """Retourne les candidats (value_masked, value_hash, count) dont le nom ne
    correspond a aucune entite active existante."""
    known = _known_names(entities)
    return [
        candidate for candidate in candidates if _normalize(candidate[0]) not in known
    ]
