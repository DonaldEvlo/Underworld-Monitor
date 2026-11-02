"""Nom de groupe attaquant, tel qu'un analyste doit le lire.

⚠️ Le nom de SOURCE porte des suffixes qui decrivent NOTRE collecte, pas le
groupe : « LOCKBIT 3.0 (New Dark mirror 1) (DLS) ». Les afficher tels quels sur
une carte de menace noierait le nom du gang sous notre plomberie.
"""

import pytest

from app.pipeline.collect.source_naming import (
    group_display_name as _nom_de_groupe,
)


class TestNomDeGroupe:
    @pytest.mark.parametrize(
        "source,attendu",
        [
            ("LOCKBIT 3.0 (New Dark mirror 1) (DLS)", "LOCKBIT 3.0"),
            ("KRYBIT (DLS)", "KRYBIT"),
            ("AKIRA (ransomware leak site)", "AKIRA"),
            ("NIGHT SPIRE (DLS)", "NIGHT SPIRE"),
            ("BREACH FORUMS (Dark)", "BREACH FORUMS"),
        ],
    )
    def test_les_suffixes_de_collecte_sont_retires(self, source, attendu):
        assert _nom_de_groupe(source) == attendu

    def test_les_suffixes_s_enchainent(self):
        """Plusieurs suffixes se cumulent sur une meme source : les retirer un
        par un ne suffirait pas, il faut boucler."""
        assert _nom_de_groupe("BEAST (mirror 2) (DLS)") == "BEAST"

    def test_une_parenthese_PORTEUSE_DE_SENS_est_conservee(self):
        """⚠️ Ne pas tout couper : « (BASHEE) » est l'autre nom du gang, pas un
        detail de collecte. Un nettoyage trop large ferait perdre l'alias sous
        lequel il est connu."""
        assert _nom_de_groupe("APT73 (BASHEE) (DLS)") == "APT73 (BASHEE)"
        assert _nom_de_groupe("MYDATA / ALPHA LOCKER (DLS)") == "MYDATA / ALPHA LOCKER"

    def test_un_nom_sans_suffixe_est_inchange(self):
        assert _nom_de_groupe("EXILIO404") == "EXILIO404"

    def test_un_nom_entierement_suffixe_ne_devient_pas_vide(self):
        """Garde-fou : mieux vaut un nom technique qu'une ligne sans libelle."""
        assert _nom_de_groupe("(DLS)") == "(DLS)"
