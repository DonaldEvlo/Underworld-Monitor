"""Tests de pipeline/alerting/digest.py -- la synthese globale des alertes.

Le module est pur : il construit le contenu envoye au LLM, sans appel reseau.
Ce sont donc les FORMULATIONS qui sont testees ici, parce que ce sont elles
qui ont produit des erreurs factuelles en usage reel.
"""

from datetime import date, datetime, timezone

from app.api.routers.alerts import _libelle_scope
from app.contracts.alert import AlertStatus
from app.pipeline.alerting.digest import (
    _MAX_ALERTS_DETAILED,
    DIGEST_QUERY,
    build_digest_content,
)


class _FakeDetection:
    def __init__(self, value_masked: str):
        self.value_masked = value_masked


class _FakeLink:
    def __init__(self, value_masked: str):
        self.detection = _FakeDetection(value_masked)


class _FakeAlert:
    def __init__(
        self,
        *,
        severity="medium",
        status="open",
        entity_id=None,
        scope="entity",
        region=None,
        corroboration_status=None,
        corroborated_group=None,
        valeurs=("acme.sn",),
        alert_date=None,
    ):
        self.id = f"alerte-{valeurs[0]}-{region}"
        self.severity = severity
        self.status = status
        self.entity_id = entity_id
        self.scope = scope
        self.region = region
        self.corroboration_status = corroboration_status
        self.corroborated_group = corroborated_group
        self.alert_date = alert_date or date(2026, 9, 2)
        self.created_at = datetime.now(timezone.utc)
        self.detections = [_FakeLink(v) for v in valeurs]


class TestCorroborationIsUnambiguous:
    """⚠️ Le defaut qui a motive ces tests. Avec `confirmation=exclusive` dans
    le contenu, le modele a rendu « seule Organisation Exemple a ete verifiee par un
    observateur tiers » -- exactement l'inverse : Organisation Exemple etait `exclusive`,
    et Domaine Exemple la seule corroboree.

    « Exclusive » se lit spontanement comme « exclusif, donc remarquable ». Une
    synthese qui se trompe sur ce qui est confirme est pire qu'une absence de
    synthese : le contenu ne transporte donc plus le statut technique."""

    def test_a_corroborated_alert_says_so_in_plain_words(self):
        contenu = build_digest_content(
            [
                _FakeAlert(
                    corroboration_status="corroborated",
                    corroborated_group="krybit",
                    valeurs=("domaine-exemple.co.za",),
                )
            ],
            {},
        )
        assert "CONFIRMÉE par un observateur tiers" in contenu
        assert "krybit" in contenu

    def test_an_exclusive_alert_is_never_called_exclusive(self):
        contenu = build_digest_content(
            [_FakeAlert(corroboration_status="exclusive")], {}
        )
        assert "exclusive" not in contenu.lower()
        assert "vue par nous seuls" in contenu

    def test_never_confronted_is_distinct_from_not_confirmed(self):
        """`None` est une ABSENCE DE MESURE, pas un resultat negatif."""
        contenu = build_digest_content([_FakeAlert(corroboration_status=None)], {})
        assert "jamais confrontée" in contenu

    def test_the_prompt_forbids_inventing_geographic_counts(self):
        """Essai reel : le modele avait annonce « 11 alertes en Afrique du Sud,
        5 en Egypte » alors que le contenu ne porte aucun regroupement de ce
        genre."""
        assert "AUCUN décompte par pays" in DIGEST_QUERY


class TestRegionAlertsAreLabelled:
    def test_a_region_alert_says_the_victim_was_not_declared(self):
        """Sans cette mention, le modele presente une alerte regionale comme
        une organisation surveillee de plus -- alors que son interet est
        precisement que PERSONNE ne l'avait declaree."""
        contenu = build_digest_content(
            [_FakeAlert(scope="region", region="Afrique", entity_id=None)], {}
        )
        assert "périmètre Afrique (victime non déclarée)" in contenu


class TestContentIsBounded:
    def test_caps_the_number_of_detailed_alerts_and_announces_the_rest(self):
        alertes = [
            _FakeAlert(valeurs=(f"victime{i}.tld",))
            for i in range(_MAX_ALERTS_DETAILED + 7)
        ]
        contenu = build_digest_content(alertes, {})
        listees = [
            ligne
            for ligne in contenu.splitlines()
            if ligne.startswith("- ") and "|" in ligne
        ]
        assert len(listees) == _MAX_ALERTS_DETAILED
        # Le surplus est ANNONCE, jamais coupe en silence.
        assert "7 alertes de moindre gravité non détaillées" in contenu
        assert f"Nombre total d'alertes : {_MAX_ALERTS_DETAILED + 7}" in contenu

    def test_caps_the_values_listed_per_alert(self):
        """L'alerte Organisation Exemple porte 144 detections : les enumerer noierait la
        synthese, mais le compte total doit rester visible."""
        contenu = build_digest_content(
            [_FakeAlert(valeurs=tuple(f"v{i}.tld" for i in range(30)))], {}
        )
        assert "et 25 autres" in contenu
        assert "30 détection(s)" in contenu

    def test_severity_comes_first_so_truncation_drops_the_least_serious(self):
        graves = [
            _FakeAlert(severity="high", valeurs=(f"grave{i}.tld",)) for i in range(3)
        ]
        faibles = [
            _FakeAlert(severity="low", valeurs=(f"faible{i}.tld",))
            for i in range(_MAX_ALERTS_DETAILED)
        ]
        contenu = build_digest_content(faibles + graves, {})
        for i in range(3):
            assert f"grave{i}.tld" in contenu

    def test_no_alert_yields_an_explicit_message(self):
        assert build_digest_content([], {}) == "Aucune alerte ouverte."


class TestLibelleDePerimetre:
    """Le perimetre resume doit etre ENONCE avec le texte.

    ⚠️ Un resume dont on ignore l'assiette n'est pas verifiable : « 3 alertes »
    a cote d'une liste de 120 est incomprehensible. Meme raison que le
    perimetre affiche par le test de disponibilite des sources, ajoute apres
    que « 37/44 joignables » a cote de « 9 sources actives » se soit revele
    illisible a l'usage.
    """

    def test_sans_filtre_dit_explicitement_toutes(self):
        """« toutes » est la seule formulation qui ne laisse pas croire a un
        cadrage qui n'existe pas."""
        libelle = _libelle_scope(None, None, None)
        assert "toutes severites" in libelle
        assert "toutes dates" in libelle

    def test_severites_ordonnees_de_la_plus_grave(self):
        """L'ordre de lecture d'un analyste, pas l'ordre de saisie."""
        libelle = _libelle_scope(["medium", "critical", "high"], None, None)
        assert "sévérité critical, high, medium" in libelle

    def test_journee_et_statut_rapportes(self):
        libelle = _libelle_scope(["high"], date(2026, 9, 4), AlertStatus.OPEN)
        assert "journée du 2026-09-04" in libelle
        assert "statut open" in libelle
