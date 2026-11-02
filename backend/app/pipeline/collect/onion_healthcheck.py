"""Verification de disponibilite des adresses .onion listees dans forums.md.

Remplace le script jetable utilise pour le premier passage manuel : meme
logique (2 passes, la seconde apres renouvellement de circuit Tor pour ne pas
confondre "source hors service" et "circuit Tor degrade"), mais integree au
pipeline et reutilisable (CLI ou import direct).

Ne fait aucune ecriture en base : logique pure (voir AGENTS.md #3), a l'image
des autres modules de `pipeline/collect/`. L'enregistrement des sources
verifiees comme `Source(type=forum)` se fait via l'API (`POST /api/sources`),
pas ici.
"""

from __future__ import annotations

import argparse
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.pipeline.collect.politeness import polite_delay
from app.pipeline.collect.tor import build_socks5_proxy_url, renew_circuit
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

# Ligne de tableau markdown `| [Nom](url) | ... |`.
#
# ⚠️ Les espaces autour du `[` sont OBLIGATOIREMENT tolerés : le depot amont
# formate desormais ses tableaux avec une espace apres le pipe (`| [Nom](...`),
# alors que l'ancien motif exigeait `^\|\[` colle. Constate le 2026-08-22 --
# le parser renvoyait **0 entree** sur le fichier reel, donc l'import GitHub
# ne trouvait plus jamais rien et le signalait comme « 0 nouvelle adresse »,
# indiscernable d'un depot a jour. Ne pas re-durcir ce motif sans verifier sur
# le fichier amont reel (voir test_github_import.py::TestRealWorldRowFormats).
_ROW_RE = re.compile(r"^\|\s*\[(?P<name>[^\]]+)\]\(\s*(?P<url>[^)\s]+)\s*\)")
_FIRST_PASS_TIMEOUT = 75
_RETRY_PASS_TIMEOUT = 100
_FIRST_PASS_WORKERS = 5
_RETRY_PASS_WORKERS = 3


@dataclass(frozen=True)
class OnionCheckResult:
    name: str
    url: str
    reachable: bool
    http_status: int | None
    checked_at: datetime


def parse_onion_entries_from_text(markdown_text: str) -> list[tuple[str, str]]:
    """Extrait les lignes `|[Name](url)|...` dont l'URL est un .onion, dedupliquees
    par URL (le fichier source contient des alias/miroirs sous des noms differents
    pointant vers la meme adresse)."""
    seen: set[str] = set()
    entries: list[tuple[str, str]] = []
    for line in markdown_text.splitlines():
        match = _ROW_RE.match(line.strip())
        if not match:
            continue
        url = match.group("url").strip()
        if ".onion" not in url:
            continue
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        if url in seen:
            continue
        seen.add(url)
        entries.append((match.group("name").strip(), url))
    return entries


def parse_onion_entries(markdown_path: str) -> list[tuple[str, str]]:
    with open(markdown_path, encoding="utf-8") as f:
        return parse_onion_entries_from_text(f.read())


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=0)  # le retry se fait au niveau des passes, pas ici
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    proxy_url = build_socks5_proxy_url(resolve_via_proxy=True)
    session.proxies = {"http": proxy_url, "https": proxy_url}
    return session


def _check_one(name: str, url: str, timeout: int) -> OnionCheckResult:
    try:
        session = _build_session()
        # Un .onion s'authentifie par son adresse elle-meme (derivee de sa cle
        # publique) : contrairement au clearnet, un certificat auto-signe n'y est
        # pas un signal d'attaque MITM et est meme la norme (pas d'autorite de
        # certification a joindre depuis le dark web). Ne jamais desactiver la
        # verification pour un hote clearnet -- seulement ici, ou l'adresse .onion
        # est deja la racine de confiance.
        verify = not url.split("//", 1)[-1].split("/", 1)[0].endswith(".onion")
        response = session.get(
            url,
            headers={"User-Agent": pick_user_agent()},
            timeout=timeout,
            verify=verify,
        )
        return OnionCheckResult(
            name, url, True, response.status_code, datetime.now(timezone.utc)
        )
    except Exception:
        logger.debug("Adresse injoignable: %s (%s)", name, url, exc_info=True)
        return OnionCheckResult(name, url, False, None, datetime.now(timezone.utc))


