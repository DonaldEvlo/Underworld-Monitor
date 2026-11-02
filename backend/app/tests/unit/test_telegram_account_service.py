"""Connexion du compte Telegram par QR code -- client simule, aucun reseau."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError

from app.pipeline.collect.telegram import mtproto_client
from app.services import telegram_account_service as svc

MOT_DE_PASSE = "motdepasse-secret-2fa"


@pytest.fixture(autouse=True)
def _config(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(mtproto_client.settings, "TELEGRAM_API_ID", "123")
    monkeypatch.setattr(mtproto_client.settings, "TELEGRAM_API_HASH", "h" * 32)
    monkeypatch.setattr(
        mtproto_client.settings, "TELEGRAM_SESSION_PATH", str(tmp_path / "collector")
    )
    monkeypatch.setattr(svc, "_POLL_SECONDS", 0.01)
    monkeypatch.setattr(svc, "_courant", None)


class FakeQR:
    def __init__(self, issues: list[Any]) -> None:
        # Chaque element : "ok", une exception a lever, ou "jamais".
        self._issues = issues
        self.recreations = 0
        self.url = "tg://login?token=AAA"
        self.expires = datetime.now(timezone.utc) + timedelta(seconds=30)

    async def wait(self, timeout: float | None = None) -> None:
        issue = self._issues.pop(0)
        if issue == "jamais":
            await asyncio.sleep(3600)
        if isinstance(issue, BaseException):
            raise issue

    async def recreate(self) -> None:
        self.recreations += 1
        self.url = f"tg://login?token=R{self.recreations}"


class FakeClient:
    def __init__(self, qr: FakeQR, deja: bool = False) -> None:
        self.qr = qr
        self.autorise = deja
        self.qr_demande = False
        self.mots_recus: list[str] = []
        self.deconnecte = False

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        self.deconnecte = True

    async def is_user_authorized(self) -> bool:
        return self.autorise

    async def qr_login(self) -> FakeQR:
        self.qr_demande = True
        return self.qr

    async def sign_in(self, password: str) -> None:
        self.mots_recus.append(password)
        if password != MOT_DE_PASSE:
            raise PasswordHashInvalidError(request=None)
        self.autorise = True


def _job(client: FakeClient, apres_scan: bool = True) -> svc.LoginJob:
    """`apres_scan` : le scan reussi rend la session autorisee."""
    if apres_scan:
        attente_originale = client.qr.wait

        async def wait(timeout: float | None = None) -> None:
            await attente_originale(timeout)
            client.autorise = True

        client.qr.wait = wait  # type: ignore[method-assign]
    return svc.LoginJob(
        sans_tor=False,
        client_factory=lambda sans_tor: client,
        svg=lambda url: f"<svg>{url}</svg>",
    )


def _attendre_phase(job: svc.LoginJob, phase: str, delai: float = 3.0) -> None:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if job.snapshot.phase == phase:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"phase {phase!r} jamais atteinte (actuelle : {job.snapshot.phase})"
    )


class TestConnexionQR:
    def test_scan_reussi(self) -> None:
        client = FakeClient(FakeQR(["ok"]))
        job = _job(client)
        job.run()
        assert job.snapshot.phase == "connected"
        assert client.deconnecte

    def test_le_QR_disparait_une_fois_termine(self) -> None:
        """Un QR encore affiche apres coup pourrait etre scanne par un tiers."""
        job = _job(FakeClient(FakeQR(["ok"])))
        job.run()
        assert job.snapshot.qr_svg is None and job.snapshot.qr_expires_at is None

    def test_QR_expire_puis_renouvele(self) -> None:
        qr = FakeQR([asyncio.TimeoutError(), "ok"])
        job = _job(FakeClient(qr))
        job.run()
        assert qr.recreations == 1
        assert job.snapshot.phase == "connected"

    def test_session_deja_connectee_pas_de_QR(self) -> None:
        client = FakeClient(FakeQR([]), deja=True)
        job = _job(client, apres_scan=False)
        job.run()
        assert job.snapshot.phase == "connected" and client.qr_demande is False

    def test_abandon_apres_le_delai_global(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(svc, "LOGIN_TIMEOUT", timedelta(seconds=-1))
        job = _job(FakeClient(FakeQR([asyncio.TimeoutError()])), apres_scan=False)
        job.run()
        assert job.snapshot.phase == "expired"

    def test_annulation_pendant_l_attente_du_scan(self) -> None:
        job = _job(FakeClient(FakeQR(["jamais"])), apres_scan=False)
        fil = threading.Thread(target=job.run)
        fil.start()
        _attendre_phase(job, "waiting_scan")
        assert job.snapshot.qr_svg == "<svg>tg://login?token=AAA</svg>"
        job.cancel()
        fil.join(3)
        assert job.snapshot.phase == "cancelled"

    def test_session_occupee(self) -> None:
        job = _job(FakeClient(FakeQR(["ok"])))
        with mtproto_client.session_lock():
            fil = threading.Thread(target=job.run)
            fil.start()
            fil.join(3)
        assert job.snapshot.phase == "error"
        assert "occupée" in (job.snapshot.message or "")


class TestVerificationEnDeuxEtapes:
    def _lancer(self) -> tuple[svc.LoginJob, FakeClient, threading.Thread]:
        client = FakeClient(FakeQR([SessionPasswordNeededError(request=None)]))
        job = _job(client, apres_scan=False)
        fil = threading.Thread(target=job.run)
        fil.start()
        _attendre_phase(job, "password_needed")
        return job, client, fil

    def test_mot_de_passe_correct(self) -> None:
        job, client, fil = self._lancer()
        job.submit_password(MOT_DE_PASSE)
        fil.join(3)
        assert job.snapshot.phase == "connected"
        assert client.mots_recus == [MOT_DE_PASSE]

    def test_mot_de_passe_incorrect_puis_correct(self) -> None:
        job, _, fil = self._lancer()
        job.submit_password("faux")
        fin = time.monotonic() + 3
        while job.snapshot.password_attempts_left != 2 and time.monotonic() < fin:
            time.sleep(0.01)
        assert job.snapshot.message == "Mot de passe incorrect."
        job.submit_password(MOT_DE_PASSE)
        fil.join(3)
        assert job.snapshot.phase == "connected"

    def test_trop_d_essais(self) -> None:
        job, _, fil = self._lancer()
        for _ in range(svc.MAX_PASSWORD_ATTEMPTS):
            job.submit_password("faux")
        fil.join(3)
        assert job.snapshot.phase == "error"

    def test_le_mot_de_passe_n_apparait_jamais_dans_l_etat(self) -> None:
        job, _, fil = self._lancer()
        job.submit_password(MOT_DE_PASSE)
        fil.join(3)
        assert MOT_DE_PASSE not in repr(job.snapshot)

    def test_annulation_pendant_l_attente_du_mot_de_passe(self) -> None:
        job, _, fil = self._lancer()
        job.cancel()
        fil.join(3)
        assert job.snapshot.phase == "cancelled"


class TestServiceGlobal:
    def test_une_seule_connexion_a_la_fois(self) -> None:
        client = FakeClient(FakeQR(["ok"]))
        premier = svc.start_qr_login(
            client_factory=lambda s: client, start_thread=False
        )
        assert premier.phase == "starting"
        with svc._courant_lock:
            job_1 = svc._courant
        svc.start_qr_login(client_factory=lambda s: client, start_thread=False)
        with svc._courant_lock:
            assert svc._courant is job_1

    def test_non_configure_leve_avant_tout_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mtproto_client.settings, "TELEGRAM_API_ID", "")
        with pytest.raises(mtproto_client.TelegramNotConfigured):
            svc.start_qr_login(start_thread=False)
        assert svc._courant is None

    def test_mot_de_passe_sans_connexion_en_attente(self) -> None:
        with pytest.raises(RuntimeError):
            svc.submit_password("x")

    def test_etat_sans_verification_reseau(self) -> None:
        etat = svc.account_status(check=False)
        assert etat.api_configured is True
        assert etat.connected is False
        assert etat.authorized is None  # pas verifie != non connecte
        assert etat.login.phase == "idle"


class TestTemoinDeConnexion:
    """Le fichier de session ne prouve rien : seul le temoin, pose sur une
    connexion REUSSIE, fait basculer la collecte sur le Client API."""

    def test_tentative_ratee_ne_connecte_pas(self) -> None:
        job = _job(FakeClient(FakeQR([asyncio.TimeoutError()])), apres_scan=False)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(svc, "LOGIN_TIMEOUT", timedelta(seconds=-1))
            job.run()
        open(mtproto_client.session_file(), "w").close()  # comme Telethon
        assert svc.account_status().connected is False
        assert mtproto_client.is_configured() is False

    def test_connexion_reussie_pose_le_temoin(self) -> None:
        open(mtproto_client.session_file(), "w").close()
        _job(FakeClient(FakeQR(["ok"]))).run()
        assert svc.account_status().connected is True
        assert mtproto_client.is_configured() is True

    def test_session_revoquee_detectee_a_la_verification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        open(mtproto_client.session_file(), "w").close()
        mtproto_client.mark_authorized(True)

        async def revoquee() -> bool:
            return False

        monkeypatch.setattr(svc, "_est_autorise", revoquee)
        etat = svc.account_status(check=True)
        assert etat.authorized is False
        assert etat.connected is False
        assert mtproto_client.is_configured() is False

    def test_deconnexion_retire_le_temoin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        open(mtproto_client.session_file(), "w").close()
        mtproto_client.mark_authorized(True)

        async def rien() -> None:
            return None

        monkeypatch.setattr(svc, "_deconnecter", rien)
        svc.logout()
        assert svc.account_status().connected is False
        assert not os.path.exists(mtproto_client.session_file())

    def test_QR_en_svg(self) -> None:
        rendu = svc.qr_svg("tg://login?token=AAA")
        assert rendu.lstrip().startswith("<?xml") or "<svg" in rendu

    def test_la_connexion_ecoute_les_mises_a_jour(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sans `receive_updates=True`, le scan n'aboutit jamais."""
        vu: dict[str, Any] = {}
        monkeypatch.setattr(
            svc,
            "build_client",
            lambda receive_updates=False: vu.setdefault("r", receive_updates),
        )
        svc.build_login_client(sans_tor=False)
        assert vu["r"] is True
