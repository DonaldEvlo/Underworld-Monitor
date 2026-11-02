"""Rapport d'alerte : ce qu'on donne au LLM, et ce qu'on lui demande.

Logique PURE (CONTRIBUTING.md §3.3) : assemble des faits deja produits, ne touche ni
la base ni le reseau. La mise en forme PDF et la collecte des donnees vivent
dans `services/report_service.py`.

⚠️ CONFORMITE. Le rapport est destine a SORTIR de l'outil -- c'est le document
qu'un analyste transmet a l'organisation victime. Il ne doit donc contenir que
ce que l'interface affiche deja : valeurs MASQUEES, metadonnees, liens de
preuve. Jamais de valeur brute, jamais le contenu d'une fuite (regle 2). Les
valeurs passees ici viennent de `value_masked`, jamais de `value_hash` ni d'un
contenu de document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# Bornes du prompt. Meme raison que `summarize.py` : des dizaines de lignes
# quasi identiques sont exactement ce qui pousse un LLM a mal compter, alors
# qu'on lui interdit d'inventer un chiffre.
MAX_VALEURS = 40
MAX_DOCUMENTS = 15

REPORT_QUERY = """Tu rediges la SYNTHESE d'un rapport d'incident destine a
l'organisation victime, en francais professionnel.

