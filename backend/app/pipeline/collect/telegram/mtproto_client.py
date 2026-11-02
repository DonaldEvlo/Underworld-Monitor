"""Lecture de l'historique d'un canal Telegram par le Client API (MTProto).

Seule partie RESEAU de la collecte MTProto ; la conversion des messages est
pure (`mtproto.py`). Telethon est importe a l'interieur des fonctions : les
tests et les modules qui n'en ont pas besoin ne le chargent pas.

⚠️ LECTURE SEULE, PAR CONSTRUCTION. Ce module n'appelle que trois methodes :
`get_input_entity` (resoudre un nom public), `iter_messages` (lire) et
`is_user_authorized`. Il ne rejoint aucun canal, n'envoie rien, ne liste
aucun membre et ne telecharge aucun fichier -- verrouille par un test qui
relit ce fichier (`TestLectureSeule`). Un lien d'invitation (`t.me/+...`)
n'arrive jamais ici : `channel_from_url` l'ecarte en amont.

⚠️ TOR OBLIGATOIRE (regle 3). Telethon accepte un proxy SOCKS5, mais si
`python-socks` manque il se contente d'un AVERTISSEMENT et se connecte en
direct depuis l'IP du serveur. `telethon_proxy()` leve donc au lieu de
laisser passer : un contournement silencieux de Tor est pire qu'une collecte
en echec.

⚠️ UNE SESSION, UN SEUL UTILISATEUR A LA FOIS. La session Telethon est un
fichier SQLite partage par l'API (collecte a la demande) et le worker
(collecte planifiee), et la collecte groupee lance 5 sources en parallele.
Deux ouvertures simultanees se bloquent (« database is locked »). Un verrou
de fichier (`flock`, valable entre conteneurs sur le meme volume) serialise
tout acces.

⚠️ LA SESSION SE CONNECTE, ELLE NE S'OUVRE JAMAIS ICI. Si le compte n'est pas
autorise, on leve `TelegramNotAuthorized` ; seule la commande
`app.scripts.telegram_login`, lancee a la main, saisit un code. Une tache
planifiee qui demanderait un code par SMS resterait bloquee sans temoin.
"""

from __future__ import annotations

import asyncio
import fcntl
import importlib.util
import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.core.config import settings
from app.pipeline.collect.telegram.mtproto import (
    DEFAULT_MAX_MESSAGES,
    MtprotoMessage,
    message_from_telethon,
)

logger = logging.getLogger(__name__)

# Telethon dort de lui-meme sur un FloodWait plus court ; au-dela, il leve
# `FloodWaitError` et le canal est abandonne pour ce cycle. Pas de nouvelle
# tentative : insister sur une limite de debit est exactement ce qui fait
# restreindre un compte.
FLOOD_SLEEP_THRESHOLD_SECONDS = 60

# Pause entre deux pages de 100 messages (au-dela de DEFAULT_MAX_MESSAGES).
_WAIT_BETWEEN_PAGES_SECONDS = 2

_thread_lock = threading.Lock()


class TelegramNotConfigured(RuntimeError):
    """`TELEGRAM_API_ID`/`TELEGRAM_API_HASH` absents ou session inexistante."""


class TelegramNotAuthorized(RuntimeError):
    """La session existe mais n'est plus (ou pas encore) connectee."""


def api_credentials() -> tuple[int, str]:
    brut = settings.TELEGRAM_API_ID.strip()
    if not brut or not settings.TELEGRAM_API_HASH.strip():
        raise TelegramNotConfigured("TELEGRAM_API_ID / TELEGRAM_API_HASH absents")
    try:
        return int(brut), settings.TELEGRAM_API_HASH.strip()
    except ValueError as exc:
        raise TelegramNotConfigured("TELEGRAM_API_ID n'est pas un entier") from exc


def session_file() -> str:
    chemin = settings.TELEGRAM_SESSION_PATH
    return chemin if chemin.endswith(".session") else f"{chemin}.session"


def authorized_marker() -> str:
    return f"{session_file()}.authorized"


def mark_authorized(autorise: bool) -> None:
    """Pose ou retire le temoin « connexion reussie ».

    ⚠️ LE FICHIER DE SESSION NE PROUVE RIEN : Telethon le cree des la premiere
    tentative de connexion, meme si elle n'aboutit pas (constate le
    2026-09-26 : la page annoncait « session enregistree » et la collecte
    tentait le Client API pour un compte jamais connecte). Le temoin n'est
    pose QUE sur une connexion reussie, et retire des que Telegram repond
    « non autorise » (session revoquee, compte banni) ou a la deconnexion."""
    chemin = authorized_marker()
    if autorise:
        os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as f:
            f.write("")
    elif os.path.exists(chemin):
        os.remove(chemin)


