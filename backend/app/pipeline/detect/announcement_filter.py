"""Classification d'une annonce : fuite de donnees exploitable, ou bruit ?

**Pourquoi ce module existe.** Les sites de fuite dedies publient une victime
par page : tout y est signal. Les forums generalistes (Dread, BreachForums,
DarkForums, SPEAR, DARKNET ARMY) melangent des annonces de fuite reelles avec
des tutoriels, des demandes d'aide, du carding, des discussions de communaute
et des jeux piratés. Mesure du 2026-08-28 : ces forums produisent **20 a 96 %
de bruit** sur leurs detections de domaine, contre 0 a 7 % pour les sites de
fuite.

Ce module tranche AVANT la detection : un document classe `NOISE` ne doit pas
alimenter la watchlist ni le calcul de gravite.

**Logique purement deterministe, par conception.** Aucun appel LLM ici. Un
classifieur non reproductible sur le chemin critique rendrait les resultats
invérifiables -- or la platforme doit pouvoir justifier chaque alerte. Le LLM
intervient plus tard, uniquement sur les cas que ces regles laissent
`UNCERTAIN` (voir chantier 3).

**Le titre suffit souvent, et c'est heureux.** Sur BreachForums, 93 documents
sur 93 sont tronques (« contenu du post non accessible sans compte ») : le
titre est alors la SEULE information disponible. Or un titre d'annonce de
fuite est tres codifie -- volume, nom de base, pays entre crochets, mention
« Database »/« Leaked ». C'est exploitable sans jamais s'authentifier sur le
forum, ce que le projet s'interdit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class AnnouncementClass(str, Enum):
    """Verdict de classification d'un document."""

    LEAK = "leak"
    """Annonce de fuite de donnees : volume, base nommee, victime identifiee."""

    NOISE = "noise"
    """Hors perimetre : tutoriel, discussion, entraide, piratage de jeux..."""

    UNCERTAIN = "uncertain"
    """Ni marqueur de fuite franc, ni marqueur d'exclusion franc. C'est
    l'ensemble que le LLM pourra trancher plus tard -- volontairement distinct
    de NOISE : ne jamais jeter silencieusement ce qu'on n'a pas su classer."""


