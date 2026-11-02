"""Compte de lecture Telegram : etat, connexion par QR code, deconnexion.

Remplace, pour l'analyste, la commande `app.scripts.telegram_login` lancee
dans un terminal : la page « Compte Telegram » affiche le QR, l'administrateur
le scanne avec le telephone du compte dedie, et la session est enregistree.

⚠️ QR CODE, PAS CODE PAR MESSAGE. Une application tierce ne recoit son code
que dans l'application Telegram, et il n'arrive souvent jamais (constate le
2026-09-26, avec et sans Tor ; Telethon #4687, #4730). Le QR est la methode
officiellement ouverte aux applications tierces (core.telegram.org/api/auth).

⚠️ UNE CONNEXION VIT PLUSIEURS MINUTES (QR renouvele toutes les ~30 s, puis
eventuel mot de passe de verification en deux etapes). Elle tourne donc dans
un THREAD de l'API, et la page interroge son etat. Consequence assumee :
l'etat vit dans la memoire du processus -- l'API tourne en un seul processus
uvicorn (docker-compose.yml). Passer a plusieurs processus exigerait de
deplacer la connexion dans un worker dedie.

⚠️ SECRETS : ni le mot de passe, ni le jeton du QR, ni aucune identite du
compte (numero, nom, identifiant) ne sont journalises ni renvoyes en dehors de
ce qui est strictement necessaire (le QR a scanner, tant qu'il est valide).
Le mot de passe transite en memoire, du formulaire au thread, puis est oublie.

⚠️ `sans_tor` est l'EXCEPTION A LA REGLE 3 decidee pour le projet pour la
premiere connexion (2026-09-26). Elle ne concerne que ce module : la collecte
(`mtproto_client.build_client`) reste obligatoirement sous Tor.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from app.pipeline.collect.telegram.mtproto_client import (
    SessionBusy,
    TelegramNotConfigured,
    api_credentials,
    build_client,
    is_authorized_locally,
    mark_authorized,
    session_file,
    session_lock,
)

logger = logging.getLogger(__name__)

LoginPhase = Literal[
    "idle",
    "starting",
    "waiting_scan",
    "password_needed",
    "connected",
    "expired",
    "cancelled",
    "error",
]

# Au-dela, la connexion abandonne : un QR affiche indefiniment sur un ecran
# oublie serait une porte ouverte (quiconque le scanne connecte SON compte a
# notre session).
LOGIN_TIMEOUT = timedelta(minutes=5)
PASSWORD_TIMEOUT_SECONDS = 180
MAX_PASSWORD_ATTEMPTS = 3
_POLL_SECONDS = 0.5


@dataclass(frozen=True)
class LoginSnapshot:
    phase: LoginPhase = "idle"
    qr_svg: str | None = None
    qr_expires_at: datetime | None = None
    message: str | None = None
    via_tor: bool = True
    started_at: datetime | None = None
    password_attempts_left: int = MAX_PASSWORD_ATTEMPTS

    @property
    def active(self) -> bool:
        return self.phase in ("starting", "waiting_scan", "password_needed")


def build_login_client(sans_tor: bool) -> Any:
    """Client capable de recevoir `UpdateLoginToken` (indispensable au QR).

    Via Tor par defaut ; sans proxy uniquement sur demande explicite."""
    if not sans_tor:
        return build_client(receive_updates=True)
    from telethon import TelegramClient

    api_id, api_hash = api_credentials()
    os.makedirs(os.path.dirname(session_file()) or ".", exist_ok=True)
    return TelegramClient(session_file(), api_id, api_hash, receive_updates=True)


def qr_svg(url: str) -> str:
    """QR code en SVG, fond blanc inclus (lisible sur un theme sombre)."""
    import qrcode
    from qrcode.image.svg import SvgPathFillImage

    image = qrcode.make(url, image_factory=SvgPathFillImage, border=2)
    rendu = image.to_string()
    return rendu.decode("utf-8") if isinstance(rendu, bytes) else str(rendu)


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


class LoginJob:
    """Une tentative de connexion par QR. `run()` est synchrone et bloquant :
    il est lance dans un thread par `start_qr_login`, et directement par les
    tests (avec un client simule)."""

    def __init__(
        self,
        sans_tor: bool,
        client_factory: Callable[[bool], Any] = build_login_client,
        svg: Callable[[str], str] = qr_svg,
    ) -> None:
        self._client_factory = client_factory
        self._svg = svg
        self._sans_tor = sans_tor
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._passwords: queue.Queue[str] = queue.Queue()
        self._snapshot = LoginSnapshot(
            phase="starting", via_tor=not sans_tor, started_at=_maintenant()
        )

    # -- etat partage avec les requetes HTTP ---------------------------------

    @property
    def snapshot(self) -> LoginSnapshot:
        with self._lock:
            return self._snapshot

    def _set(self, **champs: Any) -> None:
        with self._lock:
            self._snapshot = replace(self._snapshot, **champs)

    def cancel(self) -> None:
        self._cancel.set()

    def submit_password(self, password: str) -> None:
        self._passwords.put(password)

    # -- deroulement ---------------------------------------------------------

    def run(self) -> None:
        try:
            with session_lock(blocking=False):
                asyncio.run(self._run())
        except SessionBusy:
            self._set(
                phase="error",
                message="Session occupée (collecte Telegram en cours) : réessayer "
                "dans une minute.",
            )
        except TelegramNotConfigured as exc:
            self._set(phase="error", message=str(exc))
        except Exception as exc:  # noqa: BLE001
            # Le type seul : un message d'erreur Telegram peut citer le numero.
            logger.warning("Telegram: connexion QR en echec (%s)", type(exc).__name__)
            self._set(
                phase="error", message=f"Échec de la connexion ({type(exc).__name__})"
            )
        finally:
            self._set(qr_svg=None, qr_expires_at=None)

    async def _run(self) -> None:
        client = self._client_factory(self._sans_tor)
        await client.connect()
        try:
            if await client.is_user_authorized():
                mark_authorized(True)
                self._set(phase="connected", message="Session déjà connectée.")
                return
            await self._qr(client)
        finally:
            await client.disconnect()

    async def _qr(self, client: Any) -> None:
        from telethon.errors import SessionPasswordNeededError

        limite = _maintenant() + LOGIN_TIMEOUT
        connexion = await client.qr_login()
        while True:
            self._set(
                phase="waiting_scan",
                qr_svg=self._svg(connexion.url),
                qr_expires_at=connexion.expires,
                message=None,
            )
            # ⚠️ `wait()` doit TOURNER pendant le scan (docstring Telethon) :
            # on ne le decoupe pas en tranches courtes, ou la notification
            # arrivee entre deux tranches serait perdue. Une tache unique par
            # QR, annulable.
            attente = asyncio.ensure_future(connexion.wait())
            try:
                while not attente.done():
                    if self._cancel.is_set():
                        attente.cancel()
                        with suppress(asyncio.CancelledError):
                            await attente
                        self._set(phase="cancelled", message="Connexion annulée.")
                        return
                    await asyncio.sleep(_POLL_SECONDS)
                attente.result()
                break
            except asyncio.TimeoutError:
                if _maintenant() >= limite:
                    self._set(
                        phase="expired",
                        message="Aucun scan en 5 minutes : relancer la connexion.",
                    )
                    return
                await connexion.recreate()
            except SessionPasswordNeededError:
                await self._mot_de_passe(client)
                break

        if self.snapshot.phase in ("cancelled", "expired", "error"):
            return
        if await client.is_user_authorized():
            mark_authorized(True)
            self._set(phase="connected", message="Session enregistrée.")
        else:
            self._set(phase="error", message="Connexion non aboutie.")

    async def _mot_de_passe(self, client: Any) -> None:
        from telethon.errors import PasswordHashInvalidError

        boucle = asyncio.get_running_loop()
        for restant in range(MAX_PASSWORD_ATTEMPTS, 0, -1):
            self._set(
                phase="password_needed",
                qr_svg=None,
                qr_expires_at=None,
                password_attempts_left=restant,
            )
            try:
                mot = await boucle.run_in_executor(None, self._attendre_mot_de_passe)
            except queue.Empty:
                self._set(phase="expired", message="Mot de passe non saisi à temps.")
                return
            if mot is None:
                self._set(phase="cancelled", message="Connexion annulée.")
                return
            try:
                await client.sign_in(password=mot)
                return
            except PasswordHashInvalidError:
                self._set(message="Mot de passe incorrect.")
            finally:
                del mot
        self._set(phase="error", message="Trop de mots de passe incorrects.")

    def _attendre_mot_de_passe(self) -> str | None:
        """Attend le mot de passe, en surveillant l'annulation."""
        echeance = _maintenant() + timedelta(seconds=PASSWORD_TIMEOUT_SECONDS)
        while _maintenant() < echeance:
            if self._cancel.is_set():
                return None
            try:
                return self._passwords.get(timeout=_POLL_SECONDS)
            except queue.Empty:
                continue
        raise queue.Empty


