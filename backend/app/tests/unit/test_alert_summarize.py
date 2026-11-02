from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.pipeline.alerting.summarize import (
    _MAX_DETECTION_GROUPS,
    _build_alert_content,
    summarize_alert,
)


class _FakeDetection:
    def __init__(self, type_: str, value_masked: str, validated: bool):
        self.type = type_
        self.value_masked = value_masked
        self.validated = validated
        self.created_at = datetime(2026, 8, 11, tzinfo=timezone.utc)


class _FakeAlertDetection:
    def __init__(self, detection: _FakeDetection):
        self.detection = detection


class _FakeAlert:
    def __init__(self, severity: str, detections: list[_FakeAlertDetection]):
        self.alert_date = date(2026, 8, 11)
        self.severity = severity
        self.detections = detections


# `_build_alert_content` et `summarize_alert` prennent desormais le SUJET de
# l'alerte sous forme de chaine, et non une entite : une alerte de perimetre
# geographique (migration 0016) n'en a aucune.
class TestBuildAlertContent:
    def test_includes_entity_severity_and_masked_values_only(self):
        detections = [
            _FakeAlertDetection(_FakeDetection("domain", "operateur.sn", True)),
            _FakeAlertDetection(_FakeDetection("email", "j***@operateur.sn", False)),
        ]
        alert = _FakeAlert("high", detections)
        entity = "Operateur SN"

        content = _build_alert_content(alert, entity)

        assert "Operateur SN" in content
        assert "high" in content
        assert "operateur.sn" in content
        assert "j***@operateur.sn" in content
        # Jamais de valeur brute -- seules les valeurs deja masquees
        # transitent (voir docstring module).
        assert "@operateur.sn" not in content.replace("j***@operateur.sn", "")

    def test_reports_detection_count(self):
        detections = [
            _FakeAlertDetection(_FakeDetection("domain", "a.tld", True)),
            _FakeAlertDetection(_FakeDetection("domain", "b.tld", True)),
        ]
        alert = _FakeAlert("medium", detections)
        content = _build_alert_content(alert, "Test")
        assert "2" in content


class TestSummarizeAlert:
    @pytest.mark.asyncio
    async def test_calls_generate_response_with_built_content(self):
        alert = _FakeAlert(
            "critical",
            [_FakeAlertDetection(_FakeDetection("credentials", "user***", True))],
        )
        entity = "Test entity"

        with patch(
            "app.pipeline.alerting.summarize.generate_response",
            new_callable=AsyncMock,
        ) as mock_generate:
            mock_generate.return_value = "Resume de l'alerte Test entity."
            result = await summarize_alert(alert, entity, "ollama:llama3")

        assert result == "Resume de l'alerte Test entity."
        mock_generate.assert_awaited_once()
        call_args = mock_generate.call_args
        assert call_args.args[0] == "ollama:llama3"
        assert "Test entity" in call_args.args[1]