# --------------------------------------------------------------------------
# Marqueurs d'EXCLUSION -- priment sur tout le reste.
#
# Ces termes designent une activite qui n'est PAS une fuite de donnees d'une
# organisation, meme quand ils cotoient du vocabulaire de securite. Le cas
# fondateur : « HTB - Season 11 - Nimbus - Writeup » -- un exercice Hack The
# Box, pedagogique, sans aucune victime reelle.
# --------------------------------------------------------------------------
_EXCLUSION_PATTERNS: tuple[tuple[str, str], ...] = (
    # Exercices et pedagogie
    (r"\b(writeup|write-up|walkthrough)\b", "exercice"),
    (
        r"\bhtb\b|hack\s?the\s?box|tryhackme|\bctf\b|\broot-?me\b",
        "plateforme d'entrainement",
    ),
    (
        r"\b(tutorials?|tuto|how\s?to|guides?|courses?|lessons?|learning|"
        r"beginner)\b",
        "tutoriel",
    ),
    (r"\bmethod(e|s)?\b.{0,20}\b(working|100%)\b", "methode"),
    (r"\b(working|100%)\b.{0,20}\bmethod(e|s)?\b", "methode"),
    # Demandes et entraide
    (
        r"\b(looking\s?for|searching\s?for|need\s?help|help\s?me|request|wtb|where\s?do\s?i)\b",
        "demande",
    ),
    (r"^\s*(is|are|does|how|why|what|who|where|can)\b.*\?\s*$", "question"),
    # Vie du forum
    (
        r"\b(introduction|my\s?intro|welcome|announcement|community\s?update|"
        r"rules?\s?update|guidelines|giveaway|raffle|contest)\b",
        "vie du forum",
    ),
    (r"\b(staff|moderator|admin)\s?(chat|application|recruitment)\b", "vie du forum"),
    # Outils, logiciels, contenus pirates -- pas des fuites d'organisation
    (
        r"\b(cracker|checker|bruteforce|combo\s?list\s?maker|keygen|crack(ed)?\s?by)\b",
        "outil",
    ),
    (
        r"\b(gta\s?6|gta6|minecraft|netflix|spotify|steam|epicgames|psn|"
        r"vpn|iptv|rdp|vps)\b",
        "compte/logiciel grand public",
    ),
    (r"\.(7z|rar|exe|apk|iso)\b", "fichier logiciel"),
    (r"\bv\.?\d+\.\d+\.\d+", "version logicielle"),
    # Monetisation frauduleuse et services -- pas des fuites d'organisation.
    #
    # Ajoute le 2026-09-02 sur signalement : ces annonces contiennent du
    # vocabulaire de fuite (« CC », « cashout », un volume en Go) et scoraient
    # donc LEAK. Mesure avant correctif : 9 faux positifs sur DARKNET ARMY et
    # DARKFORUMS, dont « UPDATED METHODS OF CARD CASHOUT » et « CC TO CRYPTO ».
    #
    # Le carding est deja hors perimetre par decision documentee (exclusion de
    # markets.md et de BFD Forum, desactivation de DOXBYTE) : `matching.py` ne
    # sait pas rattacher une detection `card` a une organisation.
    (
        r"\b(carding|cash\s?out|cashout|dumps?\s?\+?\s?pin|bin\s?list)\b",
        "carding",
    ),
    (r"\bcc\s?(to|2)\s?(btc|crypto|bitcoin|usdt|cash)\b", "carding"),
    # Comptes et logiciels pirates. `premium` n'est JAMAIS seul : une victime
    # peut tres bien s'appeler « Premium Foods ».
    (r"\b(cracked|nulled)\b|\bpremium\s?(account|acc)s?\b", "contenu pirate"),
    (r"\b(robux|v-?bucks|free\s?nitro)\b", "monnaie de jeu"),
    # Services de deverrouillage -- le cas signale (« 🍏 iCLOUD UNLOCK »)
    # passait en NOISE par simple ABSENCE de marqueur de fuite, donc par
    # accident : la meme annonce citant « database » aurait bascule.
    (
        r"\b(icloud|imei|frp|bootloader|sim)\s?(unlock|bypass|removal)\b|"
        r"\bunlock\s?(service|tool|method)\b",
        "service de deverrouillage",
    ),
    (
        r"\bbypass(ing)?\b.{0,25}\b(verification|otp|2fa|sms|kyc)\b",
        "contournement",
    ),
    # Doxxing et ciblage de PERSONNES -- exclusion de CONFORMITE, pas de
    # rendement.
    #
    # Les regles 1 et 2 de CONTRIBUTING.md interdisent de desanonymiser une personne
    # et de traiter de la PII : une personne n'est jamais une victime au sens
    # de cet outil, quel que soit le volume de donnees exposees. C'est le motif
    # qui a fait desactiver DOXBYTE et signaler EXILIO404.
    #
    # ⚠️ Traite ICI, par regle, et NON confie au LLM. Mesure du 2026-09-03 :
    # meme avec une consigne explicite dans le prompt, le modele local classait
    # encore `leak` deux cas sur quatre (« dox do exemplo », « cathedral/KYS »).
    # Une decision de conformite ne peut pas dependre d'un modele
    # probabiliste -- et la traiter ici la rend reproductible ET applicable a
    # tout le pipeline, pas seulement a l'arbitrage.
    (
        r"\bdox(x(ing|ed)?|bin)?\b|\bpedo\b|\bkys\b|\bswatting\b|" r"\bgrabber\b",
        "ciblage de personne",
    ),
    # Annuaires et meta
    (
        r"\b(dark\s?web\s?links?|onion\s?links?|directory|mirrors?\s?check)\b",
        "annuaire",
    ),
)

