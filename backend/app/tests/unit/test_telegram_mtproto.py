"""Collecte Telegram par le Client API (MTProto) -- sans reseau ni Telethon.

Les messages Telethon sont remplaces par des doublures `SimpleNamespace` :
le module de conversion ne lit que des attributs.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.contracts.source import SourceContract, SourceType
from app.pipeline.collect.telegram import mtproto_client
from app.pipeline.collect.telegram.mtproto import (
    AttachedFile,
    MtprotoMessage,
    document_content,
    document_meta,
    document_title,
    human_size,
    message_from_telethon,
)
from app.pipeline.collect.telegram.mtproto_adapter import MtprotoChannelCollector
from app.pipeline.collect.telegram.mtproto_client import (
    TelegramNotAuthorized,
    TelegramNotConfigured,
)

DATE = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)


def _msg(**kw):
    base = {
        "id": 42,
        "message": "Operateur SN database leak 4.2 GB",
        "date": DATE,
        "post": True,
        "post_author": None,
        "views": 1500,
        "forwards": 3,
        "fwd_from": None,
        "file": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _source(url: str = "https://t.me/dropleak") -> SourceContract:
    return SourceContract(
        id=uuid.uuid4(),
        name="canal test",
        url=url,
        type=SourceType.TELEGRAM,
        created_at=DATE,
    )


class TestConversion:
    def test_message_de_canal(self) -> None:
        m = message_from_telethon(_msg(post_author="admin"), "dropleak")
        assert m is not None
        assert m.url == "https://t.me/dropleak/42"
        assert m.published_at == DATE
        assert m.author == "admin"

    def test_message_de_service_ignore(self) -> None:
        assert message_from_telethon(_msg(message="", file=None), "c") is None
        assert message_from_telethon(_msg(id=None), "c") is None

    def test_auteur_d_un_GROUPE_jamais_repris(self) -> None:
        """Regle 1 : dans un groupe, l'auteur est une personne."""
        brut = _msg(
            post=False,
            post_author="Jean Dupont",
            sender_id=123456,
            sender=SimpleNamespace(username="jdupont", first_name="Jean"),
        )
        m = message_from_telethon(brut, "groupe")
        assert m is not None and m.author is None
        meta = document_meta(m)
        texte = repr(meta) + document_content(m)
        assert "123456" not in texte and "jdupont" not in texte and "Jean" not in texte

    def test_transfert_depuis_un_canal_garde_depuis_une_personne_non(self) -> None:
        canal = _msg(fwd_from=SimpleNamespace(from_id=SimpleNamespace(channel_id=777)))
        personne = _msg(fwd_from=SimpleNamespace(from_id=SimpleNamespace(user_id=999)))
        m1 = message_from_telethon(canal, "c")
        m2 = message_from_telethon(personne, "c")
        assert m1 is not None and m1.forwarded_from_channel_id == 777
        assert m2 is not None and m2.forwarded_from_channel_id is None
        assert "999" not in repr(document_meta(m2))

    def test_fichier_joint_metadonnees(self) -> None:
        brut = _msg(
            message="",
            file=SimpleNamespace(
                name="acme_sn_clients.zip",
                size=4_509_715_660,
                mime_type="application/zip",
            ),
        )
        m = message_from_telethon(brut, "c")
        assert m is not None
        assert m.files == (
            AttachedFile("acme_sn_clients.zip", 4_509_715_660, "application/zip"),
        )
        assert "acme_sn_clients.zip (4.2 GB, application/zip)" in document_content(m)
        assert document_title(m) == "acme_sn_clients.zip"

    def test_photo_seule_n_est_pas_un_fichier(self) -> None:
        brut = _msg(
            file=SimpleNamespace(name=None, size=50_000, mime_type="image/jpeg")
        )
        m = message_from_telethon(brut, "c")
        assert m is not None and m.files == ()


class TestCompteursHorsContenu:
    def test_vues_et_transferts_dans_meta_pas_dans_le_contenu(self) -> None:
        a = message_from_telethon(_msg(views=10, forwards=1), "c")
        b = message_from_telethon(_msg(views=99_999, forwards=500), "c")
        assert a is not None and b is not None
        assert document_content(a) == document_content(b)
        assert document_meta(b)["views"] == 99_999

    def test_meme_hash_quand_seules_les_vues_changent(self) -> None:
        src = _source()
        docs = []
        for vues in (10, 99_999):
            m = message_from_telethon(_msg(views=vues), "dropleak")
            assert m is not None
            docs += MtprotoChannelCollector(
                history_reader=lambda c, n, m=m: [m]
            ).collect(src)
        assert docs[0].content_hash == docs[1].content_hash


class TestTaille:
    @pytest.mark.parametrize(
        ("octets", "attendu"),
        [
            (None, None),
            (-1, None),
            (512, "512 B"),
            (2048, "2.0 KB"),
            (5 * 1024**3, "5.0 GB"),
        ],
    )
    def test_human_size(self, octets: int | None, attendu: str | None) -> None:
        assert human_size(octets) == attendu