class TestPromptIsBounded:
    """Le contenu envoye au LLM listait une ligne par detection rattachee, sans
    borne : 144 lignes sur la plus grosse alerte reelle (Organisation Exemple). Il est
    desormais regroupe par valeur distincte et borne a
    `_MAX_DETECTION_GROUPS`.

    Regrouper plutot que tronquer n'est pas un detail : sur cette alerte, les
    144 lignes se reduisent a 28 valeurs distinctes, le masquage ramenant des
    dizaines d'adresses differentes a la meme chaine. La borne ne coupe donc
    rien en pratique -- elle garantit seulement que le prompt ne peut plus
    croitre indefiniment avec le corpus."""

    def test_groups_identical_masked_values_with_a_count(self):
        detections = [
            _FakeAlertDetection(
                _FakeDetection("email", "a***@organisation-exemple.int", False)
            )
            for _ in range(14)
        ]
        content = _build_alert_content(
            _FakeAlert("medium", detections), "Organisation Exemple"
        )

        # Une seule ligne de detection, portant le compte -- pas 14 lignes.
        assert content.count("a***@organisation-exemple.int") == 1
        assert "occurrences=14" in content
        # Le total reel reste annonce : le regroupement ne doit pas faire
        # perdre l'information de volume.
        assert "Nombre de détections rattachées : 14" in content
        assert "Nombre de valeurs distinctes : 1" in content

    def test_caps_the_number_of_listed_groups(self):
        detections = [
            _FakeAlertDetection(_FakeDetection("domain", f"victime{i}.example", False))
            for i in range(_MAX_DETECTION_GROUPS + 12)
        ]
        content = _build_alert_content(_FakeAlert("medium", detections), "Test")

        listed = [line for line in content.splitlines() if line.startswith("- type=")]
        assert len(listed) == _MAX_DETECTION_GROUPS

    def test_announces_the_omitted_groups_instead_of_cutting_silently(self):
        """Couper en silence ferait croire au LLM qu'il voit tout, alors que le
        prompt lui interdit d'inventer un chiffre et lui demande de signaler ce
        qui manque -- encore faut-il que le contenu le dise."""
        detections = [
            _FakeAlertDetection(_FakeDetection("domain", f"victime{i}.example", False))
            for i in range(_MAX_DETECTION_GROUPS + 12)
        ]
        content = _build_alert_content(_FakeAlert("medium", detections), "Test")

        assert "12 autres valeurs distinctes non listées" in content
        assert f"Nombre de valeurs distinctes : {_MAX_DETECTION_GROUPS + 12}" in content

    def test_no_omission_notice_when_everything_fits(self):
        detections = [
            _FakeAlertDetection(_FakeDetection("domain", "a.example", False)),
            _FakeAlertDetection(_FakeDetection("domain", "b.example", False)),
        ]
        content = _build_alert_content(_FakeAlert("low", detections), "Test")
        assert "non listées" not in content

    def test_most_frequent_groups_are_kept_first(self):
        """La troncature garde les valeurs les plus frequentes : si elle doit
        couper, elle coupe le moins significatif."""
        detections = [
            _FakeAlertDetection(_FakeDetection("domain", "rare.example", False))
        ]
        detections += [
            _FakeAlertDetection(_FakeDetection("domain", f"bruit{i}.example", False))
            for i in range(_MAX_DETECTION_GROUPS)
            for _ in range(3)
        ]
        content = _build_alert_content(_FakeAlert("medium", detections), "Test")

        # `rare.example` (1 occurrence) sort du top-50 face a 50 valeurs a 3.
        assert "rare.example" not in content
        assert "1 autres valeurs distinctes non listées" in content

    def test_keeps_the_earliest_detection_date_of_a_group(self):
        """L'anteriorite du signal est ce qui interesse l'analyste : le groupe
        porte la date la PLUS ANCIENNE, pas celle rencontree en dernier."""
        old = _FakeDetection("email", "a***@test.tld", False)
        old.created_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
        recent = _FakeDetection("email", "a***@test.tld", False)
        recent.created_at = datetime(2026, 8, 30, tzinfo=timezone.utc)

        content = _build_alert_content(
            _FakeAlert(
                "medium", [_FakeAlertDetection(recent), _FakeAlertDetection(old)]
            ),
            "Test",
        )
        assert "premiere_detection_le=2026-08-01" in content

    def test_still_never_leaks_a_raw_value(self):
        """Le regroupement ne doit pas avoir rouvert la regle 2 : seules des
        valeurs deja masquees transitent."""
        detections = [
            _FakeAlertDetection(_FakeDetection("email", "j***@operateur.sn", False))
            for _ in range(5)
        ]
        content = _build_alert_content(_FakeAlert("medium", detections), "Operateur SN")
        assert "@operateur.sn" not in content.replace("j***@operateur.sn", "")


class TestContexteEnrichi:
    """Le modele doit recevoir les faits d'enrichissement de l'alerte, et
    jamais le drapeau `validated` la ou il ne mesure rien (2026-09-28 : il
    ecrivait « domaines non valides » sur une victime critique corroboree)."""

    def _alerte(self, **attrs):
        alert = _FakeAlert(
            "critical",
            [
                _FakeAlertDetection(
                    _FakeDetection("domain", "compagnie-aerienne.co.tz", False)
                )
            ],
        )
        for cle, valeur in attrs.items():
            setattr(alert, cle, valeur)
        return alert

    def test_le_gang_est_presente_comme_attaquant(self):
        content = _build_alert_content(
            self._alerte(corroborated_groups=["krybit", "lockbit5"]), "X"
        )
        assert "REVENDIQUE la victime : krybit" in content
        assert "auteur présumé" in content
        assert "lockbit5" in content

    def test_secteur_pays_date_et_credibilite_transmis(self):
        content = _build_alert_content(
            self._alerte(
                victim_sector="Transportation",
                victim_country="TZ",
                victim_attack_date=datetime(2026, 9, 24, tzinfo=timezone.utc),
                credibility_level="published",
                corroboration_status="corroborated",
            ),
            "X",
        )
        assert "Transportation" in content
        assert "TZ" in content
        assert "2026-09-24" in content
        assert "AFFIRME" in content
        # Jamais le statut technique brut (le modele l'avait lu a l'envers).
        assert "corroborated" not in content
        assert "pas que la fuite est réelle" in content

    def test_validee_absent_pour_un_domaine(self):
        content = _build_alert_content(self._alerte(), "X")
        assert "validee" not in content

    def test_validee_conserve_pour_une_carte(self):
        alert = _FakeAlert(
            "high", [_FakeAlertDetection(_FakeDetection("card", "4***1111", True))]
        )
        assert "validee=True" in _build_alert_content(alert, "X")

    def test_une_alerte_sans_enrichissement_reste_resumable(self):
        content = _build_alert_content(self._alerte(), "X")
        assert "REVENDIQUE" not in content
        assert "Secteur" not in content