def is_authorized_locally() -> bool:
    """Derniere connexion connue reussie (sans interroger Telegram)."""
    return os.path.exists(authorized_marker()) and os.path.exists(session_file())


def is_configured() -> bool:
    """Identifiants presents ET compte connecte avec succes (temoin). Ne dit
    rien de la validite ACTUELLE : une session revoquee depuis est detectee a
    la lecture suivante, qui retire le temoin et repasse sur l'apercu web."""
    try:
        api_credentials()
    except TelegramNotConfigured:
        return False
    return is_authorized_locally()


def telethon_proxy() -> dict[str, Any]:
    """Proxy SOCKS5 vers le conteneur Tor, au format Telethon.

    Leve si `python-socks` est absent -- voir docstring du module."""
    if importlib.util.find_spec("python_socks") is None:
        raise RuntimeError(
            "python-socks absent : Telethon se connecterait SANS Tor (regle 3)"
        )
    return {
        "proxy_type": "socks5",
        "addr": settings.TOR_SOCKS_HOST,
        "port": settings.TOR_SOCKS_PORT,
        "rdns": True,
    }


def build_client(receive_updates: bool = False) -> Any:
    """Client Telethon route par Tor.

    Sans reception d'evenements par defaut : la collecte lit, elle n'ecoute
    pas. ⚠️ La connexion par QR code, elle, EXIGE `receive_updates=True` :
    elle attend la notification `UpdateLoginToken` que Telegram envoie quand
    le telephone valide le QR. Sans elle, le scan reussit cote telephone et le
    script attend indefiniment (constate en relisant `QRLogin.wait`)."""
    from telethon import TelegramClient

    api_id, api_hash = api_credentials()
    os.makedirs(os.path.dirname(session_file()) or ".", exist_ok=True)
    return TelegramClient(
        session_file(),
        api_id,
        api_hash,
        proxy=telethon_proxy(),
        flood_sleep_threshold=FLOOD_SLEEP_THRESHOLD_SECONDS,
        receive_updates=receive_updates,
    )


class SessionBusy(RuntimeError):
    """La session est deja utilisee (collecte ou connexion en cours)."""


@contextmanager
def session_lock(blocking: bool = True) -> Iterator[None]:
    """Acces exclusif a la session : entre threads (verrou local) et entre
    processus/conteneurs (`flock` sur un fichier voisin de la session).

    `blocking=False` leve `SessionBusy` au lieu d'attendre : une requete HTTP
    ne doit pas rester suspendue le temps d'une connexion QR (plusieurs
    minutes) ou d'une lecture de canal."""
    if not _thread_lock.acquire(blocking=blocking):
        raise SessionBusy("session Telegram deja utilisee")
    try:
        os.makedirs(os.path.dirname(session_file()) or ".", exist_ok=True)
        with open(f"{session_file()}.lock", "w") as verrou:
            try:
                fcntl.flock(
                    verrou, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
                )
            except BlockingIOError as exc:
                raise SessionBusy("session Telegram deja utilisee") from exc
            try:
                yield
            finally:
                fcntl.flock(verrou, fcntl.LOCK_UN)
    finally:
        _thread_lock.release()


async def _read(channel: str, limit: int) -> list[MtprotoMessage]:
    client = build_client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            # Session revoquee ou compte banni : on retire le temoin, pour que
            # les passes suivantes aillent directement a l'apercu web et que
            # la page « Compte Telegram » le montre.
            mark_authorized(False)
            raise TelegramNotAuthorized(
                "session Telegram non connectee : lancer "
                "`python -m app.scripts.telegram_login`"
            )
        # Le nom est resolu une fois puis mis en cache DANS la session
        # (identifiant + access_hash) : les cycles suivants ne refont pas la
        # resolution, qui est l'appel le plus limite par Telegram.
        entite = await client.get_input_entity(channel)
        messages: list[MtprotoMessage] = []
        async for brut in client.iter_messages(
            entite, limit=limit, wait_time=_WAIT_BETWEEN_PAGES_SECONDS
        ):
            converti = message_from_telethon(brut, channel)
            if converti is not None:
                messages.append(converti)
        return messages
    finally:
        await client.disconnect()


def read_channel_history(
    channel: str, limit: int = DEFAULT_MAX_MESSAGES
) -> list[MtprotoMessage]:
    """Les `limit` messages les plus recents d'un canal ou groupe PUBLIC."""
    api_credentials()
    if not is_authorized_locally():
        raise TelegramNotConfigured(f"aucune connexion reussie : {session_file()}")
    with session_lock():
        return asyncio.run(_read(channel, limit))