# --------------------------------------------------------------------------
# Marqueurs de FUITE -- signalent une annonce de donnees exfiltrees.
#
# Chacun porte un poids : un seul marqueur fort suffit, plusieurs marqueurs
# faibles se cumulent. Les poids viennent de l'observation du corpus reel,
# pas d'une intuition.
# --------------------------------------------------------------------------
_LEAK_PATTERNS: tuple[tuple[str, int, str], ...] = (
    # Marqueurs FORTS : quasi jamais presents hors annonce de fuite
    (
        r"\b(database|db)\s*(leak|dump|breach)?\b.{0,20}\b(leaked|download|free|sell)\b",
        3,
        "base annoncee",
    ),
    (r"\bdata\s?(breach|leak)\b", 3, "fuite declaree"),
    (
        r"\b(leaked|breached)\b.{0,15}\b(download|database|db)\b",
        3,
        "fuite telechargeable",
    ),
    (
        r"\b(stealer\s?logs?|ulp\s?logs?|combolist|fullz|dehashed)\b",
        3,
        "donnees volees",
    ),
    (r"\b\d+(\.\d+)?\s?(gb|tb|mb)\b", 2, "volume annonce"),
    (
        r"\b\d+(\.\d+)?\s?(k|m|million|millions)\b.{0,25}"
        r"\b(users?|records?|rows?|lines?|emails?|clients?)\b",
        3,
        "volume d'enregistrements",
    ),
    # Marqueurs MOYENS
    (r"\b(database|db)\b", 2, "mention de base"),
    (r"\b(leak(ed)?|dump|breach(ed)?|exfiltrat)", 2, "vocabulaire de fuite"),
    (
        r"^\s*\[[a-z]{2}\]|\[(france|russia|usa|mexico|canada|brazil|india|china)\]",
        2,
        "pays cible",
    ),
    (
        r"\b(admin\s?access|full\s?corporate\s?data|internal\s?documents?)\b",
        2,
        "acces ou documents internes",
    ),
    # Formats de listes d'identifiants voles, tres codifies sur les forums.
    # Mesure du 2026-08-28 : « URL:LOG:PASS », « ULP », « combo » et les lots
    # de comptes scoraient 0 alors que ce sont des donnees volees.
    (
        r"\burl\s?:\s?log\s?:\s?pass\b|\bu\s?:\s?l\s?:\s?p\b|\bulp\b",
        3,
        "liste d'identifiants",
    ),
    (r"\b(combo|mailpass|mail\s?access)\b", 2, "identifiants en lot"),
    (r"\b(uhq|hq)\b.{0,15}\b(private|mix|fresh)\b", 2, "lot qualifie"),
    (r"\b\d{2,}\s?kk?\b", 2, "volume abrege"),
    # Volume NU, sans nom commun derriere : « Exemple Communications, Inc. 42M ».
    # Poids 2 seulement -- un nombre suivi de M/K peut aussi etre un prix ou
    # une reference, il ne doit jamais suffire seul a declencher LEAK.
    (r"\b\d{1,4}\s?[MK]\b", 2, "volume nu"),
    (r"\b\d{1,3}[.\s]\d{3}[.\s]\d{3}\b", 2, "volume en clair"),
    (r"\b(sql|csv)\b", 2, "format d'export"),
    (r"\b(dox|doxx)\b", 2, "divulgation ciblee"),
    # Marqueurs FAIBLES : ne suffisent jamais seuls
    (r"\b(sell|selling|for\s?sale|price)\b", 1, "mise en vente"),
    (r"\b(passport|driving\s?licence|ssn|passeport)\b", 1, "piece d'identite"),
    (r"\b(email|mail|password|credential)s?\b", 1, "identifiants"),
)

# Un domaine dans le titre est un signal fort : une annonce de fuite nomme sa
# victime (« [FRANCE] hotel-bourse.com Database », « GPO.Gov Database »).
_DOMAIN_IN_TITLE = re.compile(
    r"\b[a-z0-9][a-z0-9-]{1,}\.(com|net|org|io|co|gov|edu|info|biz|"
    r"[a-z]{2}(\.[a-z]{2})?)\b",
    re.IGNORECASE,
)

# Seuil de decision. Cale sur le corpus reel : « Tinder (dating app) 32
# million users DB » atteint 5, « anonymous irc server » reste a 0.
_LEAK_THRESHOLD = 3

