"""Export STIX 2.1 d'une alerte (pipeline/reporting/stix.py).

Le juge est le VALIDATEUR OFFICIEL de l'OASIS (`stix2-validator`) : un paquet
que nous croyons conforme ne l'est pas tant qu'il ne l'a pas passe. Les autres
tests verrouillent ce que la specification ne peut pas verifier pour nous :
la regle 2 (rien de prive, rien de .onion), le marquage TLP sur chaque objet,
la table Admiralty et la mise en garde sur le mode operatoire."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest

from app.pipeline.reporting.stix import (
    TLP_AMBER_STRICT_ID,
    StixAlertInput,
    StixGangProfile,
    StixTechnique,
    StixVictim,
    build_bundle,
)

CREE = datetime(2026, 9, 29, 22, 7, tzinfo=timezone.utc)
MAINTENANT = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
MISE_EN_GARDE = "Mode operatoire HABITUEL du groupe, pas le vecteur de cet incident."


def _entree(**champs) -> StixAlertInput:
    base = dict(
        alert_id="318198b1-8576-45c2-8c59-ac4fbb08045f",
        subject="Exemple Defence Force -- victime non declaree (Afrique)",
        created=CREE,
        modified=MAINTENANT,
        severity="critical",
        victims=(
            StixVictim(
                name="Exemple Defence Force",
                gang="ransomhouse",
                country="NA",
                sector="Government & Defense",
            ),
        ),
        credibility_level="claimed",
        credibility_evidence="victime annoncee, statut non expose",
        admiralty="F6",
        profiles=(
            StixGangProfile(
                gang="ransomhouse",
                techniques=(
                    StixTechnique(
                        "T1190",
                        "Exploit Public-Facing Application",
                        "Initial Access",
                        "https://attack.mitre.org/techniques/T1190/",
                    ),
                ),
                tools=("RClone", "File[.]io"),
                cves=("CVE-2023-3519",),
            ),
        ),
        evidence=(
            ("capture", "https://images.ransomware.live/victims/x.png"),
            ("fuite", "http://gangabcdefgh.onion/leak/ndf"),
            ("hostile", "javascript:alert(1)"),
        ),
        modus_operandi_caveat=MISE_EN_GARDE,
    )
    base.update(champs)
    return StixAlertInput(**base)


def _types(paquet: dict) -> dict[str, list[dict]]:
    par_type: dict[str, list[dict]] = {}
    for objet in paquet["objects"]:
        par_type.setdefault(objet["type"], []).append(objet)
    return par_type


class TestValidateurOfficiel:
    def test_le_paquet_est_conforme_stix_2_1(self):
        """0 erreur. Deux AVERTISSEMENTS de bonne pratique sont assumes, et
        seulement eux -- tout autre avertissement fait echouer le test :
        - {103} identifiants UUIDv5 et non v4 : DETERMINISTES par choix, pour
          que le destinataire dedoublonne (pratique d'OpenCTI pour ses
          identifiants standard) ;
        - {302} lien sans empreinte : la plateforme ne telecharge jamais la
          capture ni la page (regle 2), il n'y a donc rien a hacher."""
        validator = pytest.importorskip("stix2validator")
        resultat = validator.validate_instance(build_bundle(_entree()))
        assert resultat.is_valid, [str(e) for e in resultat.errors]
        trouves = [re.search(r"\{(\d+)\}", str(w)) for w in resultat.warnings]
        # Sans cette garde, une lecture ratee des codes rendrait l'ensemble
        # vide -- « inclus » dans les codes toleres : test vert, a vide.
        assert all(trouves), "avertissement sans code lisible"
        codes = {t.group(1) for t in trouves if t}
        assert codes <= {"103", "302"}, [str(w) for w in resultat.warnings]

    def test_alerte_minimale_conforme(self):
        """Victime de forum, sans gang ni profil ni preuve : toujours valide."""
        validator = pytest.importorskip("stix2validator")
        paquet = build_bundle(
            _entree(
                victims=(StixVictim(name="Organisation Exemple"),),
                profiles=(),
                evidence=(),
                admiralty=None,
                credibility_level=None,
            )
        )
        assert validator.validate_instance(paquet).is_valid