# -- API du service (une seule connexion a la fois) ----------------------------

_courant: LoginJob | None = None
_courant_lock = threading.Lock()


def current_login() -> LoginSnapshot:
    with _courant_lock:
        return _courant.snapshot if _courant is not None else LoginSnapshot()


def start_qr_login(
    sans_tor: bool = False,
    client_factory: Callable[[bool], Any] = build_login_client,
    start_thread: bool = True,
) -> LoginSnapshot:
    """Lance une connexion par QR, ou rend celle deja en cours : deux
    connexions simultanees se disputeraient la meme session."""
    global _courant
    api_credentials()  # leve TelegramNotConfigured AVANT de lancer un thread
    with _courant_lock:
        if _courant is not None and _courant.snapshot.active:
            return _courant.snapshot
        _courant = LoginJob(sans_tor=sans_tor, client_factory=client_factory)
        job = _courant
    if start_thread:
        threading.Thread(target=job.run, name="telegram-qr-login", daemon=True).start()
    return job.snapshot


def submit_password(password: str) -> LoginSnapshot:
    with _courant_lock:
        job = _courant
    if job is None or job.snapshot.phase != "password_needed":
        raise RuntimeError("aucune connexion n'attend de mot de passe")
    job.submit_password(password)
    return job.snapshot