# Marqueur laisse par les collecteurs quand le forum exige un compte.
_TRUNCATED_MARKERS = (
    "apercu invite uniquement",
    "non accessible sans compte",
    "content locked",
    # ⚠️ AJOUTE LE 2026-09-21, signale a l'usage pendant l'annotation sur
    # « DATA LINE BANK » (/d/leaks) : un titre seul, impossible a trancher.
    #
    # Le collecteur Dread borne le nombre de corps recuperes par cycle (cout
    # Tor) et persiste les autres avec ce marqueur. Mesure : **134 documents
    # Dread sur 238**. Aucun n'etait signale comme tronque, si bien que les
    # regles jugeaient sur le seul titre EN CROYANT avoir lu le message -- un
    # score faible s'y lisait « pas une fuite » au lieu de « pas pu juger ».
    # C'est la meme distinction que partout ailleurs dans le projet : une
    # absence de mesure n'est pas un resultat negatif.
    "corps du message non recupere",
)


# Collecteurs dont CHAQUE document est une victime annoncee : sites de fuite
# de gangs (`dls`, `akira`) et agregateur de ces sites (`ransomlook`).
# Sur ces sources, un titre est une raison sociale nue -- « Exemplo Corporation »
# -- et l'absence de vocabulaire de fuite n'a aucune valeur informative.
#
# Le COLLECTEUR est le bon discriminant : il dit comment la source est lue,
# donc ce que ses documents contiennent. Un nom de source serait fragile
# (renommages, miroirs multiples pour un meme forum).
VICTIM_PUBLISHING_COLLECTORS: frozenset[str] = frozenset({"dls", "akira", "ransomlook"})


def source_publishes_victims(collector_name: str | None) -> bool:
    """Le collecteur produit-il un document par victime annoncee ?"""
    return (collector_name or "").strip().lower() in VICTIM_PUBLISHING_COLLECTORS


@dataclass(frozen=True)
class ClassificationResult:
    """Verdict motive : le `reason` doit permettre a un analyste de
    comprendre POURQUOI un document a ete ecarte, sans relire le code."""

    verdict: AnnouncementClass
    score: int
    reason: str
    content_truncated: bool = False

    @property
    def is_actionable(self) -> bool:
        """Un document `UNCERTAIN` reste exploitable : on ne jette que ce qui
        est franchement identifie comme hors perimetre."""
        return self.verdict is not AnnouncementClass.NOISE


def is_content_truncated(content: str) -> bool:
    """Le contenu se limite-t-il a un apercu ?

    Sur BreachForums, 93 documents sur 93 sont dans ce cas. Le savoir change
    la lecture : un score faible sur un contenu tronque signifie « on n'a pas
    pu juger », pas « ce n'est pas une fuite »."""
    lowered = (content or "").lower()
    return any(marker in lowered for marker in _TRUNCATED_MARKERS)


# --------------------------------------------------------------------------
# Exclusions RESERVEES AUX FORUMS -- jamais appliquees a un site de fuite.
#
# ⚠️ POURQUOI UNE LISTE A PART. Les exclusions ci-dessus s'appliquent AVANT la
# protection `source_publishes_victims` : un motif trop large y supprime une
# vraie victime sans recours (cas de controle : « The Methodist Church of
# Southern Africa »). Or une marque de jeu est exactement ce genre de motif --
# « Riot Games », « Rockstar Games » ou Sony sont des entreprises qui peuvent
# figurer sur un site de fuite, et AKIRA publie reellement « Buffalo Games,
# Edaron, Ceaco » (mesure du 2026-09-18). Sur un FORUM en revanche, ces noms
# designent une offre de comptes de joueurs : hors perimetre, puisqu'un compte
# de joueur n'est pas une fuite d'organisation (decision de projet,
# 2026-09-18).
#
# ⚠️ « games » SEUL n'y figure pas : il supprimerait la victime AKIRA ci-dessus
# si la liste etait un jour appliquee aux sites de fuite, et il attraperait sur
# les forums des studios reellement compromis (« member of major AAA game
# studio's private GitHub » -- un acces a une ORGANISATION, a garder).
# --------------------------------------------------------------------------
_FORUM_ONLY_EXCLUSIONS: tuple[tuple[str, str], ...] = (
    (r"\bgam(ing|e)\s?acc(ount)?s?\b", "comptes de jeu"),
    (
        r"\b(fortnite|roblox|valorant|riot\s?games?|rockstar|xbox|playstation|"
        r"ps[45]|nintendo|call\s?of\s?duty|warzone|league\s?of\s?legends|"
        r"genshin|pubg|apex\s?legends|cs\s?go|cs2|geforce\s?now)\b",
        "comptes de jeu",
    ),
)


