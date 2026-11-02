"""Rapport d'alerte en PDF : rassemble, fait rediger par le LLM, met en forme.

⚠️ C'est le document qui SORT de l'outil. Jusqu'ici l'analyste qui voulait
transmettre un dossier a une organisation victime n'avait que des captures
d'ecran : aucun export n'existait nulle part et ce fichier etait vide.

⚠️ CONFORMITE (regle 2). Le rapport ne contient que ce que l'interface affiche
deja : valeurs MASQUEES, metadonnees, liens de preuve. Jamais de valeur brute,
jamais le contenu d'une fuite. Les extraits de documents cites sont les
annonces PUBLIQUES des attaquants, tronquees.

⚠️ fpdf2 plutot que WeasyPrint/Playwright : pur Python, aucune bibliotheque
systeme, et le resultat est un VRAI fichier -- il peut donc etre joint a
l'email envoye a l'organisation, ce qu'un rendu HTML imprime par le navigateur
ne permettrait pas.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.llm.client import generate_response
from app.db.models.alert import Alert, AlertDetection
from app.db.models.detection import Detection
from app.db.models.entity import Entity
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.pipeline.alerting.admiralty import TLP_DEFINITION, TLP_RAPPORT
from app.pipeline.reporting.charte_pdf import (
    ENCRE,
    ENCRE_DOUCE,
    ENCRE_PALE,
    FILET,
    FOND_CARTE,
    GRAVITES,
    LIEN,
    SIGNAL_IMPRIME,
    RapportCharte,
)
from app.pipeline.reporting.charte_pdf import latin1 as _latin1
from app.pipeline.reporting.governance import SECTEURS_FR
from app.pipeline.collect.dls.scraper import neutraliser_compteurs
from app.pipeline.reporting.nommage import nom_de_fichier
from app.pipeline.reporting.alert_report import (
    MAX_DOCUMENTS,
    MAX_VALEURS,
    REPORT_QUERY,
    DocumentSource,
    DonneesRapport,
    ValeurDetectee,
    build_report_content,
    libelle_credibilite,
)
from app.pipeline.alerting.subject import region_alert_subject
from app.services.admiralty_service import rate_alerts, victim_claims, victim_titles

logger = logging.getLogger(__name__)


def sujet_alerte(db: Session, alert: Alert) -> str:
    """Libelle lisible de ce que l'alerte concerne.

    ℹ️ Vivait dans `notification_service`, supprime avec la notion de
    destinataire le 2026-09-05. Deplace ici, son seul appelant restant.
    """
    if alert.entity_id is not None:
        entity = db.query(Entity).filter(Entity.id == alert.entity_id).first()
        if entity is not None:
            return entity.name
    if alert.scope == "region" and alert.region:
        return region_alert_subject(
            alert.region, victim_titles(db, [alert]).get(alert.id, [])
        )
    return "Alerte"


# Libellés courts du bandeau « en bref » (la phrase complète reste dans les faits).
CREDIBILITE_COURTE = {
    "confirmed": "Confirmée",
    "doubtful": "Douteuse",
    "published": "Publiée",
    "claimed": "Revendiquée",
    "not_evaluated": "Non évaluée",
}
STATUTS = {"open": "ouverte", "acknowledged": "acquittée", "resolved": "résolue"}


def collecter_donnees(db: Session, alert: Alert) -> DonneesRapport:
    """Rassemble tout ce qui est pertinent pour cette alerte."""
    lignes = (
        db.query(Detection, RawDocument, Source)
        .join(AlertDetection, AlertDetection.detection_id == Detection.id)
        .join(RawDocument, RawDocument.id == Detection.document_id)
        .join(Source, Source.id == RawDocument.source_id)
        .filter(AlertDetection.alert_id == alert.id)
        .all()
    )

    # Regroupement par valeur distincte plutot que troncature : le masquage
    # ramene souvent des dizaines d'adresses a la meme chaine (meme raison que
    # summarize.py). On borne SANS rien perdre.
    groupes: dict[tuple[str, str], ValeurDetectee] = {}
    for detection, _document, _source in lignes:
        cle = (detection.type, detection.value_masked or "")
        existant = groupes.get(cle)
        if existant is None:
            groupes[cle] = ValeurDetectee(
                type=detection.type,
                valeur_masquee=detection.value_masked or "",
                occurrences=1,
                premiere_vue=detection.created_at,
            )
        else:
            groupes[cle] = ValeurDetectee(
                type=existant.type,
                valeur_masquee=existant.valeur_masquee,
                occurrences=existant.occurrences + 1,
                premiere_vue=min(
                    (
                        d
                        for d in (existant.premiere_vue, detection.created_at)
                        if d is not None
                    ),
                    default=None,
                ),
            )

    documents: dict[uuid.UUID, DocumentSource] = {}
    for _detection, document, source in lignes:
        if document.id in documents:
            continue
        # ⚠️ On neutralise les compteurs AVANT de montrer l'extrait au LLM et
        # au lecteur : sans cela le modele a repris « 46 175 vues » comme un
        # fait de l'incident dans un rapport destine a la victime. Meme
        # fonction que celle qui protege la deduplication.
        extrait = neutraliser_compteurs(
            re.sub(r"\s+", " ", document.content or "")
        ).strip()
        documents[document.id] = DocumentSource(
            titre=document.title or "(sans titre)",
            source=source.name,
            collecteur=document.collector,
            url=document.url,
            publie_le=document.published_at,
            collecte_le=document.fetched_at,
            extrait=extrait[:600] or None,
        )

    note = rate_alerts(db, [alert]).get(alert.id)
    return DonneesRapport(
        admiralty=note.libelle() if note else None,
        admiralty_detail=(
            f"source : {note.source_name or 'n/d'} ({note.source.motif}) ; "
            f"information : {note.information.motif}"
            if note
            else None
        ),
        sujet=sujet_alerte(db, alert),
        severite=alert.severity,
        statut=alert.status,
        date_alerte=alert.alert_date,
        nombre_detections=len(lignes),
        corroboration=alert.corroboration_status,
        gang=alert.corroborated_group,
        lien_preuve=alert.corroboration_evidence_url,
        lien_presse=alert.press_source_url or alert.press_evidence_url,
        credibilite=alert.credibility_level,
        preuve_credibilite=alert.credibility_evidence,
        valeurs=sorted(
            groupes.values(), key=lambda v: (-v.occurrences, v.type, v.valeur_masquee)
        )[:MAX_VALEURS],
        documents=list(documents.values())[:MAX_DOCUMENTS],
        note_analyste=alert.analyst_note,
        reference=str(alert.id)[:8],
        groupe=alert.corroborated_group or _premier_groupe(db, alert),
        secteur=(
            SECTEURS_FR.get(alert.victim_sector, alert.victim_sector)
            if alert.victim_sector
            else None
        ),
        pays=alert.victim_country,
        date_attaque=alert.victim_attack_date,
    )


def _premier_groupe(db: Session, alert: Alert) -> str | None:
    """Groupe lu sur la SOURCE quand aucun agrégateur ne l'a attribué
    (documents RansomLook, jamais corroborés)."""
    return next((gang for _, gang in victim_claims(db, alert) if gang), None)


async def rediger_synthese(donnees: DonneesRapport, model_name: str) -> str:
    """Fait rediger la synthese par le LLM. Un echec n'empeche PAS le rapport.

    ⚠️ Le rapport reste utile sans le LLM : les faits, les sources et les liens
    de preuve sont produits par le code. La synthese est un confort de
    lecture, pas la substance -- si le modele est indisponible, on le dit dans
    le document plutot que de refuser de le produire.
    """
    try:
        return (
            await generate_response(
                model_name,
                build_report_content(donnees),
                REPORT_QUERY,
                temperature=settings.SUMMARY_LLM_TEMPERATURE,
            )
        ).strip()
    except Exception:
        logger.warning("Synthèse IA indisponible pour le rapport", exc_info=True)
        return ""


def _pdf(donnees: DonneesRapport, synthese: str, model_name: str) -> bytes:
    """Rapport d'alerte à la charte (`pipeline/reporting/charte_pdf`).

    Ordre de lecture voulu : QUI est touché et à quel point (bandeau « en
    bref »), CE QUE L'ON EN DIT (synthèse), CE QUI EST ÉTABLI (faits), CE QUI
    SE VÉRIFIE (preuves), puis le détail. Un destinataire pressé s'arrête
    après le bandeau et sait déjà l'essentiel.
    """
    libelle, couleur = GRAVITES.get(
        donnees.severite, (donnees.severite.upper(), ENCRE_DOUCE)
    )
    titre, _, contexte = donnees.sujet.partition(" — ")

    pdf = RapportCharte(
        type_document="Rapport d'alerte",
        rappel=f"Rapport d'alerte - {titre}",
        tlp=TLP_RAPPORT,
        reference=donnees.reference or "",
    )
    pdf.set_title(_latin1(f"Rapport d'alerte - {donnees.sujet}"))
    pdf.set_author("Underworld Monitor")
    pdf.add_page()

    # --- Titre : la victime, avec le liseré de sa gravité --------------------
    y = pdf.get_y()
    pdf.set_fill_color(*couleur)
    pdf.rect(pdf.l_margin, y, 1.6, 19, style="F")
    pdf.set_xy(pdf.l_margin + 5, y)
    pdf.set_font("helvetica", "B", 7)
    pdf.set_char_spacing(0.8)
    pdf.set_text_color(*ENCRE_PALE)
    pdf.cell(0, 4, _latin1("ORGANISATION CONCERNÉE"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_char_spacing(0)
    pdf.set_x(pdf.l_margin + 5)
    pdf.set_font("helvetica", "B", 19)
    pdf.set_text_color(*ENCRE)
    pdf.multi_cell(pdf.largeur_utile - 5, 8.5, _latin1(titre))
    pdf.set_x(pdf.l_margin + 5)
    pdf.pastille(f"GRAVITÉ {libelle}", couleur)
    pdf.set_font("helvetica", "", 8.5)
    pdf.set_text_color(*ENCRE_DOUCE)
    contexte_ligne = contexte.strip()
    pdf.cell(
        0,
        4.6,
        _latin1(
            "   "
            + "   -   ".join(
                x
                for x in [
                    contexte_ligne,
                    f"alerte du {donnees.date_alerte.strftime('%d/%m/%Y')}",
                    STATUTS.get(donnees.statut, donnees.statut),
                ]
                if x
            )
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(6)

    # --- En bref ----------------------------------------------------------
    credibilite_courte = CREDIBILITE_COURTE.get(
        donnees.credibilite or "", "non évaluée"
    )
    code_admiralty = (donnees.admiralty or "").split(" ")[0] or "-"
    pdf.cartes(
        [
            ("Gravité", libelle.capitalize(), couleur),
            (
                "Crédibilité",
                credibilite_courte,
                SIGNAL_IMPRIME if donnees.credibilite == "confirmed" else None,
            ),
            ("Notation Admiralty", code_admiralty, None),
            ("Groupe revendicateur", donnees.groupe or "non attribué", None),
            ("Secteur", donnees.secteur or "non renseigné", None),
            ("Pays déclaré", donnees.pays or "non renseigné", None),
            (
                "Date de l'attaque",
                (
                    donnees.date_attaque.strftime("%d/%m/%Y")
                    if donnees.date_attaque
                    else "non datée"
                ),
                None,
            ),
            ("Détections", str(donnees.nombre_detections), None),
        ]
    )

    # --- 01 Synthèse -------------------------------------------------------
    pdf.section(1, "Synthèse")
    if synthese:
        pdf.encadre(
            synthese,
            note=(
                f"Rédigée par le modèle {model_name} à partir des faits ci-dessous ; "
                "à relire avant transmission. Le modèle n'établit aucun fait."
            ),
        )
    else:
        pdf.encadre(
            "Synthèse automatique indisponible au moment de la génération. "
            "Les faits ci-dessous restent complets et vérifiables.",
            accent=ENCRE_PALE,
            fond=FOND_CARTE,
        )

    # --- 02 Faits établis ----------------------------------------------------
    pdf.section(2, "Faits établis")
    if donnees.corroboration == "corroborated":
        verification = (
            "Annonce retrouvée chez un agrégateur public de sites de fuite"
            + (f" (groupe {donnees.gang})" if donnees.gang else "")
            + ". Cela confirme que la revendication existe, pas que la fuite est réelle."
        )
    elif donnees.corroboration == "exclusive":
        # ⚠️ `exclusive` n'est PAS un doute : nous lisons le site à la source,
        # l'agrégateur ne l'a peut-être pas encore indexé.
        verification = (
            "Non reprise à ce jour par la source tierce consultée "
            "(cela ne remet pas en cause la détection)."
        )
    else:
        verification = "Non effectuée pour cette alerte."
    pdf.ligne_fait("Vérification externe", verification)
    pdf.ligne_fait(
        "Confirmation presse",
        (
            "Incident rapporté par la presse ou une déclaration officielle."
            if donnees.lien_presse
            else "Aucune connue à ce jour (la presse couvre surtout les grandes organisations, "
            "et avec retard : ce n'est pas un signe de fuite fausse)."
        ),
    )
    if donnees.admiralty:
        pdf.ligne_fait(
            "Notation Admiralty",
            donnees.admiralty
            + (f". {donnees.admiralty_detail}" if donnees.admiralty_detail else ""),
        )
    if libelle_credibilite(donnees.credibilite):
        pdf.ligne_fait(
            "Crédibilité",
            f"{libelle_credibilite(donnees.credibilite)}"
            + (f". {donnees.preuve_credibilite}" if donnees.preuve_credibilite else ""),
        )

    # --- 03 Preuves consultables ----------------------------------------------
    pdf.section(3, "Preuves consultables")
    pdf.paragraphe(
        "Chaque preuve se vérifie sans cet outil. Une adresse .onion exige le réseau "
        "Tor ; une preuve clearnet s'ouvre dans un navigateur ordinaire.",
        taille=8.5,
        couleur=ENCRE_DOUCE,
    )
    preuves: list[tuple[str, tuple[int, int, int], str]] = []
    if donnees.lien_presse:
        preuves.append(("PRESSE", SIGNAL_IMPRIME, donnees.lien_presse))
    if donnees.lien_preuve:
        preuves.append(("CLEARNET - CITABLE", LIEN, donnees.lien_preuve))
    for document in donnees.documents:
        if document.url:
            preuves.append(("TOR - NON CLIQUABLE", ENCRE_DOUCE, document.url))
    for etiquette, teinte, lien in preuves:
        pdf.place_pour(12)
        pdf.au_bord()
        largeur = pdf.pastille(etiquette, teinte)
        pdf.set_font("helvetica", "", 8.5)
        pdf.set_text_color(*(LIEN if teinte != ENCRE_DOUCE else ENCRE_DOUCE))
        pdf.set_x(pdf.l_margin + largeur + 2.5)
        pdf.multi_cell(pdf.largeur_utile - largeur - 2.5, 4.6, _latin1(lien)[:200])
        pdf.ln(1.5)
    if not preuves:
        pdf.paragraphe("Aucune preuve consultable rattachée à cette alerte.", taille=9)

    # --- 04 Éléments détectés --------------------------------------------------
    numero = 4
    if donnees.valeurs:
        pdf.section(numero, "Éléments détectés")
        numero += 1
        pdf.paragraphe(
            "Valeurs masquées : aucune valeur sensible n'est conservée en clair.",
            taille=8.5,
            couleur=ENCRE_DOUCE,
        )
        pdf.tableau(
            [("Type", 36), ("Valeur masquée", 0), ("Occurrences", 26)],
            [[v.type, v.valeur_masquee, str(v.occurrences)] for v in donnees.valeurs],
        )

    # --- Sources ------------------------------------------------------------
    if donnees.documents:
        pdf.section(numero, "Sources à l'origine de l'alerte")
        numero += 1
        for document in donnees.documents:
            dates = []
            if document.publie_le:
                dates.append(f"publié le {document.publie_le.strftime('%d/%m/%Y')}")
            if document.collecte_le:
                dates.append(f"collecté le {document.collecte_le.strftime('%d/%m/%Y')}")
            pdf.place_pour(20)
            pdf.au_bord()
            pdf.set_font("helvetica", "B", 9.5)
            pdf.set_text_color(*ENCRE)
            pdf.multi_cell(0, 5, _latin1(document.titre)[:140])
            pdf.paragraphe(
                f"{document.source} (collecteur {document.collecteur})"
                + (" - " + ", ".join(dates) if dates else ""),
                taille=8,
                couleur=ENCRE_PALE,
                interligne=4.2,
            )
            if document.extrait:
                pdf.encadre(
                    f"« {document.extrait[:360]} »", accent=FILET, fond=FOND_CARTE
                )
            pdf.ln(1)

    if donnees.note_analyste:
        pdf.section(numero, "Note de l'analyste")
        pdf.encadre(donnees.note_analyste, accent=ENCRE_DOUCE, fond=FOND_CARTE)

    # --- Cadre ----------------------------------------------------------------
    pdf.ln(3)
    pdf.encadre(
        "Ce rapport résulte d'une OBSERVATION de sources publiques du dark web. "
        "Aucun identifiant n'a été exploité, aucune donnée fuitée n'a été "
        "téléchargée ni rediffusée, aucune personne n'a été désanonymisée. "
        "Les valeurs sensibles y figurent uniquement sous forme masquée.",
        accent=ENCRE,
        fond=FOND_CARTE,
        note=f"{TLP_RAPPORT} : {TLP_DEFINITION}",
    )
    return bytes(pdf.output())


async def generer_rapport_pdf(
    db: Session, alert: Alert, model_name: str
) -> tuple[bytes, str]:
    """PDF du rapport et nom de fichier propose."""
    donnees = collecter_donnees(db, alert)
    synthese = await rediger_synthese(donnees, model_name)
    nom = nom_de_fichier(donnees.sujet)
    return _pdf(donnees, synthese, model_name), (
        f"rapport-{nom}-{donnees.date_alerte.isoformat()}.pdf"
    )
