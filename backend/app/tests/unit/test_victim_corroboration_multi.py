"""Double revendication domaine + nom (mesure du 2026-09-11).

Cas reel : `transports-exemple.com` est publiee par NIGHT SPIRE (qui publie
des RAISONS SOCIALES) et par KRYBIT (qui publie des domaines). Trouvee par
domaine chez KRYBIT, la victime lue sur le site de NIGHT SPIRE etait
attribuee a KRYBIT seul -- la revendication du gang de la source, pourtant
indexee par son nom, disparaissait."""

from app.pipeline.enrich.ransomlook_corroboration import (
    CorroborationStatus,
    build_victim_index,
    corroborate_victim,
)


def _index():
    return build_victim_index(
        [],
        {
            "krybit": [
                {
                    "post_title": "transports-exemple.com",
                    "discovered": "2026-08-05T00:00:00Z",
                }
            ],
            "nightspire": [
                {
                    "post_title": "Transportes Exemple",
                    "discovered": "2026-08-02T00:00:00Z",
                }
            ],
        },
    )


class TestDomaineEtNomDuGangDeLaSource:
    def test_le_gang_de_la_source_reste_attribue_en_premier(self):
        verdict = corroborate_victim(
            ["transports-exemple.com"],
            ["Transportes Exemple"],
            _index(),
            expected_group="nightspire",
        )
        assert verdict.status is CorroborationStatus.CORROBORATED
        assert verdict.match == "domain"
        assert verdict.groups == ["nightspire", "krybit"]

    def test_sans_nom_de_la_victime_seul_le_domaine_compte(self):
        verdict = corroborate_victim(
            ["transports-exemple.com"], [], _index(), expected_group="nightspire"
        )
        assert verdict.groups == ["krybit"]

    def test_nom_d_un_autre_gang_n_est_jamais_ajoute(self):
        """Le complement par nom reste borne au gang de la source."""
        verdict = corroborate_victim(
            ["transports-exemple.com"],
            ["Transportes Exemple"],
            _index(),
            expected_group="qilin",
        )
        assert verdict.groups == ["krybit"]
