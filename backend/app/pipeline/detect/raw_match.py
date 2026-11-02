"""Type intermediaire partage entre les patterns (patterns/*.py) et le registre
(registry.py) -- extrait dans son propre module pour eviter un import
circulaire (les patterns produisent des RawMatch, le registre les consomme et
les associe a un document)."""

from dataclasses import dataclass

from app.contracts.detection import DetectionType


@dataclass
class RawMatch:
    """Sortie d'un detecteur de pattern, avant association a un document. Pas
    de valeur brute ici (voir masking.py) -- un pattern ne renvoie jamais la
    valeur elle-meme, uniquement le resultat deja masque/hashe."""

    type: DetectionType
    value_masked: str
    value_hash: str
    validated: bool