ResultCallback = Callable[[OnionCheckResult, str], None]
"""Rappel de progression : (resultat, passe) avec passe = "first" | "retry"."""


def _notify(callback: Callable[..., None] | None, *args: object) -> None:
    """Un suivi de progression ne doit JAMAIS faire echouer le test : c'est un
    confort d'affichage, le rapport final reste le livrable."""
    if callback is None:
        return
    try:
        callback(*args)
    except Exception:
        logger.exception("Suivi de progression du test : rappel en echec (ignore)")


def _run_pass(
    entries: list[tuple[str, str]],
    *,
    timeout: int,
    max_workers: int,
    on_result: ResultCallback | None = None,
    phase: str = "first",
) -> list[OnionCheckResult]:
    results: list[OnionCheckResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_check_one, name, url, timeout): (name, url)
            for name, url in entries
        }
        # `as_completed` rend la main dans le fil appelant : le rappel n'est
        # donc jamais execute en parallele avec lui-meme.
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            _notify(on_result, result, phase)
            polite_delay()
    return results


def check_onion_entries(
    entries: list[tuple[str, str]],
    *,
    on_result: ResultCallback | None = None,
    on_retry_start: Callable[[int], None] | None = None,
) -> list[OnionCheckResult]:
    """Teste chaque (nom, url) .onion via Tor. Deux passes : la premiere avec une
    concurrence moderee, la seconde uniquement sur les echecs et apres
    renouvellement du circuit Tor (NEWNYM) pour eliminer les faux negatifs dus a
    un circuit degrade plutot qu'a un service reellement hors ligne.

    `on_result` est appele a chaque adresse testee (dans les deux passes) et
    `on_retry_start` au debut de la seconde passe, avec le nombre d'echecs a
    retester : sans eux, un test de plusieurs minutes ne rendait AUCUN retour
    avant la fin (signale a l'usage le 2026-09-11)."""
    first_pass = _run_pass(
        entries,
        timeout=_FIRST_PASS_TIMEOUT,
        max_workers=_FIRST_PASS_WORKERS,
        on_result=on_result,
        phase="first",
    )
    by_url = {r.url: r for r in first_pass}

    failed = [(r.name, r.url) for r in first_pass if not r.reachable]
    if failed:
        logger.info(
            "Renouvellement du circuit Tor avant la passe de rattrapage (%d echecs)",
            len(failed),
        )
        _notify(on_retry_start, len(failed))
        renew_circuit()
        retry_pass = _run_pass(
            failed,
            timeout=_RETRY_PASS_TIMEOUT,
            max_workers=_RETRY_PASS_WORKERS,
            on_result=on_result,
            phase="retry",
        )
        for result in retry_pass:
            if result.reachable:
                by_url[result.url] = result

    return list(by_url.values())


def write_working_report(results: list[OnionCheckResult], output_path: str) -> int:
    """Ecrit les adresses joignables dans un rapport markdown (meme format que
    forums.md). Retourne le nombre d'entrees ecrites."""
    working = sorted((r for r in results if r.reachable), key=lambda r: r.name.upper())

    lines = [
        "# Forums .onion verifies fonctionnels",
        "",
        "> Genere par `pipeline/collect/onion_healthcheck.py` : verification de "
        "disponibilite via le conteneur Tor du projet, jamais depuis l'IP hote. "
        "Une entree absente n'est pas forcement morte (auth/JS requis, filtrage "
        "de l'IP de sortie Tor) — voir `pipeline/collect/forums.md` pour la liste "
        "complete source.",
        "",
        "| Name | Onion URL | HTTP | Verifie le |",
        "| ------ | ------ | ------ | ------ |",
    ]
    for r in working:
        lines.append(f"|{r.name}|{r.url}|{r.http_status}|{date.today().isoformat()}|")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return len(working)


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Fichier markdown source (ex: forums.md)")
    parser.add_argument(
        "output", help="Fichier markdown de sortie (adresses joignables)"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    entries = parse_onion_entries(args.input)
    print(f"{len(entries)} adresses .onion uniques a tester...")

    results = check_onion_entries(entries)
    count = write_working_report(results, args.output)
    print(f"{count}/{len(entries)} adresses confirmees joignables -> {args.output}")


if __name__ == "__main__":
    _main()