class TestPlusieursVictimes:
    """Alerte regionale a plusieurs victimes : gangs, secteur et pays sont
    portes par l'ALERTE. Le modele a ecrit « krybit revendique Suivi Flotte »
    alors que Suivi Flotte est une victime de DIRE WOLF (2026-09-28)."""

    VICTIMES = [
        ("Suivi Flotte Holdings", "direwolf"),
        ("www.domaine-exemple.co.za", "krybit"),
    ]

    def _alerte(self):
        alert = _FakeAlert(
            "high",
            [
                _FakeAlertDetection(
                    _FakeDetection("domain", "suivi-flotte.co.za", False)
                )
            ],
        )
        alert.corroborated_groups = ["krybit", "direwolf"]
        alert.victim_sector = "Transportation"
        alert.victim_country = "ZA"
        alert.press_evidence_url = "https://example.org/article"
        return alert

    def test_chaque_victime_porte_son_propre_gang(self):
        content = _build_alert_content(self._alerte(), "X", self.VICTIMES)
        assert "Suivi Flotte Holdings : revendiquée par direwolf" in content
        assert "www.domaine-exemple.co.za : revendiquée par krybit" in content
        assert "n'attribue jamais le groupe d'une victime à une autre" in content

    def test_le_gang_de_niveau_alerte_n_est_plus_attribue(self):
        content = _build_alert_content(self._alerte(), "X", self.VICTIMES)
        assert "REVENDIQUE la victime : krybit" not in content

    def test_secteur_et_pays_de_niveau_alerte_omis(self):
        content = _build_alert_content(self._alerte(), "X", self.VICTIMES)
        assert "Transportation" not in content
        assert "Pays de la victime" not in content

    def test_la_presse_est_bornee_a_une_des_victimes(self):
        content = _build_alert_content(self._alerte(), "X", self.VICTIMES)
        assert "pour au moins une des victimes" in content

    def test_une_seule_victime_garde_le_contexte_complet(self):
        content = _build_alert_content(
            self._alerte(), "X", [("Suivi Flotte Holdings", "direwolf")]
        )
        assert "REVENDIQUE la victime : krybit" in content
        assert "Transportation" in content


class TestReponseHorsSujet:
    """2026-09-28 : « Il semble que votre message ait ete interrompu... » rendu
    deux fois pour cgcgabon par la passe de pre-generation. Un resume qui ne
    cite rien de l'alerte est redemande, puis refuse."""

    HORS_SUJET = (
        "Il semble que votre message ait été interrompu ou incomplet. "
        "Je suis la pour vous aider."
    )

    def _alerte(self):
        alert = _FakeAlert(
            "medium",
            [
                _FakeAlertDetection(
                    _FakeDetection("domain", "www.chantier-exemple.ga", False)
                )
            ],
        )
        alert.corroborated_groups = ["krybit"]
        return alert

    async def _resumer(self, reponses):
        with patch(
            "app.pipeline.alerting.summarize.generate_response",
            new_callable=AsyncMock,
        ) as mock_generate:
            mock_generate.side_effect = reponses
            try:
                return (
                    await summarize_alert(
                        self._alerte(), "chantier-exemple.com", "ollama:qwen3:8b"
                    ),
                    mock_generate.await_count,
                )
            except ValueError:
                return None, mock_generate.await_count

    @pytest.mark.asyncio
    async def test_une_reponse_hors_sujet_est_redemandee(self):
        resume, appels = await self._resumer(
            [self.HORS_SUJET, "Le groupe krybit revendique www.chantier-exemple.ga."]
        )
        assert resume == "Le groupe krybit revendique www.chantier-exemple.ga."
        assert appels == 2

    @pytest.mark.asyncio
    async def test_deux_reponses_hors_sujet_ne_sont_jamais_enregistrees(self):
        resume, appels = await self._resumer([self.HORS_SUJET, self.HORS_SUJET])
        assert resume is None
        assert appels == 2

    @pytest.mark.asyncio
    async def test_le_gras_markdown_est_retire(self):
        resume, _ = await self._resumer(["Le groupe **krybit** revendique la victime."])
        assert resume == "Le groupe krybit revendique la victime."

    @pytest.mark.asyncio
    async def test_une_reponse_vide_est_refusee(self):
        resume, _ = await self._resumer(["", "  "])
        assert resume is None