class TestCollecteur:
    def test_un_document_par_message(self) -> None:
        msgs = [
            MtprotoMessage(
                channel="dropleak", message_id=i, text=f"annonce {i}", published_at=DATE
            )
            for i in (1, 2)
        ]
        docs = MtprotoChannelCollector(history_reader=lambda c, n: msgs).collect(
            _source()
        )
        assert [d.url for d in docs] == [
            "https://t.me/dropleak/1",
            "https://t.me/dropleak/2",
        ]
        assert all(d.collector == "telegram" for d in docs)
        assert (
            docs[0].source_meta is not None and docs[0].source_meta["via"] == "mtproto"
        )

    def test_borne_transmise_au_lecteur(self) -> None:
        vu: list[tuple[str, int]] = []

        def lecteur(canal: str, n: int) -> list[MtprotoMessage]:
            vu.append((canal, n))
            return []

        MtprotoChannelCollector(history_reader=lecteur, max_messages=30).collect(
            _source()
        )
        assert vu == [("dropleak", 30)]

    def test_lien_d_invitation_jamais_lu(self) -> None:
        appels: list[str] = []
        c = MtprotoChannelCollector(
            history_reader=lambda ch, n: appels.append(ch) or []
        )
        assert c.collect(_source("https://t.me/+AbCdEf123456")) == []
        assert appels == []

    @pytest.mark.parametrize(
        "erreur", [TelegramNotConfigured("x"), TelegramNotAuthorized("x")]
    )
    def test_repli_sur_l_apercu_web(self, erreur: Exception) -> None:
        class Repli:
            appele = False

            def collect(self, source):  # noqa: ANN001, ANN201
                Repli.appele = True
                return ["apercu"]

        def lecteur(c: str, n: int) -> list[MtprotoMessage]:
            raise erreur

        docs = MtprotoChannelCollector(history_reader=lecteur, fallback=Repli()).collect(_source())  # type: ignore[arg-type]
        assert Repli.appele and docs == ["apercu"]

    def test_autre_erreur_abandonne_le_canal_sans_repli(self) -> None:
        def lecteur(c: str, n: int) -> list[MtprotoMessage]:
            raise ValueError("canal prive")

        class Repli:
            def collect(self, source):  # noqa: ANN001, ANN201
                raise AssertionError("pas de repli sur une erreur de lecture")

        assert MtprotoChannelCollector(history_reader=lecteur, fallback=Repli()).collect(_source()) == []  # type: ignore[arg-type]


class TestConfiguration:
    def test_identifiants_absents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mtproto_client.settings, "TELEGRAM_API_ID", "")
        monkeypatch.setattr(mtproto_client.settings, "TELEGRAM_API_HASH", "")
        with pytest.raises(TelegramNotConfigured):
            mtproto_client.api_credentials()
        assert mtproto_client.is_configured() is False

    def test_api_id_non_entier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mtproto_client.settings, "TELEGRAM_API_ID", "abc")
        monkeypatch.setattr(mtproto_client.settings, "TELEGRAM_API_HASH", "h")
        with pytest.raises(TelegramNotConfigured):
            mtproto_client.api_credentials()

    def test_session_absente_non_configure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:  # noqa: ANN001
        monkeypatch.setattr(mtproto_client.settings, "TELEGRAM_API_ID", "123")
        monkeypatch.setattr(mtproto_client.settings, "TELEGRAM_API_HASH", "h")
        monkeypatch.setattr(
            mtproto_client.settings, "TELEGRAM_SESSION_PATH", str(tmp_path / "s")
        )
        assert mtproto_client.is_configured() is False
        with pytest.raises(TelegramNotConfigured):
            mtproto_client.read_channel_history("dropleak")
        # ⚠️ Le fichier de session SEUL ne suffit pas : Telethon le cree des
        # la premiere tentative, meme ratee (constate le 2026-09-26).
        (tmp_path / "s.session").write_text("")
        assert mtproto_client.is_configured() is False
        with pytest.raises(TelegramNotConfigured):
            mtproto_client.read_channel_history("dropleak")
        mtproto_client.mark_authorized(True)
        assert mtproto_client.is_configured() is True
        mtproto_client.mark_authorized(False)
        assert mtproto_client.is_configured() is False


class TestTorObligatoire:
    def test_proxy_vers_le_conteneur_tor(self) -> None:
        proxy = mtproto_client.telethon_proxy()
        assert proxy["proxy_type"] == "socks5"
        assert proxy["addr"] == mtproto_client.settings.TOR_SOCKS_HOST
        assert proxy["rdns"] is True

    def test_python_socks_absent_leve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sans python-socks, Telethon se connecterait en direct."""
        monkeypatch.setattr(
            mtproto_client.importlib.util, "find_spec", lambda nom: None
        )
        with pytest.raises(RuntimeError, match="SANS Tor"):
            mtproto_client.telethon_proxy()


class TestLectureSeule:
    """Le client ne doit appeler que des methodes de LECTURE. Relit le code
    source : un ajout (rejoindre, telecharger, lister des membres) fait
    echouer ce test au lieu de passer inapercu."""

    INTERDITS = (
        "download",
        "JoinChannel",
        "ImportChatInvite",
        "join",
        "send_message",
        "send_file",
        "get_participants",
        "iter_participants",
        "forward_messages",
    )

    def test_aucune_methode_d_ecriture_ni_de_telechargement(self) -> None:
        source = inspect.getsource(mtproto_client)
        code = "\n".join(
            ligne for ligne in source.splitlines() if not ligne.strip().startswith("#")
        )
        # La docstring du module nomme ces gestes pour les INTERDIRE : on ne
        # controle que ce qui suit la docstring.
        code = code.split('"""', 2)[2]
        # Temoin : le code examine est bien celui qui LIT. Sans lui, un
        # decoupage rate ferait passer ce test a vide.
        assert "iter_messages" in code and "get_input_entity" in code
        for mot in self.INTERDITS:
            assert mot not in code, mot