def _find_exclusion(
    text: str, patterns: tuple[tuple[str, str], ...] = _EXCLUSION_PATTERNS
) -> str | None:
    for pattern, label in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return None


def _score_leak(text: str) -> tuple[int, list[str]]:
    score = 0
    hits: list[str] = []
    for pattern, weight, label in _LEAK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            score += weight
            hits.append(label)
    return score, hits


def classify_announcement(
    title: str | None,
    content: str | None = None,
    *,
    source_publishes_victims: bool = False,
) -> ClassificationResult:
    """Classe un document en LEAK / NOISE / UNCERTAIN.

    Le TITRE porte l'essentiel de la decision, pour deux raisons mesurees :
    il est toujours disponible (meme quand le corps est verrouille), et un
    titre d'annonce de fuite est fortement codifie. Le corps n'est utilise
    qu'en appoint, quand il est reellement accessible.

    ⚠️ `source_publishes_victims` est indispensable et ne doit PAS etre
    devine depuis le texte. Sur un site de fuite, un document EST une victime
    et son titre n'est souvent qu'une raison sociale nue -- « Tohpe
    Corporation », sans le moindre mot-cle. Sans ce drapeau, la mesure du
    2026-08-28 ecartait a tort 18 % des documents de sites de fuite, dont de
    vraies victimes. Sur ces sources, le doute profite donc au document."""
    title = (title or "").strip()
    truncated = is_content_truncated(content or "")

    # Le corps n'entre dans l'analyse que s'il apporte vraiment quelque chose.
    body = "" if truncated else (content or "")
    haystack = f"{title}\n{body[:2000]}"

    if not title:
        return ClassificationResult(
            AnnouncementClass.UNCERTAIN, 0, "titre absent", truncated
        )

    # 1. Exclusion d'abord : « HTB ... Writeup » ne doit jamais etre reclasse
    #    en fuite parce qu'il contient par ailleurs du vocabulaire technique.
    exclusion = _find_exclusion(title)
    if exclusion is None and not source_publishes_victims:
        exclusion = _find_exclusion(title, _FORUM_ONLY_EXCLUSIONS)
    if exclusion is not None:
        return ClassificationResult(
            AnnouncementClass.NOISE, 0, f"hors perimetre : {exclusion}", truncated
        )

    # 2. Score de fuite
    score, hits = _score_leak(haystack)

    # Un domaine nomme dans le TITRE (pas dans le corps) designe la victime.
    if _DOMAIN_IN_TITLE.search(title):
        score += 2
        hits.append("victime nommee")

    if score >= _LEAK_THRESHOLD:
        return ClassificationResult(
            AnnouncementClass.LEAK, score, ", ".join(hits[:4]), truncated
        )

    # Sur un site de fuite, l'absence de vocabulaire n'a aucune valeur
    # informative : le titre EST le nom de la victime. On ne declasse donc
    # jamais en NOISE sur ces sources.
    if source_publishes_victims:
        return ClassificationResult(
            AnnouncementClass.LEAK if score else AnnouncementClass.UNCERTAIN,
            score,
            ", ".join(hits[:4]) if hits else "victime publiee par la source",
            truncated,
        )

    if score > 0:
        return ClassificationResult(
            AnnouncementClass.UNCERTAIN,
            score,
            f"signal faible : {', '.join(hits[:3])}",
            truncated,
        )

    return ClassificationResult(
        AnnouncementClass.NOISE, 0, "aucun marqueur de fuite", truncated
    )