Structure imposee, en trois paragraphes courts, SANS titre et SANS aucune
mise en forme markdown (pas d'asterisques, pas de dieses, pas de listes) :
1. Ce qui a ete constate (qui revendique quoi, ou, quand).
2. Ce que cela implique concretement pour l'organisation.
3. Ce qu'il est recommande de verifier en priorite.

Regles absolues :
- ⚠️ NE CONFONDS JAMAIS L'ATTAQUANT ET L'OBSERVATEUR. Le groupe cite comme
  « groupe attaquant » est l'AUTEUR PRESUME de l'attaque : il revendique la
  victime, il ne « confirme » rien et ce n'est pas une organisation amie.
  L'agregateur est un tiers qui a vu la MEME publication sur le meme site :
  il confirme que l'annonce existe, il ne verifie pas que la fuite est reelle.
- N'INVENTE AUCUN CHIFFRE et n'utilise QUE les nombres presents dans la
  section « Faits ». Les nombres qui apparaissent dans les extraits d'annonces
  (compteurs de vues, d'images, comptes a rebours) ne sont PAS des faits :
  ne les cite jamais.
- Ne recopie aucune valeur technique masquee (celles avec des etoiles).
- N'affirme jamais que des donnees ont ete diffusees, vendues ou dechiffrees
  si les faits ne le disent pas : distingue ce qui est REVENDIQUE de ce qui
  est CONFIRME.
- Pas de conseil juridique, pas de promesse de resultat.
- 200 mots maximum au total."""


@dataclass(frozen=True)
class ValeurDetectee:
    type: str
    valeur_masquee: str
    occurrences: int
    premiere_vue: datetime | None = None


@dataclass(frozen=True)
class DocumentSource:
    titre: str
    source: str
    collecteur: str
    url: str | None
    publie_le: datetime | None
    collecte_le: datetime | None
    extrait: str | None = None


@dataclass(frozen=True)
class DonneesRapport:
    """Tout ce qu'un rapport doit porter, deja masque et borne."""

    sujet: str
    severite: str
    statut: str
    date_alerte: date
    nombre_detections: int
    corroboration: str | None = None
    gang: str | None = None
    lien_preuve: str | None = None
    # Confirmation par la presse (migration 0030) : seule preuve exterieure
    # au gang. None = aucune confirmation connue, jamais « fuite fausse ».
    lien_presse: str | None = None
    # Credibilite (migration 0031) : niveau technique + preuve lisible.
    credibilite: str | None = None
    preuve_credibilite: str | None = None
    valeurs: list[ValeurDetectee] = field(default_factory=list)
    documents: list[DocumentSource] = field(default_factory=list)
    note_analyste: str | None = None
    # Notation Admiralty (lettre + chiffre + motifs), produite par le CODE --
    # jamais transmise au LLM : il n'a pas a reformuler une notation.
    admiralty: str | None = None
    admiralty_detail: str | None = None
    # Bandeau « en bref » du PDF (2026-10-01) : affichés, jamais transmis au
    # LLM -- ce sont des faits du code, il n'a pas à les reformuler.
    reference: str | None = None
    groupe: str | None = None
    secteur: str | None = None
    pays: str | None = None
    date_attaque: datetime | None = None


def _mot_corroboration(statut: str | None) -> str:
    """⚠️ Le vocabulaire technique ne doit PAS transiter jusqu'au LLM.

    Mesure du 2026-09-02 sur la synthese globale : avec le statut brut
    `exclusive`, le modele a ecrit l'exact contraire de la verite -- il lit
    « exclusif, donc remarquable ». On lui donne donc des phrases, pas des
    etiquettes.
    """
    if statut == "corroborated":
        # ⚠️ PAS « independant » (corrige le 2026-09-26) : l'agregateur lit le
        # MEME site du groupe que nous. Il confirme que l'annonce existe et que
        # notre lecture est juste, pas que la fuite est reelle -- « couverture,
        # pas independance » (2026-09-15). Un rapport destine a la victime ne
        # doit pas suggerer une verification qui n'a pas eu lieu.
        return (
            "annonce RETROUVÉE chez un agrégateur public de sites de fuite, tiers "
            "a l'attaquant (confirme que la revendication existe, pas que la "
            "fuite est réelle)"
        )
    if statut == "exclusive":
        return "vue par nous seuls a ce stade (pas encore reprise ailleurs)"
    return "jamais confrontée à une source tierce"


# ⚠️ Le niveau technique ne transite JAMAIS tel quel jusqu'au LLM : avec le
# statut brut `exclusive`, le modele avait ecrit l'exact contraire de la
# verite (2026-09-02). On lui donne des phrases. `published` en particulier
# reste une DECLARATION du groupe, jamais une verification de notre part.
LIBELLES_CREDIBILITE = {
    "confirmed": "CONFIRMÉE par une source extérieure au groupe (presse ou "
    "déclaration officielle)",
    "doubtful": "DOUTEUSE (des éléments contredisent la revendication)",
    "published": "le groupe AFFIRME avoir mis les données en ligne (déclaration "
    "du groupe, non vérifiée par nous)",
    "claimed": "simple revendication, sans mise en ligne constatée",
    "not_evaluated": "non évaluée",
}


def libelle_credibilite(niveau: str | None) -> str | None:
    return LIBELLES_CREDIBILITE.get(niveau or "")


def build_report_content(donnees: DonneesRapport) -> str:
    """Faits transmis au LLM. Bornes, masques, sans contenu de fuite."""
    lignes = [
        f"Organisation concernée : {donnees.sujet}",
        f"Gravité évaluée : {donnees.severite}",
        f"Date de l'alerte : {donnees.date_alerte.isoformat()}",
        f"Nombre de détections rattachées : {donnees.nombre_detections}",
        f"Vérification externe : {_mot_corroboration(donnees.corroboration)}",
    ]
    if donnees.gang:
        # ⚠️ Le role du groupe est ECRIT EN TOUTES LETTRES. Sans cela, le
        # modele a presente le gang « krybit » comme « l'organisation qui a
        # confirme l'exposition » -- l'attaquant transforme en tiers de
        # confiance, dans un document destine a la victime. Le vocabulaire du
        # prompt est du code.
        lignes.append(
            f"Groupe attaquant qui REVENDIQUE cette victime : {donnees.gang} "
            "(auteur présumé de l'attaque, pas un observateur)"
        )
    if donnees.lien_presse:
        lignes.append(
            "Confirmation extérieure : l'incident a été rapporté par la presse "
            "ou une déclaration officielle (source indépendante du groupe)"
        )
    if libelle_credibilite(donnees.credibilite):
        lignes.append(
            f"Crédibilité de la revendication : {libelle_credibilite(donnees.credibilite)}"
        )
    if donnees.documents:
        sources = sorted({d.source for d in donnees.documents})
        lignes.append(f"Sources où l'organisation apparaît : {', '.join(sources)}")
        dates = [d.publie_le for d in donnees.documents if d.publie_le]
        if dates:
            lignes.append(
                f"Publication la plus ancienne : {min(dates).date().isoformat()} ; "
                f"la plus récente : {max(dates).date().isoformat()}"
            )

    if donnees.valeurs:
        par_type: dict[str, int] = {}
        for valeur in donnees.valeurs:
            par_type[valeur.type] = par_type.get(valeur.type, 0) + valeur.occurrences
        lignes.append(
            "Types de données concernés : "
            + ", ".join(f"{t} ({n})" for t, n in sorted(par_type.items()))
        )

    apercus = [d.extrait for d in donnees.documents[:3] if d.extrait]
    if apercus:
        lignes.append("")
        lignes.append(
            "Extraits des annonces publiques (CONTEXTE seulement : les nombres "
            "qui y figurent sont des compteurs d'affichage, jamais des faits) :"
        )
        lignes.extend(f"- {a[:400]}" for a in apercus)
    return "\n".join(lignes)
