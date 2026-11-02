"""Tests de pipeline/classify/llm_triage.py.

Module pur : construction du prompt et analyse de la reponse, sans reseau.

Ces tests portent surtout sur les GARDE-FOUS, parce que chacun repare une
defaillance observee sur le modele reel, pas une crainte theorique.
"""

from app.pipeline.classify.llm_triage import (
    DEFAULT_BATCH_SIZE,
    TriageItem,
    build_triage_prompt,
    parse_triage_response,
)


def _item(titre: str, *, victimes: bool = True, key: str | None = None) -> TriageItem:
    return TriageItem(
        key=key or titre,
        title=titre,
        content="",
        source_publishes_victims=victimes,
    )


class TestPromptTellsTheSourceNature:
    """Le type de source est decisif et ne se devine pas du texte : sur un site
    de fuite, un titre reduit a une raison sociale EST une victime ; le meme
    titre sur un forum ne veut rien dire."""

    def test_leak_site_is_announced_as_such(self):
        prompt = build_triage_prompt([_item("Ermat Grup", victimes=True)])
        assert "site de fuite" in prompt
        assert "Ermat Grup" in prompt

    def test_forum_is_announced_as_such(self):
        prompt = build_triage_prompt([_item("Vente de comptes", victimes=False)])
        assert "forum generaliste" in prompt


class TestTitleEchoCatchesMisalignment:
    """⚠️ Le garde-fou principal. A 10 documents par lot, le modele DECALAIT ses
    numeros : `exemplic` recevait la justification de « Exemplo Corporation »,
    `exempledhall` celle de « kioti ». Des verdicts attribues aux mauvais
    documents, sans que rien ne le signale.

    L'echo du titre rend le decalage detectable."""

    def test_a_matching_echo_is_accepted(self):
        items = [_item("Exemple Chemicals India")]
        verdicts, rejets = parse_triage_response(
            "1|leak|Exemple Chemicals India|Victime annoncee.", items
        )
        assert verdicts["Exemple Chemicals India"].verdict == "leak"
        assert rejets == 0

    def test_a_mismatched_echo_is_rejected_not_guessed(self):
        items = [_item("Exemple Chemicals India")]
        verdicts, rejets = parse_triage_response(
            "1|leak|Exemplo Corporation|Victime annoncee.", items
        )
        assert verdicts == {}
        assert rejets == 1

    def test_punctuation_and_case_do_not_count_as_a_mismatch(self):
        """Le modele recopie rarement au caractere pres."""
        items = [_item("OFFICINE FRATELLI EXEMPLE snc")]
        verdicts, _ = parse_triage_response("1|leak|officine fratelli|Victime.", items)
        assert verdicts["OFFICINE FRATELLI EXEMPLE snc"].verdict == "leak"


class TestNoiseIsInadmissibleOnAVictimPublishingSource:
    """⚠️ Mesure du 2026-09-03 : **6 documents sur 32** issus de QILIN et ORION
    etaient marques `noise` par le modele -- `Maison-Exemple`, `Traceur-Exemple`,
    `prix-exemple`, `exemplic`, de vraies victimes ecartees parce que leur raison
    sociale « ressemble a un service ». 19 % de faux negatifs sur le cas
    d'usage principal.

    Meme regle que le classifieur : sur un site de fuite, un document EST une
    victime, et l'absence de vocabulaire de fuite n'a aucune valeur
    informative."""

    def test_noise_on_a_leak_site_becomes_uncertain(self):
        items = [_item("prix-exemple", victimes=True)]
        verdicts, _ = parse_triage_response(
            "1|noise|prix-exemple|Vente de comptes ou logiciels.", items
        )
        assert verdicts["prix-exemple"].verdict == "uncertain"
        assert "source publie des victimes" in verdicts["prix-exemple"].reason

    def test_noise_on_a_forum_is_kept(self):
        """La contrainte vise les sites de fuite, pas les forums -- ou `noise`
        est au contraire le verdict attendu."""
        items = [_item("X40 comptes premium", victimes=False)]
        verdicts, _ = parse_triage_response(
            "1|noise|X40 comptes premium|Vente de comptes.", items
        )
        assert verdicts["X40 comptes premium"].verdict == "noise"

    def test_leak_on_a_leak_site_is_untouched(self):
        items = [_item("Ermat Grup", victimes=True)]
        verdicts, _ = parse_triage_response("1|leak|Ermat Grup|Victime.", items)
        assert verdicts["Ermat Grup"].verdict == "leak"


class TestParsingToleratesTheModelsFormatDrift:
    """Le modele local est instable sur la FORME : numerotation en double,
    preambule, justification vide. Un ancrage strict en debut de ligne rejetait
    des reponses pourtant justes. La tolerance porte sur la forme ; la
    verification du titre, elle, ne cede rien."""

    def test_double_numbering_is_tolerated(self):
        items = [_item("Exemple Chemicals India")]
        verdicts, _ = parse_triage_response(
            "1. 1|leak|Exemple Chemicals India|Victime annoncee.", items
        )
        assert verdicts["Exemple Chemicals India"].verdict == "leak"

    def test_a_preamble_line_is_ignored(self):
        items = [_item("Ermat Grup")]
        verdicts, _ = parse_triage_response(
            "Here are the answers:\n\n1|leak|Ermat Grup|Victime.", items
        )
        assert verdicts["Ermat Grup"].verdict == "leak"

    def test_an_empty_justification_is_accepted(self):
        items = [_item("kioti")]
        verdicts, _ = parse_triage_response("1|leak|kioti||", items)
        assert verdicts["kioti"].verdict == "leak"
        assert verdicts["kioti"].reason == ""

    def test_an_unknown_verdict_is_not_invented(self):
        items = [_item("Ermat Grup")]
        verdicts, _ = parse_triage_response("1|peut-etre|Ermat Grup|Bof.", items)
        assert verdicts == {}

    def test_a_missing_answer_leaves_the_document_unclassified(self):
        """Le document reste `uncertain` cote regles et sera represente.
        Inventer un verdict serait indiscernable d'un vrai."""
        items = [_item("Ermat Grup"), _item("Traceur-Exemple")]
        verdicts, _ = parse_triage_response("1|leak|Ermat Grup|Victime.", items)
        assert set(verdicts) == {"Ermat Grup"}

    def test_batch_size_stays_small(self):
        """A 10 par lot le modele decalait ses numeros : la taille du lot est un
        garde-fou, pas un reglage de performance."""
        assert DEFAULT_BATCH_SIZE <= 5