def cancel_login() -> LoginSnapshot:
    with _courant_lock:
        job = _courant
    if job is not None:
        job.cancel()
        return job.snapshot
    return LoginSnapshot()


@dataclass(frozen=True)
class AccountStatus:
    api_configured: bool
    # Derniere connexion connue reussie (temoin local, sans reseau). Le
    # fichier de session seul ne prouve rien : Telethon le cree des la
    # premiere tentative, meme ratee.
    connected: bool
    # None = pas verifie (verification reseau non demandee, ou session
    # occupee) -- jamais « non connecte » par defaut.
    authorized: bool | None
    login: LoginSnapshot


def _api_configured() -> bool:
    try:
        api_credentials()
        return True
    except TelegramNotConfigured:
        return False


async def _est_autorise() -> bool:
    client = build_client()
    await client.connect()
    try:
        return bool(await client.is_user_authorized())
    finally:
        await client.disconnect()


def account_status(check: bool = False) -> AccountStatus:
    """Etat du compte. `check=True` interroge Telegram (via Tor, quelques
    secondes) pour savoir si la session est toujours valide."""
    login = current_login()
    configure = _api_configured()
    autorise: bool | None = None
    if check and configure and is_authorized_locally() and not login.active:
        try:
            with session_lock(blocking=False):
                autorise = asyncio.run(_est_autorise())
        except SessionBusy:
            autorise = None
        if autorise is False:
            # Revoquee depuis : la collecte repasse sur l'apercu web.
            mark_authorized(False)
    return AccountStatus(
        api_configured=configure,
        connected=is_authorized_locally(),
        authorized=autorise,
        login=login,
    )


async def _deconnecter() -> None:
    client = build_client()
    await client.connect()
    try:
        if await client.is_user_authorized():
            # Revoque la session CHEZ TELEGRAM, et supprime le fichier.
            await client.log_out()
    finally:
        await client.disconnect()


def logout() -> None:
    """Deconnecte le compte : la session est revoquee cote Telegram puis
    supprimee. La collecte repasse alors sur l'apercu web, sans compte."""
    if current_login().active:
        raise SessionBusy("une connexion est en cours")
    with session_lock(blocking=False):
        mark_authorized(False)
        if os.path.exists(session_file()):
            try:
                asyncio.run(_deconnecter())
            finally:
                # Meme si Telegram est injoignable : une session qu'on veut
                # retirer ne doit pas rester utilisable localement.
                if os.path.exists(session_file()):
                    os.remove(session_file())
