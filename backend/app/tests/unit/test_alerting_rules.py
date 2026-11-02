import uuid
from datetime import datetime, timezone

import pytest

from app.contracts.alert import AlertSeverity
from app.contracts.detection import DetectionContract, DetectionType
from app.pipeline.alerting.matching import MATCHABLE_DETECTION_TYPES
from app.pipeline.alerting.rules import (
    ALERT_THRESHOLD,
    detections_to_alert,
    severity_for_detection,
    should_alert,
)


def _make_detection(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "type": DetectionType.EMAIL,
        "value_masked": "j***@example.test",
        "value_hash": "deadbeef",
        "validated": False,
        "is_relevant": False,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return DetectionContract(**defaults)


class TestSeverityForDetection:
    def test_not_relevant_is_low(self):
        detection = _make_detection(
            is_relevant=False, validated=True, type=DetectionType.CARD
        )
        assert severity_for_detection(detection) == "low"

    def test_relevant_but_not_validated_is_medium(self):
        detection = _make_detection(
            is_relevant=True, validated=False, type=DetectionType.EMAIL
        )
        assert severity_for_detection(detection) == "medium"

    def test_match_on_watched_entity_lifts_a_non_relevant_detection(self):
        """Le rattachement a une entite surveillee est un critere de pertinence
        a part entiere : sans cela, une victime de ransomware revendiquee dont
        le document ne contient aucun mot de la watchlist restait en LOW et
        n'alertait jamais (constate en usage reel sur les annonces
        d'agregateur, voir docstring de severity_for_detection)."""
        detection = _make_detection(
            is_relevant=False, validated=False, type=DetectionType.DOMAIN
        )
        assert severity_for_detection(detection) == "low"
        assert (
            severity_for_detection(detection, matches_watched_entity=True) == "medium"
        )

    def test_match_on_watched_entity_keeps_critical_type_critical(self):
        detection = _make_detection(
            is_relevant=False, validated=True, type=DetectionType.CARD
        )
        assert (
            severity_for_detection(detection, matches_watched_entity=True) == "critical"
        )

    def test_relevant_detection_is_unaffected_by_the_entity_flag(self):
        """Le flag ne fait que relever un plancher : il ne change rien pour une
        detection deja pertinente."""
        detection = _make_detection(
            is_relevant=True, validated=True, type=DetectionType.PHONE
        )
        assert severity_for_detection(detection) == "medium"
        assert (
            severity_for_detection(detection, matches_watched_entity=True) == "medium"
        )

    def test_validated_alone_no_longer_lifts_a_non_critical_type(self):
        """⚠️ Changement du 2026-09-04, mesure a l'appui.

        `validated` n'eleve plus que les types a validation REELLE (Luhn,
        mod-97). Ailleurs le drapeau ne mesure rien : `organization` est
        valide a 100 % (2414/2414) et `domain` a 13 %, ces 13 % etant
        exclusivement des `.onion` -- « format reconnu », pas « fait
        confirme ». Sans cette restriction, rendre `organization`
        rattachable faisait passer TOUTE victime nommee en HIGH d'un coup.

        Effet sur l'existant, verifie en base avant d'appliquer : les 657
        detections concernees sont toutes des `.onion`, **aucune** ne porte
        de severite et **aucune** n'est rattachee a une alerte. Le code
        rejoint la doctrine deja ecrite le 2026-09-01 : HIGH vient de la
        corroboration."""
        detection = _make_detection(
            is_relevant=True, validated=True, type=DetectionType.PHONE
        )
        assert severity_for_detection(detection) == "medium"

    def test_relevant_and_validated_critical_type_is_critical(self):
        detection = _make_detection(
            is_relevant=True, validated=True, type=DetectionType.CARD
        )
        assert severity_for_detection(detection) == "critical"

    def test_iban_and_credentials_are_also_critical_types(self):
        for critical_type in (DetectionType.IBAN, DetectionType.CREDENTIALS):
            detection = _make_detection(
                is_relevant=True, validated=True, type=critical_type
            )
            assert severity_for_detection(detection) == "critical"

    def test_domain_is_never_critical_even_when_validated_and_relevant(self):
        # DOMAIN a un validateur (voir detect/patterns/domain.py) mais n'est
        # pas dans _CRITICAL_TYPES -- doit plafonner a HIGH, pas CRITICAL.
        detection = _make_detection(
            is_relevant=True, validated=True, type=DetectionType.DOMAIN
        )
        assert severity_for_detection(detection) == "medium"
        # ⚠️ Depuis le 2026-09-15 c'est l'exposition d'identifiants qui porte
        # HIGH, plus la corroboration (devenue une marque de verifiabilite).
        assert (
            severity_for_detection(detection, privileged_credential_exposure=True)
            == AlertSeverity.HIGH
        )
        assert severity_for_detection(detection, corroborated=True) == "medium"


class TestShouldAlert:
    def test_low_never_alerts(self):
        assert should_alert("low") is False

    def test_medium_and_above_alert(self):
        assert should_alert("medium") is True
        assert should_alert("high") is True
        assert should_alert("critical") is True

    def test_threshold_is_medium(self):
        assert ALERT_THRESHOLD == "medium"


class TestDetectionsToAlert:
    def test_filters_out_low_severity_detections(self):
        low = _make_detection(is_relevant=False)
        medium = _make_detection(is_relevant=True, validated=False)
        result = detections_to_alert([low, medium])
        assert result == [(medium, "medium")]

    def test_empty_input_returns_empty_list(self):
        assert detections_to_alert([]) == []

    def test_preserves_order_and_pairs_correct_severity(self):
        critical = _make_detection(
            is_relevant=True, validated=True, type=DetectionType.IBAN
        )
        medium = _make_detection(
            is_relevant=True, validated=True, type=DetectionType.DOMAIN
        )
        result = detections_to_alert([critical, medium])
        assert result == [(critical, "critical"), (medium, "medium")]


class TestCorroborationLiftsSeverity:
    """La branche HIGH etait INATTEIGNABLE : elle exige `validated=true` sur une
    detection rattachee, or les 1216 detections `domain` validees du corpus sont
    toutes des `.onion` et aucun email n'est jamais valide -- un `.onion` ne
    matche jamais un selecteur clearnet surveille. Mesure du 2026-09-01 :
    0 des 692 rattachements valide, 120 alertes sur 120 en `medium`. La
    taxonomie a 4 niveaux ne produisait qu'une seule valeur.

    `corroborated` (voir enrich/ransomlook_corroboration.py) porte desormais
    cette elevation : un observateur independant confirme la victime."""

    def test_corroboration_seule_n_eleve_plus(self):
        """⚠️ REECRIT le 2026-09-15 (arbitrage de projet). La corroboration
        est une marque de VERIFIABILITE, pas un facteur de risque : sur un
        incident ancien, qu'un tiers publie la meme annonce confirme notre
        lecture, cela ne rend pas la fuite plus urgente.

        Mesure qui l'a impose : 31 des 33 alertes reelles etaient corroborees,
        et l'ancienne regle aurait bascule 30 sur 33 en CRITICAL -- la
        troisieme constante en trois tentatives."""
        detection = _make_detection(type=DetectionType.DOMAIN, value_masked="acme.sn")
        assert (
            severity_for_detection(
                detection, matches_watched_entity=True, corroborated=True
            )
            == AlertSeverity.MEDIUM
        )

    def test_corroboration_n_eleve_plus_meme_sur_un_incident_frais(self):
        """⚠️ REECRIT le 2026-09-26 (phase 7). Avant : frais ET corrobore ->
        CRITICAL. Avec la collecte toutes les 3 h, presque toute victime
        nouvelle est fraiche ET indexee par les agregateurs en quelques heures
        (mesure d'avance du 2026-09-26 : 0 victime vue avant eux) -- la regle
        serait devenue une constante. La corroboration est l'axe CREDIBILITE."""
        detection = _make_detection(type=DetectionType.DOMAIN, value_masked="acme.sn")
        assert (
            severity_for_detection(
                detection,
                matches_watched_entity=True,
                corroborated=True,
                incident_is_fresh=True,
            )
            == AlertSeverity.MEDIUM
        )

    def test_same_detection_without_corroboration_stays_medium(self):
        """Temoin : c'est bien la corroboration qui eleve, rien d'autre."""
        detection = _make_detection(type=DetectionType.DOMAIN, value_masked="acme.sn")
        assert (
            severity_for_detection(detection, matches_watched_entity=True)
            == AlertSeverity.MEDIUM
        )

    def test_corroboration_lifts_the_low_floor_for_an_unwatched_victim(self):
        """Decision du 2026-09-01 : une victime corroboree n'est JAMAIS LOW,
        meme sans rattachement ni `is_relevant`.

        Motif mesure : `is_relevant` vient d'une watchlist de vocabulaire de
        menace, si bien qu'une annonce factuelle (« Groupe X / Victime Y ») en
        sort a false alors que c'est le signal le plus fiable du corpus. 28 des
        65 victimes corroborees retombaient ainsi en LOW, donc invisibles.

        C'est ce qui donne une severite aux institutions HORS perimetre de
        surveillance -- sans pour autant leur creer une alerte."""
        detection = _make_detection(type=DetectionType.DOMAIN, is_relevant=False)
        # ⚠️ Le plancher est bien LEVE (la victime cesse d'etre invisible),
        # mais a MEDIUM et non plus HIGH : depuis le 2026-09-15 la
        # corroboration n'eleve plus au-dela du plancher sur un incident
        # ancien.
        assert (
            severity_for_detection(detection, corroborated=True) == AlertSeverity.MEDIUM
        )

    def test_an_uncorroborated_unwatched_detection_stays_low(self):
        """Temoin : le plancher LOW existe toujours. Seule la corroboration le
        leve -- pas l'absence de rattachement a elle seule, sinon tout le corpus
        remonterait."""
        detection = _make_detection(type=DetectionType.DOMAIN, is_relevant=False)
        assert severity_for_detection(detection) == AlertSeverity.LOW

    def test_corroboration_does_not_downgrade_a_validated_detection(self):
        """`exclusive`/`unknown` arrivent ici en `corroborated=False`. Ils ne
        doivent RIEN abaisser : ne pas etre corrobore n'est pas un doute (nous
        lisons le site de fuite a la source, l'agregateur peut ne pas l'avoir
        indexe)."""
        detection = _make_detection(
            type=DetectionType.DOMAIN, validated=True, is_relevant=True
        )
        # `validated` ne porte plus HIGH (voir
        # test_validated_alone_no_longer_lifts_a_non_critical_type) : le point
        # verifie ici est que l'ABSENCE de corroboration n'abaisse rien
        # au-dessous du plancher MEDIUM.
        assert (
            severity_for_detection(detection, corroborated=False)
            == AlertSeverity.MEDIUM
        )

    def test_default_is_not_corroborated(self):
        """Le defaut ne doit pas elever silencieusement : un appelant qui ignore
        la corroboration obtient exactement le comportement d'avant."""
        detection = _make_detection(type=DetectionType.DOMAIN)
        assert (
            severity_for_detection(detection, matches_watched_entity=True)
            == AlertSeverity.MEDIUM
        )


class TestCriticalBranchIsDeliberatelyUnreachable:
    """La branche CRITICAL exige un type `card`/`iban`/`credentials` rattache a
    une entite, or `matching.py` ne gere que DOMAIN/EMAIL : elle ne peut pas
    etre atteinte par le chemin d'alerting.

    Ce n'est PAS un oubli mais une decision de perimetre du 2026-09-01. Les 153
    detections `card` eligibles (validees ET pertinentes) viennent de forums de
    carding ; les rattacher a une organisation supposerait de passer par le
    porteur de la carte, donc de traiter de la PII d'individus -- contraire aux
    regles 1 et 2 de CONTRIBUTING.md.

    Ces tests verrouillent l'intention : la fonction sait toujours produire
    CRITICAL (si le perimetre changeait un jour), mais aucun type matchable ne
    peut y arriver."""

    def test_function_still_produces_critical_for_a_card(self):
        detection = _make_detection(
            type=DetectionType.CARD, validated=True, is_relevant=True
        )
        assert severity_for_detection(detection) == AlertSeverity.CRITICAL

    def test_no_matchable_type_can_ever_be_critical(self):
        for type_ in MATCHABLE_DETECTION_TYPES:
            detection = _make_detection(
                type=DetectionType(type_),
                validated=True,
                is_relevant=True,
            )
            severity = severity_for_detection(
                detection, matches_watched_entity=True, corroborated=True
            )
            assert severity != AlertSeverity.CRITICAL, type_


class TestEchelleNonConstante:
    """⚠️ Le defaut que ces regles corrigent : la taxonomie rendait UNE valeur.

    Mesure du 2026-09-04 : les 32 alertes reelles etaient toutes `medium`, et
    les 243 detections rattachees se repartissaient pourtant entre un site de
    fuite (40 %) et un forum (59 %) -- deux choses qui ne disent pas la meme
    chose. Sur un site de fuite le gang PUBLIE l'organisation comme sa victime
    (0 % de bruit d'infrastructure mesure le 2026-08-26) ; sur un forum, elle
    est mentionnee (34 a 96 % de bruit).
    """

    def _rattachee(self, **kw):
        return _make_detection(
            type=DetectionType.DOMAIN, is_relevant=True, validated=False, **kw
        )

    def test_forum_reste_moyen(self):
        """Une mention sur un forum est un signalement, pas une revendication."""
        assert (
            severity_for_detection(self._rattachee(), matches_watched_entity=True)
            == AlertSeverity.MEDIUM
        )

    def test_revendiquee_sans_volume_reste_moyenne(self):
        """⚠️ Le piege evite : faire monter TOUTE victime revendiquee donnait
        94 % de HIGH sur les alertes reelles -- aussi peu utile que 100 % de
        MEDIUM. Etre publie sur un site de fuite est le cas NORMAL de nos
        alertes, pas l'exception."""
        assert (
            severity_for_detection(
                self._rattachee(),
                matches_watched_entity=True,
                victim_published_by_attacker=True,
            )
            == AlertSeverity.MEDIUM
        )

    def test_volume_annonce_n_eleve_plus_seul(self):
        """⚠️ REECRIT le 2026-09-15. Le volume avait ete retenu le 2026-09-04
        FAUTE DE MIEUX -- il fallait un critere partageant la population des
        victimes revendiquees. L'exposition d'identifiants dit desormais la
        meme chose en mieux : non pas « le gang se vante d'un gros butin »
        mais « un chemin d'intrusion existe ».

        Le parametre reste accepte et reste AFFICHE a l'analyste ; il n'est
        simplement plus un levier de gravite."""
        assert (
            severity_for_detection(
                self._rattachee(),
                matches_watched_entity=True,
                victim_published_by_attacker=True,
                announced_volume=True,
            )
            == AlertSeverity.MEDIUM
        )

    def test_exposition_privilegiee_est_elevee(self):
        """Des identifiants d'EMPLOYES de l'organisation figurent dans des logs
        de voleurs : c'est un chemin d'intrusion actif.

        ⚠️ La distinction employe / client porte sur le ROLE vis-a-vis de
        l'organisation, JAMAIS sur la personne, et repose sur des COMPTEURS --
        aucun identifiant n'est detenu (regle 2)."""
        assert (
            severity_for_detection(
                self._rattachee(),
                matches_watched_entity=True,
                privileged_credential_exposure=True,
            )
            == AlertSeverity.HIGH
        )

    def test_volume_seul_sans_revendication_ne_suffit_pas(self):
        """Un volume cite sur un forum n'est pas une revendication : les deux
        criteres se cumulent, ils ne se remplacent pas."""
        assert (
            severity_for_detection(
                self._rattachee(),
                matches_watched_entity=True,
                announced_volume=True,
            )
            == AlertSeverity.MEDIUM
        )

    def test_revendiquee_et_corroboree_mais_ANCIENNE_reste_moyenne(self):
        """⚠️ REECRIT le 2026-09-15 -- le cas le plus important du fichier.

        C'est exactement la combinaison qui decrivait 30 de nos 33 alertes.
        Age reel des victimes alertees : mediane 140 jours, jusqu'a 956 jours
        (LockBit = incidents de 2023). Les faire toutes passer CRITICAL
        remplacait une constante par une autre."""
        assert (
            severity_for_detection(
                self._rattachee(),
                matches_watched_entity=True,
                victim_published_by_attacker=True,
                corroborated=True,
            )
            == AlertSeverity.MEDIUM
        )

    def test_secteur_critique_ancien_est_eleve(self):
        """Phase 7 (2026-09-26) : la gravite mesure l'IMPACT. Une
        administration, un hopital, une banque, un reseau d'energie ou de
        transport touche est plus grave qu'une PME, quel que soit l'age."""
        assert (
            severity_for_detection(
                self._rattachee(),
                matches_watched_entity=True,
                victim_published_by_attacker=True,
                critical_sector=True,
            )
            == AlertSeverity.HIGH
        )

    def test_secteur_critique_FRAIS_est_critique(self):
        """Temoin symetrique : a secteur egal, seul l'AGE distingue HIGH de
        CRITICAL -- l'organisation a encore le temps d'agir."""
        assert (
            severity_for_detection(
                self._rattachee(),
                matches_watched_entity=True,
                victim_published_by_attacker=True,
                critical_sector=True,
                incident_is_fresh=True,
            )
            == AlertSeverity.CRITICAL
        )

    def test_fraicheur_SEULE_ne_suffit_pas(self):
        """Temoin : un incident recent mais sans corroboration ni exposition
        n'est pas critique. La fraicheur MODULE les autres criteres, elle
        n'est pas un critere a elle seule -- sinon toute nouvelle alerte
        naitrait CRITICAL et l'echelle redeviendrait une constante, dans
        l'autre sens."""
        assert (
            severity_for_detection(
                self._rattachee(),
                matches_watched_entity=True,
                victim_published_by_attacker=True,
                incident_is_fresh=True,
            )
            == AlertSeverity.MEDIUM
        )

    def test_les_quatre_niveaux_sont_atteignables(self):
        """Temoin d'ensemble : c'est ce test qui echouait avant, l'echelle ne
        produisant qu'une valeur."""
        obtenues = {
            severity_for_detection(_make_detection(is_relevant=False)),
            severity_for_detection(self._rattachee(), matches_watched_entity=True),
            # HIGH : des identifiants d'employes circulent.
            severity_for_detection(
                self._rattachee(),
                matches_watched_entity=True,
                privileged_credential_exposure=True,
            ),
            # CRITICAL : incident FRAIS dans un secteur critique. ⚠️ Cette
            # branche rend 0 sur le corpus actuel (aucun incident sous 30
            # jours -- rattrapage historique) ; ce test prouve qu'elle reste
            # ATTEIGNABLE, ce qu'aucune mesure en base ne peut montrer.
            severity_for_detection(
                self._rattachee(),
                matches_watched_entity=True,
                victim_published_by_attacker=True,
                critical_sector=True,
                incident_is_fresh=True,
            ),
        }
        assert obtenues == {
            AlertSeverity.LOW,
            AlertSeverity.MEDIUM,
            AlertSeverity.HIGH,
            AlertSeverity.CRITICAL,
        }

    def test_le_drapeau_ne_contourne_pas_le_plancher_bas(self):
        """⚠️ Une detection ni pertinente, ni rattachee, ni corroboree reste
        LOW meme venant d'un site de fuite : la provenance qualifie la
        gravite, elle ne remplace pas le rattachement."""
        assert (
            severity_for_detection(
                _make_detection(is_relevant=False), victim_published_by_attacker=True
            )
            == AlertSeverity.LOW
        )


class TestSecteursCritiques:
    """Liste reprise de NIS2 (annexe I), dans le vocabulaire `activity` de
    ransomware.live releve le 2026-09-26 (14 valeurs sur 3 637 victimes)."""

    @pytest.mark.parametrize(
        "secteur",
        [
            "Government & Defense",
            "Healthcare",
            "Financial Services",
            "Energy & Utilities",
            "Transportation",
        ],
    )
    def test_secteurs_critiques(self, secteur):
        from app.pipeline.alerting.rules import is_critical_sector

        assert is_critical_sector(secteur) is True

    @pytest.mark.parametrize(
        "secteur",
        [
            "Professional Services",
            "Manufacturing",
            "Technology",
            "Education",
            "Retail & E-Commerce",
            "Hospitality",
            "Other",
            "",
            None,
        ],
    )
    def test_autres_secteurs_et_inconnu_n_elevent_rien(self, secteur):
        """Un secteur INCONNU n'eleve pas : une donnee absente ne doit pas
        faire monter la gravite."""
        from app.pipeline.alerting.rules import is_critical_sector

        assert is_critical_sector(secteur) is False

    def test_fraicheur_seule_sans_secteur_critique_reste_moyenne(self):
        """Sinon toute victime nouvelle (collecte a 3 h) naitrait CRITICAL."""
        detection = _make_detection(type=DetectionType.DOMAIN, is_relevant=True)
        assert (
            severity_for_detection(
                detection, matches_watched_entity=True, incident_is_fresh=True
            )
            == AlertSeverity.MEDIUM
        )
