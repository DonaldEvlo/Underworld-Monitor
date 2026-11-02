import uuid
from datetime import datetime, timezone

from app.contracts.detection import DetectionContract, DetectionType
from app.contracts.entity import EntityContract, EntitySelector, SelectorType
from app.pipeline.alerting.matching import (
    matchable_detection_types,
    matching_entities,
    most_specific,
    value_matches_watched_entity,
)


def _make_detection(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "type": DetectionType.DOMAIN,
        "value_masked": "operateur.sn",
        "value_hash": "deadbeef",
        "validated": True,
        "is_relevant": False,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return DetectionContract(**defaults)


def _make_entity(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "name": "Test Org",
        "selectors": [EntitySelector(type=SelectorType.DOMAIN, value="operateur.sn")],
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return EntityContract(**defaults)


class TestDomainMatching:
    def test_exact_domain_matches(self):
        detection = _make_detection(value_masked="operateur.sn")
        entity = _make_entity()
        assert matching_entities(detection, [entity]) == [entity]

    def test_real_subdomain_matches(self):
        detection = _make_detection(value_masked="mail.operateur.sn")
        entity = _make_entity()
        assert matching_entities(detection, [entity]) == [entity]

    def test_similar_but_different_domain_does_not_match(self):
        detection = _make_detection(value_masked="not-operateur.sn")
        entity = _make_entity()
        assert matching_entities(detection, [entity]) == []

    def test_selector_as_a_trailing_label_of_a_bigger_domain_does_not_match(self):
        # "operateur.sn" n'est ici qu'un prefixe de labels dans "operateur.sn.evil.com"
        # (labels terminaux = evil.com), pas un vrai suffixe -- ne doit pas matcher.
        detection = _make_detection(value_masked="operateur.sn.evil.com")
        entity = _make_entity()
        assert matching_entities(detection, [entity]) == []

    def test_case_is_normalized_before_comparison(self):
        detection = _make_detection(value_masked="Operateur.SN")
        entity = _make_entity()
        assert matching_entities(detection, [entity]) == [entity]

    def test_trailing_dot_is_normalized_before_comparison(self):
        detection = _make_detection(value_masked="operateur.sn.")
        entity = _make_entity()
        assert matching_entities(detection, [entity]) == [entity]

    def test_inactive_entity_is_ignored(self):
        detection = _make_detection(value_masked="operateur.sn")
        entity = _make_entity(active=False)
        assert matching_entities(detection, [entity]) == []

    def test_no_entity_matches_returns_empty_list(self):
        detection = _make_detection(value_masked="unrelated.example")
        entity = _make_entity()
        assert matching_entities(detection, [entity]) == []


class TestEmailDomainMatching:
    def test_email_domain_extracted_from_masked_value_matches(self):
        detection = _make_detection(
            type=DetectionType.EMAIL, value_masked="j***@operateur.sn"
        )
        entity = _make_entity(
            selectors=[
                EntitySelector(type=SelectorType.EMAIL_DOMAIN, value="operateur.sn")
            ]
        )
        assert matching_entities(detection, [entity]) == [entity]

    def test_email_domain_does_not_match_domain_selector(self):
        # Un email sur operateur.sn ne doit matcher que le selecteur email_domain,
        # pas un selecteur domain meme identique en valeur -- types distincts.
        detection = _make_detection(
            type=DetectionType.EMAIL, value_masked="j***@operateur.sn"
        )
        entity = _make_entity(
            selectors=[EntitySelector(type=SelectorType.DOMAIN, value="operateur.sn")]
        )
        assert matching_entities(detection, [entity]) == []

    def test_unrelated_email_domain_does_not_match(self):
        detection = _make_detection(
            type=DetectionType.EMAIL, value_masked="j***@unrelated.example"
        )
        entity = _make_entity(
            selectors=[
                EntitySelector(type=SelectorType.EMAIL_DOMAIN, value="operateur.sn")
            ]
        )
        assert matching_entities(detection, [entity]) == []


class TestUnsupportedTypes:
    def test_types_without_a_selector_equivalent_never_match(self):
        # CARD/IBAN/PHONE/... n'ont pas de selecteur correspondant dans ce
        # perimetre (voir docstring du module) -- jamais de faux match.
        detection = _make_detection(
            type=DetectionType.CARD, value_masked="4***-****-****-1234"
        )
        entity = _make_entity()
        assert matching_entities(detection, [entity]) == []

    def test_keyword_selector_never_matches_anything_yet(self):
        detection = _make_detection(value_masked="operateur.sn")
        entity = _make_entity(
            selectors=[EntitySelector(type=SelectorType.KEYWORD, value="acme")]
        )
        assert matching_entities(detection, [entity]) == []


def _kw(*mots):
    return _make_entity(
        selectors=[EntitySelector(type=SelectorType.KEYWORD, value=m) for m in mots]
    )


def _org(valeur):
    return _make_detection(type=DetectionType.ORGANIZATION, value_masked=valeur)


class TestRattachementParRaisonSociale:
    """Selecteur `keyword` face aux detections `organization`.

    ⚠️ Repond aux sites de fuite qui nomment leurs victimes par leur RAISON
    SOCIALE sans jamais citer de domaine (SARCOMA, METAENCRYPTER, laisses
    inactifs faute de ce rattachement). Rendement mesure le 2026-09-04 : UNE
    entite surveillee sur 42 -- la brique complete une watchlist renseignee,
    elle ne la remplace pas.
    """

    def test_forme_juridique_ignoree(self):
        """« Propane Exemple Inc. » et « Propane Exemple » designent la meme
        organisation : un site de fuite n'ecrit pas la raison sociale comme le
        registre du commerce."""
        assert matching_entities(_org("Propane Exemple Inc."), [_kw("Propane Exemple")])

    def test_casse_accents_et_ponctuation_ignores(self):
        entite = _kw("Societe Generale")
        assert matching_entities(_org("SOCIÉTÉ-GÉNÉRALE, S.A."), [entite])

    def test_inclusion_refusee(self):
        """⚠️ EGALITE, jamais inclusion -- meme doctrine que les domaines
        (CONTRIBUTING.md §8). Surveiller « Acme » ne doit rattacher ni « Acme
        County Sheriff » ni « Bank of Acme » : un nom d'organisation n'a pas
        de structure en labels pour borner les faux positifs."""
        entite = _kw("Acme")
        assert matching_entities(_org("Acme County Sheriff"), [entite]) == []
        assert matching_entities(_org("Bank of Acme"), [entite]) == []

    def test_selecteur_trop_court_ne_matche_rien(self):
        assert matching_entities(_org("AB"), [_kw("AB")]) == []

    def test_detection_organization_portant_un_domaine_est_ignoree(self):
        """⚠️ 873 des 2414 detections `organization` sont en fait des DOMAINES
        (mesure du 2026-09-04) et sont deja couvertes par le rattachement par
        domaine : les traiter ici produirait un doublon."""
        entite = _kw("hccd construction")
        assert matching_entities(_org("construction-exemple.com"), [entite]) == []

    def test_entite_inactive_jamais_rattachee(self):
        entite = _kw("Propane Exemple")
        entite = entite.model_copy(update={"active": False})
        assert matching_entities(_org("Propane Exemple"), [entite]) == []

    def test_un_domaine_ne_matche_pas_un_selecteur_mot_cle(self):
        """Les deux familles restent etanches : un mot-cle ne rattache pas un
        domaine, et reciproquement."""
        assert (
            matching_entities(
                _make_detection(value_masked="operateur.sn"), [_kw("operateur sn")]
            )
            == []
        )


class TestTypesChargesSelonLesSelecteurs:
    """⚠️ `organization` ne doit consommer le plafond que s'il peut servir.

    L'inclure inconditionnellement chargerait 2414 lignes de plus -- le
    mecanisme meme qui evinçait des detections utiles le 2026-09-01 -- pour
    zero alerte supplementaire : les 24 organisations concernees sont deja
    alertees par leur detection `domain` (verifie en base, 0 valeur inedite).
    """

    def test_sans_selecteur_keyword_le_cout_est_nul(self):
        entite = _make_entity()  # selecteur domain uniquement
        assert "organization" not in matchable_detection_types([entite])

    def test_un_selecteur_keyword_suffit_a_l_activer(self):
        assert "organization" in matchable_detection_types([_kw("Delta Fine Finishes")])

    def test_selecteur_keyword_d_une_entite_INACTIVE_ne_compte_pas(self):
        entite = _kw("Delta Fine Finishes").model_copy(update={"active": False})
        assert "organization" not in matchable_detection_types([entite])

    def test_domain_et_email_toujours_presents(self):
        for types in (
            matchable_detection_types([]),
            matchable_detection_types([_kw("Acme Corp")]),
        ):
            assert "domain" in types and "email" in types


class TestExclusionParVictimeEtNonParDetection:
    """⚠️ FAUX POSITIF REEL corrige le 2026-09-04.

    L'alerte regionale « Afrique -- victime NON DECLAREE » portait 21
    detections, **toutes** des organisations surveillees (`distribution-exemple.co.za`,
    `telecom-exemple.ma`, `egov-exemple.sc`, `institution-exemple.sn`...). Chacune etait deja alertee
    nominativement via sa detection `domain`, et re-signalee comme « non
    declaree » via sa detection `organization` -- que `matching_entities` ne
    sait pas rattacher faute de selecteur `keyword`.

    L'alerte n'etait pas seulement redondante : elle **affirmait le contraire
    de la verite**. L'exclusion doit donc porter sur la VICTIME, pas sur
    l'objet detection qui la porte.
    """

    def test_la_valeur_est_reconnue_quel_que_soit_le_type_qui_la_porte(self):
        entite = _make_entity()  # selecteur domain = operateur.sn
        # Aucune detection ici : on interroge la valeur nue.
        assert value_matches_watched_entity("operateur.sn", [entite])
        assert value_matches_watched_entity("mail.operateur.sn", [entite])

    def test_le_prefixe_www_ne_fait_pas_echouer_l_exclusion(self):
        """Les sites de fuite publient `www.partenaire-exemple.co.za`, la watchlist
        declare `partenaire-exemple.co.za`."""
        entite = _make_entity(
            selectors=[
                EntitySelector(
                    type=SelectorType.DOMAIN, value="partenaire-exemple.co.za"
                )
            ]
        )
        assert value_matches_watched_entity("www.partenaire-exemple.co.za", [entite])

    def test_toujours_par_labels_jamais_par_sous_chaine(self):
        entite = _make_entity()
        assert not value_matches_watched_entity("not-operateur.sn", [entite])
        assert not value_matches_watched_entity("operateur.sn.evil.com", [entite])

    def test_une_victime_reellement_non_declaree_reste_signalable(self):
        """Garde-fou : l'exclusion ne doit pas tout avaler. C'est la raison
        d'etre de l'alerte regionale -- `suivi-flotte.co.za` et
        `mutuelle-exemple.co.zw` n'etaient signalees par rien d'autre."""
        entite = _make_entity()
        assert not value_matches_watched_entity("suivi-flotte.co.za", [entite])

    def test_entite_inactive_n_exclut_rien(self):
        entite = _make_entity().model_copy(update={"active": False})
        assert not value_matches_watched_entity("operateur.sn", [entite])

    def test_valeur_vide_n_exclut_rien(self):
        assert not value_matches_watched_entity("", [_make_entity()])

    def test_un_email_masque_est_reconnu_par_son_domaine(self):
        """⚠️ Second correctif du 2026-09-04. Le premier ne traitait que les
        domaines nus : la passe regionale re-signalait « non declarees » des
        victimes surveillees dont elle avait ramasse une ADRESSE
        (« o***@negoce-exemple.co.za ») plutot que le domaine."""
        entite = _make_entity(
            selectors=[
                EntitySelector(type=SelectorType.DOMAIN, value="negoce-exemple.co.za")
            ]
        )
        assert value_matches_watched_entity("o***@negoce-exemple.co.za", [entite])

    def test_un_email_d_un_autre_domaine_n_est_pas_exclu(self):
        entite = _make_entity()
        assert not value_matches_watched_entity("a***@autre-societe.co.za", [entite])


class TestGroupeEtFiliales:
    """D2 (2026-10-05) : la filiale touchée est alertée, pas son groupe."""

    def _groupe_et_filiale(self):
        groupe = _make_entity(
            name="Groupe",
            selectors=[EntitySelector(type=SelectorType.DOMAIN, value="groupe.com")],
        )
        filiale = _make_entity(
            name="Filiale CI",
            parent_id=groupe.id,
            selectors=[EntitySelector(type=SelectorType.DOMAIN, value="filiale.ci")],
        )
        return groupe, filiale

    def test_domaine_de_la_filiale_alerte_la_filiale(self):
        groupe, filiale = self._groupe_et_filiale()
        d = _make_detection(value_masked="mail.filiale.ci")
        assert most_specific(matching_entities(d, [groupe, filiale])) == [filiale]

    def test_domaine_du_groupe_alerte_le_groupe(self):
        groupe, filiale = self._groupe_et_filiale()
        d = _make_detection(value_masked="groupe.com")
        assert most_specific(matching_entities(d, [groupe, filiale])) == [groupe]

    def test_domaine_declare_par_les_deux_alerte_la_filiale_seule(self):
        groupe, filiale = self._groupe_et_filiale()
        filiale.selectors.append(
            EntitySelector(type=SelectorType.DOMAIN, value="groupe.com")
        )
        d = _make_detection(value_masked="groupe.com")
        assert most_specific(matching_entities(d, [groupe, filiale])) == [filiale]

    def test_deux_organisations_sans_lien_restent_toutes_deux(self):
        a = _make_entity(name="A")
        b = _make_entity(name="B")
        d = _make_detection(value_masked="operateur.sn")
        assert most_specific(matching_entities(d, [a, b])) == [a, b]
