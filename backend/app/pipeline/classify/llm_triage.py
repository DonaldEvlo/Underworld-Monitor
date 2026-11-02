"""Arbitrage LLM des annonces que les REGLES n'ont pas su trancher.

`announcement_filter.py` rend trois verdicts, et le troisieme -- `uncertain` --
existe precisement pour ne rien jeter en silence : ni marqueur de fuite franc,
ni marqueur d'exclusion franc. Ce module s'adresse a ce seul ensemble.

Mesure du 2026-09-03 : **728 documents (18 % du corpus)**, dont **438 issus de
sites de fuite** ou le titre est une raison sociale nue (`Ermat Grup`,
`Exemple Pizza Egypt`, `OFFICINE FRATELLI EXEMPLE snc`) -- sans vocabulaire de
fuite, les regles ne pouvaient pas conclure. Le reste vient de forums et releve
surtout du commerce (`Telegram Bot for leak data`, vente de comptes,
`Call Spoofing And SIP Trunks SELLING`).

⚠️ Le verdict du LLM est STOCKE A PART et ne remplace jamais
`announcement_class`. Les regles restent maitresses du chemin critique : elles
sont reproductibles et explicables, un LLM ne l'est pas. Ce module ajoute une
lecture, il n'en retire aucune -- et l'on peut a tout moment comparer les deux.

⚠️ LE DOXXING EST EXPLICITEMENT HORS PERIMETRE dans le prompt, et ce n'est pas
une precaution de style. Sans cette regle, mesure du 2026-09-03 : le modele
classait `leak` des publications comme « Tera Behrman - child pedo »,
« t.me/nine dox » ou « BEST FREE DOXXING BOT IN TELEGRAM » -- du harcelement de
personnes privees, exactement le contenu qui a fait desactiver DOXBYTE et
signaler EXILIO404. Une personne n'est jamais une victime au sens de cet outil
(regles 1 et 2 de CONTRIBUTING.md), quel que soit le volume de donnees exposees.

⚠️ Ce module est PUR : il construit un prompt et analyse une reponse. Aucun
appel reseau, aucune base. Le service appelant s'occupe des deux.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Verdicts acceptes. Volontairement les memes que les regles, pour que les deux
# lectures soient comparables ligne a ligne.
VERDICTS = ("leak", "noise", "uncertain")

# Documents par appel.
#
# ⚠️ Mesure du 2026-09-03 a 10 par lot : le modele DECALE les numeros. Les
# justifications rendues ne correspondaient pas aux titres -- `exemplic` recevait
# « Exemplo Corporation... », `exempledhall` recevait « kioti announces itself
# as a victim ». Des verdicts attribues aux mauvais documents, et rien dans la
# reponse ne le signalait.
#
# D'ou deux garde-fous : des lots plus courts, et surtout l'ECHO DU TITRE
# verifie a l'analyse (voir `parse_triage_response`). Un desalignement devient
# alors detectable au lieu de produire une classification silencieusement
# fausse.
DEFAULT_BATCH_SIZE = 5

# Longueur de titre et de contenu transmise. Le titre porte l'essentiel du
# signal (sur un site de fuite, il EST le nom de la victime) ; le corps sert de
# contexte, pas de matiere premiere.
_MAX_TITLE = 160
_MAX_CONTENT = 400

TRIAGE_QUERY = (
    "Tu classes des annonces collectees sur des forums et des sites de fuite "
    "de donnees. Pour CHAQUE annonce numerotee, reponds par une ligne :\n"
    "<numero>|<verdict>|<les 4 premiers mots du TITRE, recopies>|"
    "<justification en 10 mots maximum>\n\n"
    "Le titre recopie sert a verifier que tu parles bien de la bonne annonce : "
    "recopie-le tel quel, sans le reformuler.\n\n"
    "Les trois verdicts possibles :\n"
    "- leak : l'annonce designe une organisation VICTIME d'une fuite ou d'un "
    "rancongiciel, ou met en vente des donnees exfiltrees. Sur un site de "
    "fuite, un simple nom d'entreprise EST une victime.\n"
    "- noise : hors perimetre. Vente de comptes ou de logiciels, carding, "
    "tutoriel, service (deverrouillage, spoofing), entraide, vie du forum. "
    "ET SURTOUT : tout ce qui vise une PERSONNE et non une organisation -- "
    "doxxing, divulgation de donnees personnelles, harcelement, recherche "
    "d'individu. Une personne n'est jamais une victime au sens de cet outil, "
    "quel que soit le volume de donnees exposees.\n"
    "- uncertain : tu ne peux pas trancher avec ce qui est fourni.\n\n"
    "Regles impératives :\n"
    "- Reponds UNIQUEMENT par les lignes demandees, une par annonce, sans "
    "introduction ni conclusion.\n"
    "- Conserve les numeros fournis : ils identifient les annonces.\n"
    "- N'invente aucune information absente de l'annonce.\n"
    "- Dans le doute, reponds `uncertain`. C'est un verdict valable, pas un "
    "echec : mieux vaut ne pas trancher que trancher a tort."
)


@dataclass(frozen=True)
class TriageItem:
    """Une annonce soumise a l'arbitrage."""

    key: str
    title: str
    content: str
    source_publishes_victims: bool


@dataclass(frozen=True)
class TriageVerdict:
    verdict: str
    reason: str