class TestRegle2:
    def test_aucun_onion_aucun_lien_hostile(self):
        texte = json.dumps(build_bundle(_entree()))
        assert ".onion" not in texte
        assert "javascript:" not in texte
        assert "images.ransomware.live" in texte

    def test_aucune_valeur_detectee(self):
        """Le constructeur ne recoit aucune detection : une adresse, meme
        masquee, ne peut donc pas sortir. Ce test garde la porte fermee."""
        assert "@" not in json.dumps(build_bundle(_entree()))


class TestMarquage:
    def test_tlp_amber_strict_sur_chaque_objet(self):
        paquet = build_bundle(_entree())
        (marquage,) = [
            o for o in paquet["objects"] if o["type"] == "marking-definition"
        ]
        assert marquage["id"] == TLP_AMBER_STRICT_ID
        assert marquage["name"] == "TLP:AMBER+STRICT"
        for objet in paquet["objects"]:
            if objet["type"] != "marking-definition":
                assert objet["object_marking_refs"] == [TLP_AMBER_STRICT_ID], objet[
                    "type"
                ]


class TestConfianceAdmiralty:
    """Table de l'annexe A de STIX 2.1, relue dans le texte integral le
    2026-09-30 (un premier resume avait INVENTE 95/75/50/25/15/0)."""

    @pytest.mark.parametrize(
        "note,attendu", [("B1", 90), ("B2", 70), ("C3", 50), ("D4", 30), ("E5", 10)]
    )
    def test_table_officielle(self, note, attendu):
        (rapport,) = _types(build_bundle(_entree(admiralty=note)))["report"]
        assert rapport["confidence"] == attendu

    def test_six_n_est_pas_zero(self):
        """« La verite ne peut etre jugee » -> propriete ABSENTE : 0 dirait
        « certainement faux »."""
        (rapport,) = _types(build_bundle(_entree(admiralty="F6")))["report"]
        assert "confidence" not in rapport
        assert "admiralty:F6" in rapport["labels"]


class TestContenu:
    def test_victime_gang_et_relation(self):
        types = _types(build_bundle(_entree()))
        (victime,) = [
            i for i in types["identity"] if i["identity_class"] == "organization"
        ]
        assert victime["sectors"] == ["government", "defense"]
        (gang,) = types["intrusion-set"]
        cibles = [
            r
            for r in types["relationship"]
            if r["relationship_type"] == "targets" and r["target_ref"] == victime["id"]
        ]
        assert [r["source_ref"] for r in cibles] == [gang["id"]]
        assert types["location"][0]["country"] == "NA"

    def test_secteur_sans_correspondance_absent(self):
        types = _types(
            build_bundle(
                _entree(victims=(StixVictim(name="X", sector="Professional Services"),))
            )
        )
        (victime,) = [
            i for i in types["identity"] if i["identity_class"] == "organization"
        ]
        assert "sectors" not in victime

    def test_mode_operatoire_porte_sa_mise_en_garde(self):
        types = _types(build_bundle(_entree()))
        (note,) = types["note"]
        assert note["content"] == MISE_EN_GARDE
        assert (
            types["attack-pattern"][0]["external_references"][0]["external_id"]
            == "T1190"
        )
        assert types["attack-pattern"][0]["kill_chain_phases"][0]["phase_name"] == (
            "initial-access"
        )
        assert {t["name"] for t in types["tool"]} == {"RClone", "File[.]io"}
        assert types["vulnerability"][0]["name"] == "CVE-2023-3519"
        usages = [r for r in types["relationship"] if r["relationship_type"] == "uses"]
        assert usages and all(r["description"] == MISE_EN_GARDE for r in usages)

    def test_identifiants_deterministes(self):
        """Deux exports identiques reutilisent les memes objets : le
        destinataire dedoublonne au lieu d'accumuler des copies."""
        a, b = build_bundle(_entree()), build_bundle(_entree())
        assert [o["id"] for o in a["objects"]] == [o["id"] for o in b["objects"]]
