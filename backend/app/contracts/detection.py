from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class DetectionType(str, Enum):
    EMAIL = "email"
    CARD = "card"
    IBAN = "iban"
    CRYPTO_WALLET = "crypto_wallet"
    API_KEY = "api_key"
    CREDENTIALS = "credentials"
    PHONE = "phone"
    DOMAIN = "domain"
    # Pas une PII -- signal de gravite/ampleur d'un leak annonce publiquement
    # (ex: "16.20 M" credentials, "40gb of corporate data"), voir
    # pipeline/detect/patterns/volume.py. value_masked porte ici la grandeur
    # normalisee lisible (pas une valeur a cacher, rien a masquer)."""
    VOLUME = "volume"
    # Pas une PII -- nom d'organisation mentionne en texte libre (NER, voir
    # pipeline/detect/patterns/organization.py), meme logique que DOMAIN :
    # c'est un indicateur de renseignement (entite potentiellement touchee),
    # pas une donnee a proteger. value_masked porte le nom normalise en clair.
    # validated=False systematiquement : inference probabiliste, pas de
    # validateur deterministe type Luhn/mod-97 pour un nom d'organisation.
    ORGANIZATION = "organization"
    # Pas une PII -- canal de distribution d'une fuite (hebergeur de fichiers,
    # messagerie, paste site) mentionne dans une annonce, voir
    # pipeline/detect/patterns/distribution.py. Signal operationnel : indique
    # OU la donnee volee est mise a disposition, pas ce qu'elle contient.
    # value_masked porte l'hote en clair (donnee publique d'infrastructure,
    # jamais une URL complete -- le chemin peut, lui, designer une victime).
    DISTRIBUTION_CHANNEL = "distribution_channel"
    # Pas une PII -- rubrique de classement declaree par la source elle-meme
    # (section de forum, categorie), voir pipeline/detect/patterns/topic.py.
    # Signal de contexte : une annonce publiee dans "CARDING" ou "Leaks" n'a
    # pas la meme portee qu'un article de la rubrique presse. value_masked
    # porte le libelle tel que la source le publie.
    SOURCE_TOPIC = "source_topic"
    # Pas une PII -- nature de l'evenement annonce par le titre d'une
    # publication ("... database breached", "... Leaked, Download!"), voir
    # pipeline/detect/patterns/announcement.py. Repond a "de quoi s'agit-il ?"
    # la ou les autres types repondent a "quelle valeur a fuite ?".
    # value_masked porte la categorie normalisee (breach, stealer_logs...).
    ANNOUNCEMENT = "announcement"
    # Pas une PII -- groupe d'attaquants revendiquant publiquement une
    # compromission (nom du gang ransomware), voir
    # pipeline/detect/patterns/threat_actor.py. Repond a "qui revendique ?",
    # complementaire de ORGANIZATION/victim ("qui est touche ?").
    THREAT_ACTOR = "threat_actor"


class DetectionContract(BaseModel):
    """Une occurrence detectee dans un `RawDocument` (voir pipeline/detect/).

    Jamais de valeur brute ici (regle non negociable, voir CONTRIBUTING.md) :
    uniquement `value_masked` (affichage, voir pipeline/detect/masking.py) et
    `value_hash` (SHA-256, correlation entre detections sans reexposer la
    valeur). `extra="forbid"` empeche justement d'ajouter un jour un champ
    `value`/`raw_value` par erreur."""

    model_config = {"extra": "forbid"}

    id: UUID
    document_id: UUID
    type: DetectionType
    value_masked: str
    value_hash: str
    # True si un validateur (Luhn pour card, mod-97 pour iban...) a confirme le
    # match ; False si seul le pattern regex a matche (types sans validateur
    # dedie, ex: email/crypto_wallet -- ou un validateur qui a echoue mais dont
    # on garde trace pour ne pas perdre un potentiel vrai positif mal forme).
    validated: bool
    # True si le document source correspond a au moins un terme de la
    # watchlist active (voir keyword_match.py) -- distingue une fuite
    # pertinente pour une organisation surveillee d'une detection technique
    # correcte mais hors sujet (ex: dox de particulier sans rapport avec un
    # client, constate empiriquement sur le corpus reel). Ne filtre PAS a la
    # persistance (toute detection reste en base, voir CONTRIBUTING.md
    # minimisation/tracabilite) : juste un signal de tri pour l'analyste.
    is_relevant: bool
    created_at: datetime