def build_triage_prompt(items: list[TriageItem]) -> str:
    """Contenu envoye au LLM pour un lot d'annonces."""
    lignes: list[str] = []
    for index, item in enumerate(items, start=1):
        titre = (item.title or "(sans titre)").strip()[:_MAX_TITLE]
        corps = " ".join((item.content or "").split())[:_MAX_CONTENT]
        # Le type de source est decisif et ne se devine pas du texte : sur un
        # site de fuite, un titre reduit a une raison sociale est une victime,
        # alors que le meme titre sur un forum ne veut rien dire. C'est le
        # meme drapeau qui, cote regles, evitait d'ecarter 18 % des documents
        # de sites de fuite.
        nature = (
            "site de fuite (un document = une victime)"
            if item.source_publishes_victims
            else "forum generaliste"
        )
        lignes.append(f"{index}. [{nature}] TITRE : {titre}")
        if corps:
            lignes.append(f"   EXTRAIT : {corps}")
    return "\n".join(lignes)


# ⚠️ Recherche dans la ligne, pas ancrage en debut de ligne.
#
# Mesure du 2026-09-03 : le modele local est INSTABLE sur la forme. Il rend
# tantot `1|leak|Nitrex|...`, tantot `1. 1|leak|Nitrex|...` (numerotation en
# double), parfois precede de « Here are the answers: », parfois avec une
# justification vide (`1|leak|kioti||`). Un ancrage en debut de ligne rejetait
# silencieusement des reponses pourtant justes.
#
# Ce qui compte est la STRUCTURE `numero|verdict|titre`, ou qu'elle commence.
# La tolerance porte sur la forme ; la verification du titre, elle, ne cede
# rien.
_LIGNE = re.compile(r"(\d+)\s*\|\s*([a-zA-Z]+)\s*\|\s*([^|]*)\|?\s*(.*)$")


def _empreinte(texte: str) -> str:
    """Signature comparable d'un titre : minuscules, sans ponctuation ni
    espaces superflus. Le modele recopie rarement au caractere pres."""
    return re.sub(r"[^a-z0-9]+", "", (texte or "").lower())


def _titre_concorde(attendu: str, echo: str) -> bool:
    """L'echo designe-t-il bien ce titre ?

    Comparaison sur un prefixe, pas sur l'egalite : on demande 4 mots, le
    modele en rend parfois 3 ou 6, avec une ponctuation differente. Un prefixe
    commun de 8 caracteres significatifs suffit a ecarter un decalage, qui
    porterait sur un titre entierement different."""
    a, b = _empreinte(attendu), _empreinte(echo)
    if not a or not b:
        return False
    court = min(len(a), len(b), 8)
    return a[:court] == b[:court]


def parse_triage_response(
    response: str, items: list[TriageItem]
) -> tuple[dict[str, TriageVerdict], int]:
    """Associe chaque annonce a son verdict. Retourne aussi le nombre de lignes
    REJETEES pour desalignement.

    ⚠️ Analyse STRICTE : une annonce dont la reponse est absente, illisible,
    porte un verdict inconnu OU dont l'echo du titre ne concorde pas n'est
    simplement PAS classee. Elle reste `uncertain` cote regles et sera
    representee plus tard.

    Deviner ici serait le pire des choix : on inventerait une decision d'IA
    qu'aucun modele n'a prise, et elle serait indiscernable d'une vraie.

    ⚠️ La verification de l'echo n'est pas une precaution theorique : a 10
    documents par lot, le modele decalait les numeros et attribuait les
    verdicts aux mauvais documents, sans que rien ne le signale.
    """
    par_numero: dict[int, tuple[str, str, str]] = {}
    for ligne in (response or "").splitlines():
        match = _LIGNE.search(ligne)
        if not match:
            continue
        verdict = match.group(2).strip().lower()
        if verdict not in VERDICTS:
            continue
        # Premiere reponse retenue : si le modele se repete, on ne laisse pas
        # la derniere ecraser la premiere en silence.
        # La justification est nettoyee des barres residuelles : le modele
        # rend parfois `1|leak|kioti||`, ou le reste de ligne se reduit a un
        # separateur. Sans cela on stockerait « | » comme motif.
        raison = " ".join(match.group(4).split()).strip("| ")[:200]
        par_numero.setdefault(
            int(match.group(1)),
            (verdict, match.group(3).strip(), raison),
        )

    resultats: dict[str, TriageVerdict] = {}
    rejets = 0
    for index, item in enumerate(items, start=1):
        entree = par_numero.get(index)
        if entree is None:
            continue
        verdict, echo, raison = entree
        if not _titre_concorde(item.title, echo):
            rejets += 1
            continue

        # ⚠️ `noise` est INADMISSIBLE sur une source qui publie des victimes.
        #
        # Meme regle que le classifieur (`announcement_filter` ne declasse
        # jamais en NOISE sur ces sources) : sur un site de fuite, un document
        # EST une victime, et l'absence de vocabulaire de fuite dans son titre
        # n'a aucune valeur informative.
        #
        # Le modele local ignore cette consigne malgre le rappel du prompt.
        # Mesure du 2026-09-03 : **6 documents sur 32** issus de QILIN et ORION
        # marques `noise` -- `Maison-Exemple`, `Traceur-Exemple`, `prix-exemple`, `exemplic`,
        # de vraies victimes, ecartees parce que leur raison sociale
        # « ressemble a un service ». Soit 19 % de faux negatifs sur le cas
        # d'usage principal.
        #
        # On rabat sur `uncertain` plutot que de rejeter : rejeter ferait
        # resoumettre indefiniment le meme document pour le meme verdict. Et
        # jamais sur `leak`, qui inventerait une conclusion que le modele n'a
        # pas tiree.
        if verdict == "noise" and item.source_publishes_victims:
            resultats[item.key] = TriageVerdict(
                "uncertain",
                "verdict noise refuse : la source publie des victimes",
            )
            continue

        resultats[item.key] = TriageVerdict(verdict, raison)
    return resultats, rejets
