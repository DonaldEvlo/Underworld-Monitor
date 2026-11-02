"""Charte graphique des rapports PDF : UNE identité pour tous les documents.

⚠️ Le rapport d'alerte était un texte noir sur blanc, titres soulignés, faits
en liste à tirets : correct, mais anonyme, et rien n'y distinguait l'essentiel
(gravité, crédibilité, groupe) du détail. Un document qui sort de l'outil pour
être transmis à une organisation doit se reconnaître et se lire en dix
secondes. Les couleurs reprennent celles de l'interface, assombries pour
l'impression (le vert « signal » #3ee8b8 est illisible sur papier blanc).

Contraintes héritées :
- polices intégrées de fpdf2, donc LATIN-1 : tout texte passe par `latin1()` ;
- marquage TLP en tête ET en pied de CHAQUE page : une page isolée garde sa
  consigne de diffusion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from fpdf import FPDF
from fpdf.enums import MethodReturnValue

# --- Couleurs (RVB) -------------------------------------------------------
NUIT = (15, 21, 29)  # fond de l'interface (#0f151d)
NUIT_CLAIR = (28, 39, 51)
SIGNAL = (62, 232, 184)  # marque, sur fond sombre uniquement
SIGNAL_IMPRIME = (14, 128, 102)  # même teinte, lisible sur blanc
ENCRE = (20, 28, 36)
ENCRE_DOUCE = (88, 100, 112)
ENCRE_PALE = (138, 150, 160)
FILET = (214, 220, 226)
FOND_CARTE = (243, 246, 248)
FOND_SIGNAL = (232, 247, 242)
LIEN = (20, 90, 160)
AMBRE_TLP = (255, 192, 0)  # FIRST TLP 2.0

GRAVITES = {
    "critical": ("CRITIQUE", (196, 30, 58)),
    "high": ("ÉLEVÉE", (205, 110, 10)),
    "medium": ("MOYENNE", (34, 110, 170)),
    "low": ("FAIBLE", (100, 110, 120)),
}

_REMPLACEMENTS = {
    "—": "-",
    "–": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    "→": "->",
    "·": "-",
    " ": " ",
    " ": " ",
    "œ": "oe",
    "•": "-",
    "€": "EUR",
    "‹": "<",
    "›": ">",
}


def latin1(texte: str) -> str:
    """Rabat les caractères hors latin-1 (tirets cadratins, guillemets courbes
    d'un LLM) plutôt que d'embarquer une police TTF de plusieurs Mo."""
    for source, cible in _REMPLACEMENTS.items():
        texte = texte.replace(source, cible)
    return texte.encode("latin-1", "replace").decode("latin-1")


class RapportCharte(FPDF):
    """Document A4 à la charte : bandeau d'identité en page 1, rappel discret
    ensuite, pied de page numéroté. `tlp` et `rappel` sont fixés à la
    construction."""

    def __init__(
        self, *, type_document: str, rappel: str, tlp: str, reference: str = ""
    ) -> None:
        super().__init__(format="A4")
        self.type_document = type_document
        self.rappel = rappel
        self.tlp = tlp
        self.reference = reference
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(auto=True, margin=20)
        self.alias_nb_pages()

    # -- en-tête / pied -----------------------------------------------------
    def _badge_tlp(self, x: float, y: float) -> None:
        self.set_font("helvetica", "B", 7.5)
        self.set_char_spacing(0.3)
        largeur = self.get_string_width(self.tlp) + 6
        self.set_fill_color(0, 0, 0)
        self.set_text_color(*AMBRE_TLP)
        self.set_xy(x - largeur, y)
        self.cell(largeur, 5.5, self.tlp, align="C", fill=True)
        self.set_char_spacing(0)

    def header(self) -> None:
        if self.page_no() == 1:
            # Bandeau d'identité, pleine largeur.
            self.set_fill_color(*NUIT)
            self.rect(0, 0, self.w, 30, style="F")
            self.set_fill_color(*SIGNAL)
            self.rect(0, 30, self.w, 0.8, style="F")
            # Marque : un carré « signal » et le nom du produit.
            self.set_fill_color(*SIGNAL)
            self.rect(self.l_margin, 10, 4.5, 4.5, style="F")
            self.set_xy(self.l_margin + 7, 9.2)
            self.set_font("helvetica", "B", 12)
            self.set_char_spacing(1.2)
            self.set_text_color(255, 255, 255)
            self.cell(0, 6, "UNDERWORLD MONITOR")
            self.set_char_spacing(0)
            self.set_xy(self.l_margin + 7, 16)
            self.set_font("helvetica", "", 8.5)
            self.set_text_color(160, 176, 188)
            self.cell(
                0, 5, latin1(f"Veille des fuites de données  -  {self.type_document}")
            )
            self._badge_tlp(self.w - self.r_margin, 8.5)
            self.set_font("helvetica", "", 7.5)
            self.set_text_color(140, 156, 168)
            horodatage = f"généré le {datetime.now(timezone.utc):%d/%m/%Y à %H:%M UTC}"
            if self.reference:
                horodatage = f"réf. {self.reference}  -  {horodatage}"
            texte = latin1(horodatage)
            self.set_xy(self.w - self.r_margin - self.get_string_width(texte), 17)
            self.cell(self.get_string_width(texte), 5, texte)
            self.set_xy(self.l_margin, 38)
        else:
            self.set_font("helvetica", "B", 7.5)
            self.set_text_color(*SIGNAL_IMPRIME)
            self.set_xy(self.l_margin, 8)
            self.set_char_spacing(0.8)
            self.cell(48, 5.5, "UNDERWORLD MONITOR")
            self.set_char_spacing(0)
            self.set_font("helvetica", "", 7.5)
            self.set_text_color(*ENCRE_PALE)
            self.cell(100, 5.5, latin1(self.rappel)[:80])
            self._badge_tlp(self.w - self.r_margin, 8)
            self.set_draw_color(*FILET)
            self.line(self.l_margin, 15.5, self.w - self.r_margin, 15.5)
            self.set_xy(self.l_margin, 20)

    def footer(self) -> None:
        self.set_y(-13)
        self.set_draw_color(*FILET)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-11)
        self.set_font("helvetica", "", 7)
        self.set_text_color(*ENCRE_PALE)
        largeur = (self.w - self.l_margin - self.r_margin) / 3
        self.cell(
            largeur, 5, latin1("Underworld Monitor - observation, jamais exploitation")
        )
        self.set_font("helvetica", "B", 7)
        self.cell(largeur, 5, self.tlp, align="C")
        self.set_font("helvetica", "", 7)
        self.cell(largeur, 5, f"page {self.page_no()} / {{nb}}", align="R")

    # -- briques de mise en page -----------------------------------------------
    @property
    def largeur_utile(self) -> float:
        return self.w - self.l_margin - self.r_margin

    def au_bord(self) -> None:
        """⚠️ `multi_cell(0, …)` part de la position COURANTE : après un `cell`
        la largeur restante tombe à zéro et fpdf lève « Not enough horizontal
        space ». Toujours ramener le curseur à la marge."""
        self.set_x(self.l_margin)

    def hauteur_texte(self, largeur: float, interligne: float, texte: str) -> float:
        lignes = self.multi_cell(
            largeur,
            interligne,
            latin1(texte),
            dry_run=True,
            output=MethodReturnValue.LINES,
        )
        return len(cast(list[str], lignes)) * interligne

    def place_pour(self, hauteur: float) -> None:
        """Change de page si le bloc ne tient pas : un encadré coupé en deux se
        lit mal et perd son fond."""
        if self.get_y() + hauteur > self.h - self.b_margin:
            self.add_page()

    def section(self, numero: int, titre: str) -> None:
        self.place_pour(22)
        self.ln(5)
        self.au_bord()
        self.set_font("helvetica", "B", 9)
        self.set_text_color(*SIGNAL_IMPRIME)
        self.cell(9, 6, f"{numero:02d}")
        self.set_font("helvetica", "B", 11.5)
        self.set_text_color(*ENCRE)
        self.set_char_spacing(0.4)
        self.cell(0, 6, latin1(titre.upper()), new_x="LMARGIN", new_y="NEXT")
        self.set_char_spacing(0)
        self.set_draw_color(*FILET)
        self.line(
            self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1
        )
        self.ln(4)

    def paragraphe(
        self, texte: str, taille: float = 9.5, couleur=ENCRE, interligne: float = 5
    ) -> None:
        self.set_font("helvetica", "", taille)
        self.set_text_color(*couleur)
        self.au_bord()
        self.multi_cell(0, interligne, latin1(texte))
        self.ln(1)

    def encadre(
        self, texte: str, accent=SIGNAL_IMPRIME, fond=FOND_SIGNAL, note: str = ""
    ) -> None:
        """Bloc de texte sur fond teinté, avec un liseré d'accent à gauche."""
        largeur = self.largeur_utile - 10
        self.set_font("helvetica", "", 10)
        h_texte = self.hauteur_texte(largeur, 5.2, texte)
        h_note = 0.0
        if note:
            self.set_font("helvetica", "I", 7.5)
            h_note = self.hauteur_texte(largeur, 4, note) + 2
        hauteur = h_texte + h_note + 8
        self.place_pour(hauteur)
        y = self.get_y()
        self.set_fill_color(*fond)
        self.rect(self.l_margin, y, self.largeur_utile, hauteur, style="F")
        self.set_fill_color(*accent)
        self.rect(self.l_margin, y, 1.4, hauteur, style="F")
        self.set_xy(self.l_margin + 6, y + 4)
        self.set_font("helvetica", "", 10)
        self.set_text_color(*ENCRE)
        self.multi_cell(largeur, 5.2, latin1(texte))
        if note:
            self.set_x(self.l_margin + 6)
            self.ln(1)
            self.set_x(self.l_margin + 6)
            self.set_font("helvetica", "I", 7.5)
            self.set_text_color(*ENCRE_DOUCE)
            self.multi_cell(largeur, 4, latin1(note))
        self.set_xy(self.l_margin, y + hauteur + 2)

    def cartes(
        self,
        elements: list[tuple[str, str, tuple[int, int, int] | None]],
        par_ligne: int = 4,
    ) -> None:
        """Grille de faits clés : petit libellé en capitales, valeur en gras."""
        espace = 3.0
        largeur = (self.largeur_utile - espace * (par_ligne - 1)) / par_ligne
        hauteur = 15.0
        for debut in range(0, len(elements), par_ligne):
            self.place_pour(hauteur + 3)
            y = self.get_y()
            for i, (libelle, valeur, couleur) in enumerate(
                elements[debut : debut + par_ligne]
            ):
                x = self.l_margin + i * (largeur + espace)
                self.set_fill_color(*FOND_CARTE)
                self.rect(x, y, largeur, hauteur, style="F")
                if couleur:
                    self.set_fill_color(*couleur)
                    self.rect(x, y, largeur, 0.9, style="F")
                self.set_xy(x + 3, y + 2.6)
                self.set_font("helvetica", "B", 6.5)
                self.set_char_spacing(0.5)
                self.set_text_color(*ENCRE_PALE)
                self.cell(largeur - 6, 3.5, latin1(libelle.upper()))
                self.set_char_spacing(0)
                self.set_xy(x + 3, y + 7.4)
                self.set_font("helvetica", "B", 10.5)
                self.set_text_color(*(couleur or ENCRE))
                texte = latin1(valeur)
                while self.get_string_width(texte) > largeur - 6 and len(texte) > 4:
                    texte = texte[:-2]
                    texte = texte.rstrip() + "."
                self.cell(largeur - 6, 5, texte)
            self.set_xy(self.l_margin, y + hauteur + espace)

    def ligne_fait(
        self, libelle: str, valeur: str, largeur_libelle: float = 44
    ) -> None:
        """Une ligne libellé / valeur, séparée de la suivante par un filet."""
        largeur = self.largeur_utile - largeur_libelle
        self.set_font("helvetica", "", 9.5)
        hauteur = max(self.hauteur_texte(largeur, 4.8, valeur), 4.8) + 3
        self.place_pour(hauteur)
        y = self.get_y()
        self.set_xy(self.l_margin, y + 1.5)
        self.set_font("helvetica", "B", 8)
        self.set_text_color(*ENCRE_DOUCE)
        self.cell(largeur_libelle, 4.8, latin1(libelle))
        self.set_xy(self.l_margin + largeur_libelle, y + 1.5)
        self.set_font("helvetica", "", 9.5)
        self.set_text_color(*ENCRE)
        self.multi_cell(largeur, 4.8, latin1(valeur))
        self.set_draw_color(*FILET)
        self.line(self.l_margin, y + hauteur, self.w - self.r_margin, y + hauteur)
        self.set_xy(self.l_margin, y + hauteur)

    def pastille(
        self, texte: str, fond, encre=(255, 255, 255), taille: float = 6.5
    ) -> float:
        """Petite étiquette pleine, posée à la position courante. Rend sa largeur."""
        self.set_font("helvetica", "B", taille)
        self.set_char_spacing(0.4)
        largeur = self.get_string_width(latin1(texte)) + 4.5
        self.set_fill_color(*fond)
        self.set_text_color(*encre)
        self.cell(largeur, 4.6, latin1(texte), align="C", fill=True)
        self.set_char_spacing(0)
        return largeur

    def tableau(
        self, entetes: list[tuple[str, float]], lignes: list[list[str]]
    ) -> None:
        """Tableau à en-tête sombre et lignes alternées. Largeurs en mm, la
        dernière à 0 prend le reste."""
        largeurs = [
            w or self.largeur_utile - sum(x for _, x in entetes) for _, w in entetes
        ]
        self.place_pour(14)
        self.au_bord()
        self.set_fill_color(*NUIT_CLAIR)
        self.set_text_color(255, 255, 255)
        self.set_font("helvetica", "B", 7.5)
        self.set_char_spacing(0.4)
        for (titre, _), largeur in zip(entetes, largeurs):
            self.cell(largeur, 6.5, f"  {latin1(titre.upper())}", fill=True)
        self.set_char_spacing(0)
        self.ln(6.5)
        self.set_font("helvetica", "", 8.5)
        for rang, ligne in enumerate(lignes):
            self.place_pour(6)
            self.au_bord()
            self.set_fill_color(*(FOND_CARTE if rang % 2 else (255, 255, 255)))
            self.set_text_color(*ENCRE)
            for valeur, largeur in zip(ligne, largeurs):
                texte = latin1(valeur)
                while self.get_string_width(texte) > largeur - 4 and len(texte) > 4:
                    texte = texte[:-2].rstrip() + "."
                self.cell(largeur, 5.8, f"  {texte}", fill=True)
            self.ln(5.8)

    def barres(
        self, titre: str, lignes: list[tuple[str, int, bool]], couleur=SIGNAL_IMPRIME
    ) -> None:
        """Classement en barres horizontales : libellé, barre proportionnelle,
        valeur. `True` en troisième position marque un secteur critique NIS2
        (barre ambre et étiquette)."""
        if not lignes:
            return
        self.place_pour(10 + 6 * min(len(lignes), 4))
        self.au_bord()
        self.set_font("helvetica", "B", 8)
        self.set_text_color(*ENCRE_DOUCE)
        self.set_char_spacing(0.4)
        self.cell(0, 5, latin1(titre.upper()), new_x="LMARGIN", new_y="NEXT")
        self.set_char_spacing(0)
        maximum = max(v for _, v, _ in lignes) or 1
        largeur_libelle, largeur_valeur = 58.0, 12.0
        largeur_barre = self.largeur_utile - largeur_libelle - largeur_valeur - 4
        for libelle, valeur, critique in lignes:
            self.place_pour(6)
            y = self.get_y()
            self.set_xy(self.l_margin, y)
            self.set_font("helvetica", "", 8.5)
            self.set_text_color(*ENCRE)
            texte = latin1(libelle)
            while (
                self.get_string_width(texte) > largeur_libelle - 14 and len(texte) > 4
            ):
                texte = texte[:-2].rstrip() + "."
            self.cell(largeur_libelle - 13, 5, texte)
            if critique:
                self.set_font("helvetica", "B", 6)
                self.set_fill_color(*GRAVITES["high"][1])
                self.set_text_color(255, 255, 255)
                self.cell(10, 3.6, "NIS2", align="C", fill=True)
            x = self.l_margin + largeur_libelle
            self.set_fill_color(*FOND_CARTE)
            self.rect(x, y + 1, largeur_barre, 3, style="F")
            # « non renseigné » et « autres » ne sont pas des catégories : en gris.
            neutre = libelle.strip().lower() in ("non renseigné", "autres")
            self.set_fill_color(
                *(
                    GRAVITES["high"][1]
                    if critique
                    else ENCRE_PALE if neutre else couleur
                )
            )
            self.rect(
                x, y + 1, max(largeur_barre * valeur / maximum, 0.8), 3, style="F"
            )
            self.set_xy(x + largeur_barre + 2, y)
            self.set_font("helvetica", "B", 8.5)
            self.set_text_color(*ENCRE)
            self.cell(largeur_valeur, 5, str(valeur), align="R")
            self.set_xy(self.l_margin, y + 5.6)
        self.ln(2)
