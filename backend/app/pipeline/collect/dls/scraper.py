"""Collecte des Data Leak Sites (DLS) de gangs ransomware.

Un DLS publie la liste des organisations que le gang affirme avoir
compromises : nom, souvent le site web, un compte a rebours avant publication
et parfois le volume de donnees. C'est la source la plus directe de noms de
VICTIMES -- exactement ce que le pipeline de detection cherche a rattacher aux
entites surveillees.

**Pourquoi un module dedie plutot que `CyberScraperCollector`** (mesure du
2026-08-24 sur les 18 DLS importes) :

  - le generique produit **UN document par site** (blob de la page d'accueil).
    Les 508 victimes de LockBit tiennent donc dans un seul document, donc une
    seule alerte possible au lieu de 508 ;
  - il ne remonte **aucune date** : sans `published_at`, la fenetre
    `_ALERT_WINDOW_DAYS` de `generate_alerts` ne peut pas distinguer une
    victime publiee hier d'une publiee l'an dernier ;
  - sur NIGHT SPIRE il extrayait **4 domaines sur 191 presents** dans le HTML
    (818 Ko recus, 29 Ko conserves) -- le contenu etait la, l'extraction
    generique passait a cote.

Ce module produit **un RawDocumentContract par victime**, avec sa date et son
volume quand le site les expose -- meme principe que RansomLookCollector et
AkiraCollector (CONTRIBUTING.md : une annonce = une unite d'alerte).

Chaque gang code son site a sa facon : il n'existe PAS de structure DLS
commune. Ce module porte donc un parser par famille de site, choisi sur
l'URL. Ajouter un gang = ajouter un parser, apres avoir observe sa structure
reelle (ne jamais deviner les selecteurs)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from app.pipeline.collect.host_aliases import canonical_host

logger = logging.getLogger(__name__)

# Volume de donnees annonce ("400 GB", "2TB"). Sert de signal de gravite.
_VOLUME_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:GB|TB|MB)\b", re.I)

# Deux formats de date coexistent sur LockBit, verifies le 2026-08-24 :
#   - `.updated-post-date` : "Updated: 21 Apr, 2025,  10:00 UTC" -- present sur
#     les 508 blocs, c'est la VRAIE date de publication ;
#   - `data-timer="Jan 26, 2027 02:16:23"` : compte a rebours avant publication,
#     present sur 1 seul bloc (les victimes pas encore publiees).
# Une premiere version ne lisait que le second : 1 date sur 508. Toujours
# verifier la couverture d'un selecteur sur la page reelle, pas sur un bloc.
_LOCKBIT_TIMER_RE = re.compile(
    r"(?P<day>\d{1,2})\s+(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*,?\s*(?P<year>\d{4})"
    r"|(?P<month2>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(?P<day2>\d{1,2}),\s*(?P<year2>\d{4})",
    re.I,
)
_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ],
        start=1,
    )
}


@dataclass(frozen=True)
class DlsVictim:
    """Une organisation nommee sur un DLS.

    `name` est le libelle affiche par le gang ; `site` le site web de la
    victime quand le DLS le publie (NIGHT SPIRE le fait, LockBit non). C'est
    `site` qui porte le signal exploitable par `matching.py`, qui travaille
    sur des domaines."""

    name: str
    site: str | None = None
    published_at: datetime | None = None
    volume: str | None = None
    detail_url: str | None = None
    description: str | None = None
    # Etat de la revendication tel que le SITE l'affiche : `published` (les
    # donnees sont en ligne), `pending` (menace, compte a rebours), None (le
    # site n'expose rien -- jamais devine). Voir `PUBLISHED` / `PENDING`.
    publication_status: str | None = None
    # Ce qui, dans la page, fonde le statut : une preuve se montre.
    publication_evidence: str | None = None


# --------------------------------------------------------------------------
# Statut de publication (plan de credibilite, phase 2)
# --------------------------------------------------------------------------
#
# « Le gang a mis les donnees en ligne » et « le gang menace de le faire » ne
# portent pas la meme credibilite. Les sites l'affichent souvent -- badge,
# compte a rebours, classe CSS -- mais chacun a sa facon.
#
# ⚠️ MESURE SUR LA PAGE ENTIERE, JAMAIS SUR UN BLOC (2026-09-24, 16 sites) :
# 13 exposent un marqueur structurel, CMD / INSOMNIA / PEAR aucun (-> None).
# Pieges rencontres :
#   - LockBit porte un `.post-timer-end` « published » sur ses 508 blocs, mais
#     en `d-none` : c'est un GABARIT cache, pas une preuve. Le vrai signal est
#     le compte a rebours `data-timer`, present seulement avant publication.
#   - NIGHT SPIRE rend ses comptes a rebours en JavaScript (« 00d 00h » dans
#     le HTML) ; les echeances vivent dans un script de la page
#     (`'1858': 1790294400000`, en millisecondes).
#   - QILIN et BEAST ne marquent que l'attente : l'absence de marqueur reste
#     None, pas « publie ».

PUBLISHED = "published"
PENDING = "pending"

# Echeances NIGHT SPIRE : `'<id>': <epoch en millisecondes>`.
_NIGHTSPIRE_DEADLINE_RE = re.compile(r"['\"](\d+)['\"]\s*:\s*(\d{12,13})\b")


def _maintenant() -> datetime:
    """Horloge du statut, isolee pour etre remplacee dans les tests : un
    statut fonde sur une echeance depend de l'instant d'observation."""
    return datetime.now(timezone.utc)


def _statut_selon_echeance(
    echeance: datetime | None, preuve: str
) -> tuple[str | None, str | None]:
    """Echeance passee -> publiee ; a venir -> en attente ; inconnue -> None."""
    if echeance is None:
        return None, None
    if echeance <= _maintenant():
        return PUBLISHED, f"{preuve} passée ({echeance.date().isoformat()})"
    return PENDING, f"{preuve} à venir ({echeance.date().isoformat()})"


def _statut_libelle(libelle: str | None, table: dict[str, str]) -> dict:
    """Statut lu dans un libelle affiche (« PUBLISHED », « SOON »). Un libelle
    absent de la table reste inconnu : on ne devine pas son sens."""
    statut = table.get((libelle or "").strip().upper())
    return {
        "publication_status": statut,
        "publication_evidence": f"statut affiché « {libelle} »" if statut else None,
    }


def _parse_volume(text: str) -> str | None:
    match = _VOLUME_RE.search(text or "")
    return match.group(0) if match else None


def _parse_lockbit_date(raw: str) -> datetime | None:
    """Accepte les deux formats LockBit (jour-mois et mois-jour, voir regex)."""
    match = _LOCKBIT_TIMER_RE.search(raw or "")
    if match is None:
        return None
    day = match.group("day") or match.group("day2")
    month_name = match.group("month") or match.group("month2")
    year = match.group("year") or match.group("year2")
    month = _MONTHS.get((month_name or "").lower()[:3])
    if month is None or day is None or year is None:
        return None
    try:
        return datetime(int(year), month, int(day), tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_dotted_date(raw: str) -> datetime | None:
    """Format BEAST : `24.06.2025` (jour.mois.annee)."""
    match = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", raw or "")
    if match is None:
        return None
    try:
        return datetime(
            int(match.group(3)),
            int(match.group(2)),
            int(match.group(1)),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _parse_iso_like_date(raw: str) -> datetime | None:
    """Format INSOMNIA : `Notified: 2026-8-5` (mois/jour non zero-padded)."""
    match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", raw or "")
    if match is None:
        return None
    try:
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def parse_lockbit(html: str, base_url: str) -> list[DlsVictim]:
    """Structure LockBit : un `a.post-block` par victime.

    Verifiee le 2026-08-24 : 508 blocs, chacun avec `.post-title` (nom),
    `.post-block-text` (description) et un `.timer[data-timer]` (echeance)."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for block in soup.select("a.post-block"):
        title_el = block.select_one(".post-title")
        if title_el is None:
            continue
        name = re.sub(r"\s+", " ", title_el.get_text(strip=True)).strip()
        if not name:
            continue

        body_el = block.select_one(".post-block-text")
        description = (
            re.sub(r"\s+", " ", body_el.get_text(" ", strip=True)).strip()
            if body_el
            else None
        )

        # `.updated-post-date` d'abord : present sur les 508 blocs et porteur
        # de la date de publication reelle. Le compte a rebours n'existe que
        # pour les victimes pas encore publiees (1 bloc sur 508).
        published_at = None
        date_el = block.select_one(".updated-post-date")
        if date_el is not None:
            published_at = _parse_lockbit_date(date_el.get_text(" ", strip=True))
        timer_el = block.select_one(".timer[data-timer]")
        if published_at is None and timer_el is not None:
            published_at = _parse_lockbit_date(timer_el.get("data-timer", ""))

        # ⚠️ Le `.post-timer-end` « published » est un gabarit CACHE present
        # sur les 508 blocs : il ne prouve rien. Seul le compte a rebours
        # distingue une victime pas encore publiee (1 bloc sur 508).
        if timer_el is not None:
            statut, preuve = _statut_selon_echeance(
                _parse_lockbit_date(timer_el.get("data-timer", "")),
                "échéance du compte à rebours",
            )
        else:
            statut, preuve = PUBLISHED, "aucun compte à rebours (victime publiée)"

        href = block.get("href")
        victims.append(
            DlsVictim(
                name=name,
                site=None,  # LockBit n'expose pas le site de la victime
                published_at=published_at,
                volume=_parse_volume(description or ""),
                detail_url=urljoin(base_url, href) if href else None,
                description=description,
                publication_status=statut,
                publication_evidence=preuve,
            )
        )
    return victims


def parse_nightspire(html: str, base_url: str) -> list[DlsVictim]:
    """Structure NIGHT SPIRE : un `div.team-card` par victime.

    Verifiee le 2026-08-24 : 239 cartes, `a.team-name` portant le nom ET le
    lien vers le site de la victime -- c'est ce lien que l'extraction
    generique ratait (4 domaines remontes sur 191 presents)."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    # Les comptes a rebours sont rendus en JS (« 00d 00h » dans le HTML) ;
    # leurs echeances vivent dans un script de la page, par `data-id`.
    scripts = " ".join(s.get_text() for s in soup.find_all("script"))
    echeances = {
        ident: datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
        for ident, ms in _NIGHTSPIRE_DEADLINE_RE.findall(scripts)
    }

    for card in soup.select("div.team-card"):
        name_el = card.select_one("a.team-name")
        if name_el is None:
            continue
        name = re.sub(r"\s+", " ", name_el.get_text(strip=True)).strip()
        if not name:
            continue

        site = name_el.get("href") or None
        if site and not site.startswith(("http://", "https://")):
            site = None

        bio_el = card.select_one("p.team-bio")
        description = (
            re.sub(r"\s+", " ", bio_el.get_text(" ", strip=True)).strip()
            if bio_el
            else None
        )

        card_text = card.get_text(" ", strip=True)
        compteur = card.select_one(".countdown[data-id]")
        statut, preuve = _statut_selon_echeance(
            echeances.get(compteur.get("data-id")) if compteur else None,
            "échéance de publication",
        )
        victims.append(
            DlsVictim(
                name=name,
                site=site,
                published_at=None,  # le compte a rebours est rendu en JS
                volume=_parse_volume(card_text),
                detail_url=None,
                description=description,
                publication_status=statut,
                publication_evidence=preuve,
            )
        )
    return victims


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    """Format SAFEPAY : `2026-08-24T18:31:53.288739+00:00` (attribut
    `data-created`). Toujours ramene en UTC : une date naive serait comparee
    a tort a des dates aware ailleurs dans le pipeline."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_month_name_date(raw: str | None) -> datetime | None:
    """Format ORION : `Jul 27, 2026` (mois abrege, jour, annee)."""
    match = re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b", raw or "")
    if match is None:
        return None
    month = _MONTHS.get(match.group(1).lower()[:3])
    if month is None:
        return None
    try:
        return datetime(
            int(match.group(3)), month, int(match.group(2)), tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _parse_slash_date(raw: str | None) -> datetime | None:
    """Format PEAR : `Date Company Notified: 08/20/2026`.

    Mois AVANT jour (convention US) -- verifie sur les blocs reels, ou l'on
    trouve `08/20/2026` : un 20e mois n'existe pas, l'ordre est donc bien
    mois/jour. Ne pas transposer ce choix a Dread, qui date au contraire en
    jour-avant-mois (voir dread/scraper.py)."""
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", raw or "")
    if match is None:
        return None
    try:
        return datetime(
            int(match.group(3)),
            int(match.group(1)),
            int(match.group(2)),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned or None


def _normalise_site(raw: str | None) -> str | None:
    """Normalise un site de victime en URL absolue.

    Plusieurs DLS l'ecrivent sans schema ("www.industrie-exemple.com") : sans ce
    prefixe, `extract_mentioned_urls` ne le verrait pas et le domaine serait
    perdu pour la detection."""
    site = _clean(raw)
    if not site:
        return None
    if site.startswith(("http://", "https://")):
        return site
    if "." not in site or " " in site:
        return None
    return f"http://{site}"


def parse_beast(html: str, base_url: str) -> list[DlsVictim]:
    """BEAST : un `a.card` par victime.

    Le plus riche des DLS observes -- nom, description, date, statut, chiffre
    d'affaires, site et volume sont dans des `span` dedies. Le collecteur
    generique n'en tirait pourtant AUCUN document (mesure du 2026-08-24)."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("a.card"):
        name = (
            _clean(card.select_one("h3").get_text()) if card.select_one("h3") else None
        )
        if not name:
            continue
        href = card.get("href")
        info = card.select_one(".card-info")
        info_text = info.get_text(" ", strip=True) if info else ""
        # BEAST ne marque que l'ATTENTE (43 « unpublished », 27 comptes a
        # rebours sur 70) : sans marqueur, le statut reste inconnu.
        if card.select_one(".unpublished"):
            statut, preuve = PENDING, "marquée « unpublished »"
        elif card.select_one(".timer"):
            statut, preuve = PENDING, "compte à rebours affiché"
        else:
            statut, preuve = None, None
        victims.append(
            DlsVictim(
                name=name,
                site=_normalise_site(
                    card.select_one(".website").get_text()
                    if card.select_one(".website")
                    else None
                ),
                published_at=_parse_dotted_date(
                    card.select_one(".date").get_text()
                    if card.select_one(".date")
                    else ""
                ),
                volume=_parse_volume(info_text),
                detail_url=urljoin(base_url, href) if href else None,
                description=_clean(
                    card.select_one(".card-text").get_text(" ")
                    if card.select_one(".card-text")
                    else None
                ),
                publication_status=statut,
                publication_evidence=preuve,
            )
        )
    return victims


def parse_insomnia(html: str, base_url: str) -> list[DlsVictim]:
    """INSOMNIA : un `div.book-card` par victime, metadonnees en `.card-meta`
    sous forme "Website: ... Revenue: ... Notified: 2026-8-5"."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("div.book-card"):
        title = card.select_one(".info-title")
        name = _clean(title.get_text()) if title else None
        if not name:
            continue
        meta_text = card.select_one(".card-meta")
        meta_text = meta_text.get_text(" ", strip=True) if meta_text else ""
        site_match = re.search(r"Website:\s*([^\s]+)", meta_text, re.I)
        link = title.select_one("a")
        victims.append(
            DlsVictim(
                name=name,
                site=_normalise_site(site_match.group(1) if site_match else None),
                published_at=_parse_iso_like_date(meta_text),
                volume=_parse_volume(meta_text),
                detail_url=(
                    urljoin(base_url, link["href"])
                    if link and link.get("href")
                    else None
                ),
                description=_clean(
                    card.select_one(".info-desc").get_text(" ")
                    if card.select_one(".info-desc")
                    else None
                ),
            )
        )
    return victims


# APT73 place le lien de sa page victime dans un `onclick`, pas un `href` :
#   onclick="window.location.href='/page_company.php?id=161'"
#
# ⚠️ MEME PIEGE QUE KRYBIT (2026-08-24). Chercher un `href` n'est pas chercher
# une structure : le lien existait depuis le debut, invisible a qui n'inspecte
# que les liens. Consequence mesurée le 2026-09-04 : **112 documents APT73 sur
# 132 restaient tronques** (« ...provides insurance (aut... »), alors que la
# page de detail porte la description complete ET le volume (« The total size
# is 44.5 GB ») -- lequel alimente desormais la severite.
_ONCLICK_LOCATION = re.compile(
    r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE
)


def _onclick_url(element) -> str | None:
    """URL cachee dans un attribut `onclick`, s'il y en a une."""
    onclick = element.get("onclick") or ""
    trouve = _ONCLICK_LOCATION.search(onclick)
    return trouve.group(1) if trouve else None


def parse_apt73(html: str, base_url: str) -> list[DlsVictim]:
    """APT73 / BASHE : un `div.segment` par victime.

    Le nom EST le domaine de la victime (`ciment-exemple.com`) -- c'est donc lui qui
    porte le signal, pas un champ site separe."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for segment in soup.select("div.segment"):
        name_el = segment.select_one(".segment__text__off")
        name = _clean(name_el.get_text()) if name_el else None
        if not name:
            continue
        desc_el = segment.select_one(".segment__text__dsc")
        chemin = _onclick_url(segment)
        badge = segment.select_one(".segment__block.published")
        publie = badge is not None and "none" not in (badge.get("style") or "")
        victims.append(
            DlsVictim(
                name=name,
                site=_normalise_site(name if "." in name else None),
                published_at=None,  # rendu par script, absent du HTML servi
                volume=_parse_volume(segment.get_text(" ", strip=True)),
                detail_url=urljoin(base_url, chemin) if chemin else None,
                description=_clean(desc_el.get_text(" ") if desc_el else None),
                publication_status=PUBLISHED if publie else None,
                publication_evidence="badge « Published »" if publie else None,
            )
        )
    return victims


def parse_payload(html: str, base_url: str) -> list[DlsVictim]:
    """PAYLOAD : un `a.card-link` par victime, volume dans `.company-size`."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for link in soup.select("a.card-link"):
        title = link.select_one(".title")
        name = _clean(title.get_text()) if title else None
        if not name:
            continue
        size = link.select_one(".company-size")
        body = link.select_one("pre.body")
        href = link.get("href")
        if link.select_one(".timer-expired"):
            statut, preuve = PUBLISHED, "compte à rebours expiré"
        elif link.select_one(".timer"):
            statut, preuve = PENDING, "compte à rebours actif"
        else:
            statut, preuve = None, None
        victims.append(
            DlsVictim(
                name=name,
                site=None,  # le site n'est pas expose en clair (lien "↗ site")
                published_at=None,
                volume=_clean(size.get_text()) if size else None,
                detail_url=urljoin(base_url, href) if href else None,
                description=_clean(body.get_text(" ") if body else None),
                publication_status=statut,
                publication_evidence=preuve,
            )
        )
    return victims


def parse_qilin(html: str, base_url: str) -> list[DlsVictim]:
    """QILIN : un `a.item_box-title` par victime, site dans
    `.item_box-info__link`. Le collecteur generique n'en tirait aucun
    domaine."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for title in soup.select("a.item_box-title"):
        name = _clean(title.get_text())
        if not name:
            continue
        # Le bloc parent porte le site et la date.
        container = title.find_parent("div")
        block_text = container.get_text(" ", strip=True) if container else ""
        site_link = container.select_one(".item_box-info__link") if container else None
        href = title.get("href")
        # « Time till publication » vit dans le bloc englobant `div.item_box`,
        # pas dans le parent immediat. QILIN ne marque que l'attente.
        boite = title.find_parent("div", class_="item_box")
        attente = boite is not None and (
            boite.select_one(".timer_publicated, .countdown-timer") is not None
        )
        victims.append(
            DlsVictim(
                name=name,
                site=_normalise_site(site_link.get("href") if site_link else None),
                published_at=_parse_lockbit_date(block_text),
                volume=_parse_volume(block_text),
                detail_url=urljoin(base_url, href) if href else None,
                description=None,
                publication_status=PENDING if attente else None,
                publication_evidence="« Time till publication »" if attente else None,
            )
        )
    return victims


def parse_sarcoma(html: str, base_url: str) -> list[DlsVictim]:
    """SARCOMA : un `div.card` par victime, nom dans `.card-title` (apres le
    compteur de vues, d'ou le nettoyage des chiffres isoles)."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("div.card"):
        title_el = card.select_one(".card-title")
        if title_el is None:
            continue
        raw = _clean(title_el.get_text(" ")) or ""
        # "60527 Propane Exemple Inc." -> le compteur de vues precede le nom.
        name = _clean(re.sub(r"^\s*[\d\s]+", "", raw))
        if not name:
            continue
        victims.append(
            DlsVictim(
                name=name,
                site=None,
                published_at=None,
                volume=_parse_volume(card.get_text(" ", strip=True)),
                detail_url=None,
                description=None,
            )
        )
    return victims


def parse_direwolf(html: str, base_url: str) -> list[DlsVictim]:
    """DIRE WOLF : un `div.card` par victime.

    Le plus complet des DLS observes : `.card-meta` porte "Published:
    2026-08-21" et `.card-summary-item` expose Company/Website/Data Size en
    paires label/valeur."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("div.card"):
        title_el = card.select_one(".card-title")
        if title_el is None:
            continue
        # Le drapeau pays precede le nom dans un span dedie : on prend le
        # dernier span, qui porte la raison sociale.
        spans = title_el.select("span")
        name = _clean(spans[-1].get_text()) if spans else _clean(title_el.get_text())
        if not name:
            continue

        summary = {}
        for item in card.select(".card-summary-item"):
            label = item.select_one(".card-summary-label")
            value = item.select_one(".card-summary-value")
            if label and value:
                summary[_clean(label.get_text()) or ""] = _clean(value.get_text())

        meta_el = card.select_one(".card-meta")
        link = card.select_one("a[href]")
        # ⚠️ La classe est portee par la CARTE elle-meme
        # (`div.card.countdown-active`) : `select_one` ne cherche que dans les
        # descendants et ne la voyait pas (0 statut sur 30 au premier essai).
        # ⚠️ « Published: <date> » de `.card-meta` date l'ANNONCE, pas la mise
        # en ligne : une carte au compte a rebours actif l'affiche aussi.
        classes = card.get("class") or []
        if "countdown-expired" in classes:
            statut, preuve = PUBLISHED, "compte à rebours expiré"
        elif "countdown-active" in classes:
            statut, preuve = PENDING, "compte à rebours actif"
        else:
            statut, preuve = None, None
        victims.append(
            DlsVictim(
                name=name,
                site=_normalise_site(summary.get("Website:")),
                published_at=_parse_iso_like_date(
                    meta_el.get_text(" ", strip=True) if meta_el else ""
                ),
                volume=summary.get("Data Size:"),
                detail_url=urljoin(base_url, link["href"]) if link else None,
                description=summary.get("Industry:"),
                publication_status=statut,
                publication_evidence=preuve,
            )
        )
    return victims


def parse_metaencrypter(html: str, base_url: str) -> list[DlsVictim]:
    """METAENCRYPTER : un `div.lt-card` par victime.

    Le generique n'en tirait AUCUN domaine (mesure du 2026-08-24) : le nom est
    une raison sociale dans `.lt-card-name`, les metadonnees (volume, pays)
    sont en paires `.lt-meta-key` / `.lt-meta-val`."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("div.lt-card"):
        name_el = card.select_one(".lt-card-name")
        name = _clean(name_el.get_text()) if name_el else None
        if not name:
            continue

        meta = {}
        for row in card.select(".lt-meta-row"):
            key = row.select_one(".lt-meta-key")
            val = row.select_one(".lt-meta-val")
            if key and val:
                meta[_clean(key.get_text()) or ""] = _clean(val.get_text())

        memo_el = card.select_one(".lt-card-memo")
        victims.append(
            DlsVictim(
                name=name,
                site=None,  # non expose sur la page d'accueil
                published_at=None,
                volume=meta.get("Data size"),
                detail_url=None,
                description=_clean(memo_el.get_text(" ") if memo_el else None),
            )
        )
    return victims


def parse_krybit(html: str, base_url: str) -> list[DlsVictim]:
    """KRYBIT : un `div.post-card` par victime.

    Le titre EST le domaine de la victime (`reseaux-exemple.com`), le statut est dans
    `.post-status` ("PUBLISHED" / "SOON"). Le lien de detail vit dans un
    attribut `onclick`, pas dans un `href` -- c'est pour cela qu'une premiere
    analyse par liens n'avait rien trouve et que ce site etait reste sur le
    collecteur generique, qui en faisait un blob unique de 74 victimes.

    C'est ce blob qui masquait la seule victime senegalaise du corpus
    (`institution-exemple.sn`) : noyee dans un document dont le titre etait
    simplement « KRYBIT »."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("div.post-card"):
        title_el = card.select_one(".post-title")
        name = _clean(title_el.get_text()) if title_el else None
        if not name:
            continue

        excerpt_el = card.select_one(".post-excerpt")
        status_el = card.select_one(".post-status")
        status = _clean(status_el.get_text()) if status_el else None

        # Le detail est dans `onclick="window.location='/blog/<hash>/'"`.
        detail_url = None
        onclick = card.get("onclick") or ""
        href_match = re.search(r"window\.location\s*=\s*'([^']+)'", onclick)
        if href_match:
            detail_url = urljoin(base_url, href_match.group(1))

        victims.append(
            DlsVictim(
                name=name,
                # Le titre est deja un domaine sur ce site : on le remonte
                # comme site pour que `extract_mentioned_urls` le voie.
                site=_normalise_site(name if "." in name else None),
                published_at=None,  # aucune date exposee sur le listing
                volume=_parse_volume(card.get_text(" ", strip=True)),
                detail_url=detail_url,
                description=_clean(
                    f"{status + ' - ' if status else ''}"
                    f"{excerpt_el.get_text(' ') if excerpt_el else ''}"
                ),
                **_statut_libelle(status, {"PUBLISHED": PUBLISHED, "SOON": PENDING}),
            )
        )
    return victims


def parse_dragonforce(html: str, base_url: str) -> list[DlsVictim]:
    """DRAGON FORCE : un `div.publications-list__publication` par victime.

    Application Vue (attributs `data-v-*` partout). Le site de la victime est
    en clair dans `p.list-publication__website` ET dans le `href` du lien
    `.addictional-row__link` -- on prefere le href, deja absolu.

    Ce site figurait parmi les "sans structure exploitable" : l'analyse
    precedente cherchait des motifs d'URL de detail, or DRAGON FORCE n'expose
    pas de page par victime depuis le listing. La structure repetitive, elle,
    existait bien -- 24 blocs."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("div.publications-list__publication"):
        name_el = card.select_one("h3.list-publication__name")
        site_el = card.select_one("p.list-publication__website")
        name = _clean(name_el.get_text()) if name_el else None
        site_text = _clean(site_el.get_text()) if site_el else None
        # A defaut de raison sociale, le domaine fait office de nom.
        name = name or site_text
        if not name:
            continue

        link = card.select_one("a.addictional-row__link[href]")
        site = _normalise_site(link.get("href") if link else site_text)
        if card.select_one(".list-publication__timer-publicated"):
            statut, preuve = PUBLISHED, "bloc « publicated »"
        elif card.select_one(".list-publication__timer-publication"):
            statut, preuve = PENDING, "compte à rebours avant publication"
        else:
            statut, preuve = None, None
        # ⚠️ COMPTE A REBOURS RENDU PAR LE SERVEUR (2026-09-24) : « Publication:
        # 5 days 13:15:56 » change a chaque seconde et etait recopie dans la
        # description -- chaque victime EN ATTENTE etait recreee a chaque
        # collecte. Retire APRES la lecture du statut, qui en a besoin.
        for compteur in card.select(".timer-publication__timer"):
            compteur.decompose()

        victims.append(
            DlsVictim(
                name=name,
                site=site,
                published_at=None,
                volume=_parse_volume(card.get_text(" ", strip=True)),
                detail_url=None,
                description=_clean(card.get_text(" ", strip=True)),
                publication_status=statut,
                publication_evidence=preuve,
            )
        )
    return victims


def parse_safepay(html: str, base_url: str) -> list[DlsVictim]:
    """SAFEPAY : un `div.card` par victime, le titre EST le domaine.

    Deux etats coexistent et ne portent PAS la meme information : une victime
    publiee a `div.published-text`, une victime a venir a une
    `div.countdown-bar` avec `data-created`/`data-end`. On lit `data-created`
    (mise en ligne de l'annonce), jamais `data-end` -- c'est exactement le
    piege du `data-timer` LockBit, qui avait donne 1 date sur 508."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("div.card"):
        title_el = card.select_one("h5.card-title")
        name = _clean(title_el.get_text()) if title_el else None
        if not name:
            continue

        published_at = None
        bar = card.select_one("[data-created]")
        if bar is not None:
            published_at = _parse_iso_datetime(bar.get("data-created"))

        status_el = card.select_one("div.published-text")
        status = _clean(status_el.get_text()) if status_el else None
        body_el = card.select_one("p.card-text")
        # Deux etats exclusifs (docstring) : texte « Published » ou barre de
        # compte a rebours.
        if status_el is not None:
            statut, preuve = PUBLISHED, "mention « Published »"
        elif bar is not None:
            statut, preuve = PENDING, "barre de compte à rebours"
        else:
            statut, preuve = None, None

        victims.append(
            DlsVictim(
                name=name,
                site=_normalise_site(name if "." in name else None),
                published_at=published_at,
                volume=_parse_volume(card.get_text(" ", strip=True)),
                detail_url=None,
                description=_clean(
                    f"{status + ' - ' if status else ''}"
                    f"{body_el.get_text(' ') if body_el else ''}"
                ),
                publication_status=statut,
                publication_evidence=preuve,
            )
        )
    return victims


def parse_orion(html: str, base_url: str) -> list[DlsVictim]:
    """ORION : un `div.post-card` par victime.

    ⚠️ Les deux champs ne portent PAS ce que leur nom suggere, et cela varie
    d'un bloc a l'autre -- verifie sur les 12 blocs, pas sur le premier :

      - bloc[0]  : `h5.card-title` = "https://www.chimie-exemple.in" (une URL),
                   `span.company-name` = "Exemple Chemicals India".
      - bloc[3+] : `h5.card-title` = "kioti" (un simple libelle),
                   `span.company-name` = "tracteurs-exemple.com" (LE domaine).

    Lire le seul bloc[0] menait a prendre `card-title` pour le site : 1 site
    sur 12. On teste donc les DEUX champs et on retient celui qui ressemble a
    un domaine ou a une URL. Meme famille de piege que le `data-timer` de
    LockBit (1 date sur 508)."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("div.post-card"):
        # ⚠️ COMPTEUR DE VUES SANS LIBELLE (2026-09-24) : `div.views-count` ne
        # porte qu'une icone d'oeil et un nombre (« 73171 »), sans le mot
        # « views » que `neutraliser_compteurs` sait reconnaitre. Recopie dans
        # la description via `card.get_text`, il changeait le `content_hash` a
        # chaque consultation : 16 victimes ORION recreees, le piege du
        # 2026-09-04 revenu par un autre element. Retire a la source.
        for compteur in card.select(".views-count"):
            compteur.decompose()
        company_el = card.select_one("span.company-name")
        title_el = card.select_one("h5.card-title")
        company_text = _clean(company_el.get_text()) if company_el else None
        title_text = _clean(title_el.get_text()) if title_el else None

        # Le site est celui des deux champs qui contient un point ; on
        # privilegie une URL explicite quand elle existe.
        site_text = None
        for candidate in (title_text, company_text):
            if candidate and candidate.startswith(("http://", "https://")):
                site_text = candidate
                break
        if site_text is None:
            for candidate in (company_text, title_text):
                if candidate and "." in candidate and " " not in candidate:
                    site_text = candidate
                    break

        # Le nom est l'autre champ : une raison sociale si elle differe du
        # site, sinon le site lui-meme.
        name = company_text if company_text != site_text else title_text
        name = name or company_text or title_text
        if not name:
            continue

        date_el = card.select_one("small.leak-date")
        published_at = _parse_month_name_date(date_el.get_text()) if date_el else None
        status_el = card.select_one("span.status-text")
        status = _clean(status_el.get_text()) if status_el else None
        # Seul `status-published` a ete observe (12/12) : un autre badge reste
        # inconnu plutot que d'etre suppose « en attente ».
        publie = card.select_one(".status-badge.status-published") is not None

        victims.append(
            DlsVictim(
                name=name,
                site=_normalise_site(site_text),
                published_at=published_at,
                volume=_parse_volume(card.get_text(" ", strip=True)),
                detail_url=None,
                description=_clean(
                    f"{status + ' - ' if status else ''}"
                    f"{card.get_text(' ', strip=True)}"
                ),
                publication_status=PUBLISHED if publie else None,
                publication_evidence="badge « PUBLISHED »" if publie else None,
            )
        )
    return victims


def parse_mydata(html: str, base_url: str) -> list[DlsVictim]:
    """MYDATA / ALPHA LOCKER : un `div.news_div` par victime.

    `a.a_title` porte le site (parfois avec schema, parfois sans) et pointe
    vers la page de detail (`blog_1-30`). La raison sociale ouvre le bloc de
    description, avant le premier `<br>`.

    Ce site publie des mots de passe d'archives en clair dans ses
    descriptions. Ils restent dans `description` (ce sont des donnees de
    l'annonce, pas des identifiants de victime au sens de la regle 2), mais
    ils ne doivent JAMAIS servir a ouvrir quoi que ce soit -- regle 1,
    observation uniquement."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("div.news_div"):
        link = card.select_one("a.a_title")
        site_text = _clean(link.get_text()) if link else None
        if not site_text:
            continue

        # La raison sociale precede le premier <br> du bloc de description.
        body = card.select_one("div[style*='line-height']")
        company = None
        if body is not None:
            first_line = body.get_text("\n", strip=True).split("\n")[0]
            company = _clean(first_line)

        detail_url = None
        if link is not None and link.get("href"):
            detail_url = urljoin(base_url, link["href"])

        status_el = card.select_one("div.data_published_text")
        status = _clean(status_el.get_text()) if status_el else None
        publie = bool(status) and "published" in status.lower()

        victims.append(
            DlsVictim(
                name=company or site_text,
                site=_normalise_site(site_text),
                published_at=None,
                volume=_parse_volume(card.get_text(" ", strip=True)),
                detail_url=detail_url,
                description=_clean(
                    f"{status + ' - ' if status else ''}"
                    f"{body.get_text(' ') if body is not None else ''}"
                ),
                publication_status=PUBLISHED if publie else None,
                publication_evidence=f"mention « {status} »" if publie else None,
            )
        )
    return victims


def parse_daixin(html: str, base_url: str) -> list[DlsVictim]:
    """DAIXIN : un `div.card-body` par victime.

    `h4.card-title` porte la raison sociale, et le sous-titre
    `h6.card-subtitle` annoncant "Web Site:" porte le domaine.

    Tous les blocs ne sont PAS des victimes nommees : certains annoncent un
    lot generique ("A little gift of exclusive data for everyone") sans site.
    On les conserve -- ce sont de vraies annonces -- mais `site` reste None,
    donc ils ne produisent aucune detection `domain`."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("div.card-body"):
        title_el = card.select_one("h4.card-title")
        name = _clean(title_el.get_text()) if title_el else None
        if not name:
            continue

        # Le lien du site vit dans le sous-titre qui annonce "Web Site:".
        site = None
        for sub in card.select("h6.card-subtitle"):
            text = sub.get_text(" ", strip=True)
            if "web site" in text.lower():
                anchor_el = sub.select_one("a[href]")
                raw = anchor_el["href"] if anchor_el else text.split(":", 1)[-1]
                site = _normalise_site(raw)
                break

        body_el = card.select_one("p.card-text")
        # Les sous-titres annoncent la mise en ligne : lien « FULL LEAK » vers
        # les donnees, ou compte a rebours « Expired ». Rien d'autre n'est lu.
        sous_titres = " ".join(
            sub.get_text(" ", strip=True).lower()
            for sub in card.select("h6.card-subtitle")
        )
        publie = "full leak" in sous_titres or "expired" in sous_titres

        victims.append(
            DlsVictim(
                name=name,
                site=site,
                published_at=None,
                volume=_parse_volume(card.get_text(" ", strip=True)),
                detail_url=None,
                description=_clean(
                    body_el.get_text(" ") if body_el else card.get_text(" ")
                ),
                publication_status=PUBLISHED if publie else None,
                publication_evidence=(
                    "sous-titre « FULL LEAK » / « Expired »" if publie else None
                ),
            )
        )
    return victims


def parse_pear(html: str, base_url: str) -> list[DlsVictim]:
    """PEAR : la page est un mailing HTML (tables imbriquees), pas une grille.

    Un `div.info` par victime, mais le nom n'est pas un titre : il vit dans
    l'attribut `id` de `input.info__switch` (`mgrlaw`, `islandnetjm`), qui
    sert d'ancre au depliage "Show more". Le corps porte "Date Company
    Notified:" et "Site: <a>".

    C'est le cas limite qui justifie de ne PAS ecrire de parser "generique
    DLS" : aucun autre site observe n'encode ses donnees dans un `id` de
    checkbox."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for block in soup.select("div.info"):
        body = block.select_one("div.info__body")
        if body is None:
            continue
        text = body.get_text(" ", strip=True)

        site = None
        anchor_el = body.select_one("a[href]")
        if anchor_el is not None:
            site = _normalise_site(_clean(anchor_el.get_text()) or anchor_el["href"])

        switch = block.select_one("input.info__switch")
        slug = _clean(switch.get("id")) if switch is not None else None

        name = None
        if site:
            name = urlparse(site).hostname or site
        name = name or slug
        if not name:
            continue

        victims.append(
            DlsVictim(
                name=name,
                site=site,
                published_at=_parse_slash_date(text),
                volume=_parse_volume(text),
                detail_url=None,
                description=_clean(text),
            )
        )
    return victims


def parse_cmd(html: str, base_url: str) -> list[DlsVictim]:
    """CMD ORGANIZATION : un `div.item-card` par victime.

    La page d'accueil ne montre que les 3 dernieres victimes sur 41 : la liste
    complete vit sur `/items`, paginee par 6 (`?page=N&per_page=M`). C'est
    `fetch.py` qui gere cette pagination -- ce parser ne lit qu'une page.
    Confondre l'accueil avec la liste aurait rendu 3 victimes sur 41 sans
    qu'aucune erreur ne soit levee."""
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for card in soup.select("div.item-card"):
        header = card.select_one("div.item-header")
        anchor_el = header.select_one("h2 a[href]") if header else None
        name = _clean(anchor_el.get_text()) if anchor_el else None
        if not name:
            continue

        body_el = card.select_one("div.description-before")

        victims.append(
            DlsVictim(
                name=name,
                site=_normalise_site(anchor_el.get("href")),
                published_at=None,
                volume=_parse_volume(card.get_text(" ", strip=True)),
                detail_url=None,
                description=_clean(
                    body_el.get_text(" ") if body_el else card.get_text(" ")
                ),
            )
        )
    return victims


# Un parser par famille de site, choisi sur l'hote. Ajouter un gang suppose
# d'avoir OBSERVE sa structure (voir docstring du module) -- pas de parser
# "generique DLS", ces sites n'ont aucune structure commune.
#
# Les DLS absents de cette table retombent volontairement sur le collecteur
# generique : mieux vaut un blob exploitable que des selecteurs devines.
def _horodatage_ms(valeur) -> datetime | None:
    """Horodatage en MILLISECONDES -> datetime UTC. None si inexploitable.

    INC RANSOM date ses annonces en millisecondes depuis l'epoque. Diviser
    par 1000 est obligatoire : traite comme des secondes, `1791380096782`
    tomberait en l'an 58 000 et `datetime.fromtimestamp` leverait."""
    try:
        millisecondes = int(valeur)
    except (TypeError, ValueError):
        return None
    if millisecondes <= 0:
        # 0 = « jamais », meme convention que l'epoch des renseignements
        # ransomware.live : une sentinelle n'est pas une date.
        return None
    try:
        return datetime.fromtimestamp(millisecondes / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _date_jour_mois_annee(valeur: str | None) -> datetime | None:
    """« 16/02/2026 » -> datetime UTC.

    ⚠️ JOUR avant MOIS. Mesure du 2026-10-08 sur RansomHouse : des valeurs
    comme `21/08/2026` et `26/03/2026` prouvent l'ordre (il n'y a pas de 21e
    mois). Lire mois/jour daterait une victime de plusieurs mois a cote --
    meme famille que le format `24th January, 2026` de Dread."""
    trouve = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", (valeur or "").strip())
    if not trouve:
        return None
    jour, mois, annee = (int(x) for x in trouve.groups())
    try:
        return datetime(annee, mois, jour, tzinfo=timezone.utc)
    except ValueError:
        return None


def _site_si_domaine(nom: str) -> str | None:
    """Le nom publie EST-il un domaine ?

    Plusieurs gangs titrent indifferemment par le domaine
    (`www.camping-exemple.com`) ou par la raison sociale (`The New
    Community School`). On ne remonte un site que dans le premier cas : un
    `site` invente ferait porter une detection `domain` a une chaine qui n'en
    est pas une."""
    return _normalise_site(nom if "." in nom and " " not in nom else None)


def parse_incransom(html: str, base_url: str) -> list[DlsVictim]:
    """INC RANSOM : une API JSON, pas une page HTML.

    `GET /api/v1/blog/get/announcements?page=N&perPage=30` rend
    `{type, message, payload: {announcements: [...], length: 855}}`. Le HTML
    de son blog, lui, fait 448 octets : c'est une application qui appelle sa
    propre API. Un parser JSON est plus robuste qu'un selecteur CSS -- il n'y
    a pas de piege « meme champ, sens different selon le bloc » (ORION).

    Releve du 2026-10-08 sur le site reel : **855 victimes**, 30 par page,
    pagination VERIFIEE (la page 2 rend 30 entrees inedites, aucune repetition
    de la page 1 -- contrairement a CMD qui re-servait sa derniere page).

    ⚠️ `visits` est VOLATIL (809, 946, 8927 sur trois entrees) et n'entre
    JAMAIS dans la description : il changerait le `content_hash` a chaque
    passage et la deduplication ne reconnaitrait plus un document deja vu --
    le defaut qui avait produit 111 documents ORION pour 12 victimes.

    ⚠️ `leakAt` N'EST PAS la date de publication et n'est pas utilisee. Pour
    « Tec Imports » elle vaut 2025-07-10 alors que l'annonce a ete creee le
    2026-10-07 : les deux champs ne decrivent pas le meme fait. Une date
    fausse est pire qu'une date absente -- elle se propagerait dans le tri
    par fraicheur, la fenetre d'alerting et le rapport PDF. La date retenue
    est `createdAt`, qui ordonne effectivement la liste servie.

    ⚠️ Les valeurs sont URL-ENCODEES (`The%20New%20Community%20School`) :
    sans `unquote`, le nom de la victime serait illisible et ne matcherait
    aucun selecteur d'entite.

    ⚠️ Aucun statut de publication n'est expose (`categories` vaut
    « Encrypted », « Proof », « AD Dump »... soit le type de donnees, pas
    leur mise en ligne) : le statut reste None plutot que devine.
    """
    try:
        donnees = json.loads(html)
    except (TypeError, ValueError):
        # Pas du JSON : l'appelant leve avec le diagnostic de la page, qui
        # dira si le site a demenage ou s'est ferme.
        return []
    if not isinstance(donnees, dict):
        return []
    payload = donnees.get("payload")
    annonces = payload.get("announcements") if isinstance(payload, dict) else None
    if not isinstance(annonces, list):
        return []

    victims: list[DlsVictim] = []
    for annonce in annonces:
        if not isinstance(annonce, dict):
            continue
        societe = annonce.get("company")
        societe = societe if isinstance(societe, dict) else {}
        name = _clean(unquote(str(societe.get("company_name") or "")))
        if not name:
            continue
        # `description` est une LISTE de paragraphes, pas une chaine.
        brut = annonce.get("description")
        morceaux = brut if isinstance(brut, list) else [brut]
        description = _clean(
            " ".join(unquote(str(m)) for m in morceaux if isinstance(m, str))
        )
        categories = [
            unquote(str(c))
            for c in (annonce.get("categories") or [])
            if isinstance(c, str)
        ]
        prefixe = f"{', '.join(categories)} - " if categories else ""
        victims.append(
            DlsVictim(
                name=name,
                site=_site_si_domaine(name),
                published_at=_horodatage_ms(annonce.get("createdAt")),
                volume=_parse_volume(description or ""),
                detail_url=None,
                description=_clean(f"{prefixe}{description or ''}"),
            )
        )
    return victims


def parse_ransomhouse(html: str, base_url: str) -> list[DlsVictim]:
    """RANSOMHOUSE : une API JSON (`GET /a`), pas une page HTML.

    Rend `{data: [...30 entrees...], errors: [], views: "3652097"}` ; le HTML
    servi par `/` est une coquille d'application de 622 octets. Releve du
    2026-10-08 : `header` = nom de la victime, `url` = son site (URL absolue
    deja complete), plus `revenue`, `employees`, `info` (description),
    `volume`, `action`/`actionDate` et `published`.

    ⚠️ LA PREMIERE ENTREE N'EST PAS UNE VICTIME : c'est une banniere
    d'actualite (`display: "animated"`, `header: "HOT NEWS"`, `url` vide) qui
    recapitule les trois dernieres victimes. L'enregistrer creerait un
    document fourre-tout -- exactement le blob que ce module existe pour
    eviter -- et son `info` changerait a chaque nouvelle victime, donc son
    `content_hash` aussi.

    ⚠️ `views` (a la racine ET par entree) est VOLATIL : hors de la
    description, sinon la victime est recreee a chaque collecte.

    ⚠️ LE STATUT VIENT DE `published` SEUL, ET SEULEMENT QUAND LES DEUX
    CHAMPS CONCORDENT. Mesure du 2026-10-08 sur les 30 entrees :
    `EVIDENCE + NOT YET` 17, `DISCLOSED + date` 8, **`DISCLOSED + NOT YET`
    4**. Ces 4 cas se contredisent -- le gang dit « divulgue » et « pas
    encore publie » -- donc leur statut reste **inconnu** plutot qu'invente.
    Une date vaut PUBLISHED, `NOT YET` avec `EVIDENCE` vaut PENDING, le reste
    None (« pas evalue », jamais « aucun »).

    ⚠️ `volume` vaut `~` sur 29 entrees sur 30 : c'est « non precise », pas un
    volume. Le reprendre tel quel remplirait le champ de tildes.

    ⚠️ `actionDate` est la date de l'ATTAQUE, pas de la publication : elle
    n'alimente pas `published_at` (meme distinction que `attackdate` et
    `discovered` chez ransomware.live).
    """
    try:
        donnees = json.loads(html)
    except (TypeError, ValueError):
        return []
    if not isinstance(donnees, dict):
        return []
    entrees = donnees.get("data")
    if not isinstance(entrees, list):
        return []

    victims: list[DlsVictim] = []
    for entree in entrees:
        if not isinstance(entree, dict):
            continue
        # La banniere d'actualite se reconnait a son `display`, pas a sa
        # position : un jour elle ne sera plus la premiere.
        if str(entree.get("display") or "").strip().lower() == "animated":
            continue
        name = _clean(str(entree.get("header") or ""))
        if not name:
            continue
        publication = _clean(str(entree.get("published") or ""))
        date_publication = _date_jour_mois_annee(publication)
        statut = etat = None
        if date_publication is not None:
            statut = PUBLISHED
            etat = f"champ published « {publication} »"
        elif (publication or "").upper() == "NOT YET" and str(
            entree.get("status") or ""
        ).strip().upper() == "EVIDENCE":
            statut = PENDING
            etat = "champs published « NOT YET » et status « EVIDENCE »"

        info = _clean(str(entree.get("info") or ""))
        volume_brut = _clean(str(entree.get("volume") or ""))
        volume = volume_brut if volume_brut and volume_brut != "~" else None
        contexte = " ".join(
            partie
            for partie in (
                (
                    f"Chiffre d'affaires annoncé : {entree['revenue']}"
                    if entree.get("revenue")
                    else ""
                ),
                (
                    f"Effectif annoncé : {entree['employees']}"
                    if entree.get("employees")
                    else ""
                ),
                f"Action : {entree['action']}" if entree.get("action") else "",
                (
                    f"Date d'attaque annoncée : {entree['actionDate']}"
                    if entree.get("actionDate")
                    else ""
                ),
            )
            if partie
        )
        victims.append(
            DlsVictim(
                name=name,
                site=_normalise_site(str(entree.get("url") or ""))
                or _site_si_domaine(name),
                published_at=date_publication,
                volume=volume or _parse_volume(f"{info or ''} {volume_brut or ''}"),
                detail_url=None,
                description=_clean(f"{info or ''} {contexte}".strip()),
                publication_status=statut,
                publication_evidence=etat,
            )
        )
    return victims


def parse_deadlock(html: str, base_url: str) -> list[DlsVictim]:
    """DEADLOCK : un `div.post` par victime, 10 par page.

    `div.post-title` porte le nom, `p.post-text` la description, `span.badge`
    le statut, et `a.pg` la pagination (relevee le 2026-10-08 :
    `?page=0` a `?page=10`, donc ~110 victimes).

    ⚠️ LE STATUT SE LIT SUR LA CLASSE DU BADGE, PAS SUR SON TEXTE. Le badge
    affiche soit `Published` (classe `badge pub`), soit
    `Publishes after: 6d 0h 47m` -- un COMPTE A REBOURS, qui change a chaque
    consultation. Reprendre ce texte dans la description ferait varier le
    `content_hash` et recreerait la victime a chaque passage : c'est le defaut
    ORION (111 documents pour 12 victimes), par un autre chemin. On
    n'enregistre donc que le fait, « publication annoncee », jamais le
    decompte.

    ⚠️ Ce site ne publie NI date de publication NI site web de la victime.
    `published_at` reste None -- la fraicheur retombe alors sur
    `COALESCE(published_at, fetched_at)`, comportement voulu pour une source
    qui ne date rien. Le domaine de la victime, quand il apparait, est DANS
    le texte de la description (mesure : `web.mobilier-exemple.co.za` en page 1) :
    raison de plus pour conserver celle-ci entiere.
    """
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for post in soup.select("div.post"):
        title = post.select_one(".post-title")
        name = _clean(title.get_text()) if title else None
        if not name:
            continue
        texte = post.select_one("p.post-text")
        description = _clean(texte.get_text(" ")) if texte else None
        badge = post.select_one("span.badge")
        classes = badge.get("class") or [] if badge is not None else []
        if "pub" in classes:
            statut, etat = PUBLISHED, "badge « Published »"
        elif badge is not None:
            statut, etat = PENDING, "badge de publication à venir"
        else:
            statut, etat = None, None
        victims.append(
            DlsVictim(
                name=name,
                site=_site_si_domaine(name),
                published_at=None,
                volume=_parse_volume(description or ""),
                detail_url=None,
                description=description,
                publication_status=statut,
                publication_evidence=etat,
            )
        )
    return victims


def parse_arcusmedia(html: str, base_url: str) -> list[DlsVictim]:
    """ARCUS MEDIA : un blog WordPress, un `article.post` par victime (50 sur
    l'accueil, releve du 2026-10-08).

    `h2.entry-title a` porte le nom ET le lien de detail (`/?p=822`),
    `div.entry-summary` l'extrait.

    ⚠️ DEUX `<time>` COHABITENT dans le meme bloc : `time.entry-date.published`
    (publication) et `time.updated` (derniere retouche). Prendre le premier
    `<time>` venu daterait certaines victimes de leur modification -- meme
    famille que la date d'INSCRIPTION DE L'AUTEUR sur Dread, qui aurait date
    tous les fils pareil. Le selecteur est donc explicite.

    ⚠️ Le statut vient de la CATEGORIE portee par l'article
    (`category-leaked`, `category-new`). `leaked` dit que les donnees sont en
    ligne ; `new` est une etiquette de FRAICHEUR, pas une declaration de
    publication -- elle laisse donc le statut INCONNU plutot que de supposer
    « en attente ». Deviner ici reviendrait a inventer un fait affiche a
    l'analyste.
    """
    soup = BeautifulSoup(html, "html.parser")
    victims: list[DlsVictim] = []

    for article in soup.select("article.post"):
        lien = article.select_one("h2.entry-title a")
        name = _clean(lien.get_text()) if lien is not None else None
        if not name:
            continue
        moment = article.select_one("time.entry-date.published")
        publiee = None
        if moment is not None:
            brut = moment.get("datetime") or moment.get("content") or ""
            try:
                publiee = datetime.fromisoformat(str(brut).replace("Z", "+00:00"))
            except ValueError:
                publiee = None
            if publiee is not None and publiee.tzinfo is None:
                publiee = publiee.replace(tzinfo=timezone.utc)
        classes = [str(c).lower() for c in (article.get("class") or [])]
        if "category-leaked" in classes:
            statut, etat = PUBLISHED, "catégorie « LEAKED »"
        else:
            statut, etat = None, None
        resume = article.select_one("div.entry-summary")
        description = _clean(resume.get_text(" ")) if resume is not None else None
        href = lien.get("href") if lien is not None else None
        victims.append(
            DlsVictim(
                name=name,
                site=_site_si_domaine(name),
                published_at=publiee,
                volume=_parse_volume(description or ""),
                detail_url=urljoin(base_url, str(href)) if href else None,
                description=description,
                publication_status=statut,
                publication_evidence=etat,
            )
        )
    return victims


_PARSERS: dict[str, callable] = {
    "lockbit": parse_lockbit,
    "nspire": parse_nightspire,
    "beast": parse_beast,
    "i62huw": parse_insomnia,
    "bashe": parse_apt73,
    "payload": parse_payload,
    "ijzn3sic": parse_qilin,
    "sarcoma": parse_sarcoma,
    "direwolf": parse_direwolf,
    "metacrpt": parse_metaencrypter,
    "krybit": parse_krybit,
    # DRAGON FORCE a migre le 2026-09-04 : l'ancienne adresse ne sert plus
    # qu'un avis « Migration completed » signe PGP annoncant la nouvelle.
    # ⚠️ LES DEUX MARQUEURS SONT CONSERVES. Ne changer que l'URL en base
    # aurait fait retomber la source sur le collecteur generique -- le nouvel
    # hote etant absent d'ici -- soit une collecte « reussie » rendant UN blob
    # au lieu de 24 victimes, sans la moindre erreur. Meme piege que les
    # miroirs DARKNET ARMY.
    "z3wqggt": parse_dragonforce,  # ancienne adresse, gardee au cas ou
    "xjhmtit": parse_dragonforce,  # adresse en service depuis le 2026-09-04
    "safepay": parse_safepay,
    "cjfntkj": parse_orion,
    "mydatae": parse_mydata,
    "7ukmkdt": parse_daixin,
    "peargxn": parse_pear,
    "cmdnkiq": parse_cmd,
    # --- Ajoutes le 2026-10-08, apres mesure du rendement africain ---
    # Ces quatre gangs portent 21 des 173 victimes africaines des 12 derniers
    # mois (ransomware.live), qu'aucune de nos sources ne voyait. Les deux
    # premiers servent du JSON : leur hote est donc mappe quelle que soit la
    # route, et `listing_urls` construit le chemin de l'API.
    #
    # ⚠️ DEUX MARQUEURS POUR INC RANSOM, volontairement. `incbacg…` porte
    # l'API et `incblog…` le blog : ce sont deux adresses du meme gang, et le
    # piege du miroir s'est deja produit trois fois (DARKNET ARMY, DRAGON
    # FORCE). Mapper une seule adresse ferait retomber l'autre sur le
    # collecteur generique -- une collecte « reussie » rendant un blob, sans
    # la moindre erreur.
    "incbacg": parse_incransom,
    "incblog": parse_incransom,
    "zohlm7": parse_ransomhouse,
    "deadblog": parse_deadlock,
    "arcuufpr": parse_arcusmedia,
}


def pick_parser(url: str):
    """Retourne le parser adapte a cette URL, ou None si le site n'est pas
    encore supporte (l'appelant retombe alors sur le collecteur generique)."""
    # Hôte d'ORIGINE : une source déménagée garde son parser (host_aliases).
    host = canonical_host(urlparse(url).hostname)
    for marker, parser in _PARSERS.items():
        if marker in host:
            return parser
    return None


# Plafond de pages pour un DLS pagine. Borne le crawl : on veut la fraicheur
# incrementale, pas un rapatriement historique (regle 1 -- observation).
# CMD sert 6 victimes par page ; 10 pages couvrent 60 victimes pour un site
# qui en annonce 41. L'adapter s'arrete de toute facon des qu'une page ne
# rend plus de nouvelle victime.
_MAX_LISTING_PAGES = 10

# Taille de page imposee par CMD. NE PAS "optimiser" en demandant un
# per_page plus grand : mesure du 2026-08-25, le serveur IGNORE ce parametre
# et renvoie 6 quoi qu'on demande. Un `per_page=60` semblait fonctionner
# (aucune erreur, une page pleine) tout en perdant 35 victimes sur 41 --
# echec silencieux typique, du meme genre que le parser GitHub muet.
_CMD_PAGE_SIZE = 6

# INC RANSOM sert sa liste par une API JSON paginee : 30 victimes par page,
# 855 au total le 2026-10-08. On en lit 3 pages, soit les 90 victimes les plus
# recentes.
#
# ⚠️ C'EST UN PLAFOND ASSUME, PAS UN DEFAUT DE COUVERTURE. La doctrine est la
# fraicheur incrementale, pas le rapatriement historique (regle 1 --
# observation) : meme arbitrage que `DEFAULT_MAX_PAGES = 1` sur Dread. 90
# victimes couvrent tres largement ce qu'un gang publie entre deux passes.
# Le relacher impose de refaire la mesure du cout en requetes Tor.
#
# ⚠️ Contrairement a CMD, l'arret « plus de victime nouvelle » ne protege PAS
# ici : chaque page rend 30 entrees inedites (verifie). Le nombre de pages EST
# donc le nombre de requetes.
_INCRANSOM_PAGES = 3
_INCRANSOM_PAGE_SIZE = 30

# DEADLOCK pagine par `?page=N` a partir de ZERO (releve : `?page=0` a
# `?page=10`, 10 victimes par page). Trois pages = les 30 plus recentes.
_DEADLOCK_PAGES = 3


def _racine(url: str) -> str:
    """`http://hote.onion/un/chemin` -> `http://hote.onion`.

    Reconstruire depuis l'URL analysee plutot que de decouper la chaine : un
    `split("/a")` sur l'adresse de RansomHouse marcherait aujourd'hui et
    casserait au premier changement de chemin."""
    morceaux = urlparse(url)
    return f"{morceaux.scheme}://{morceaux.netloc}"


def listing_urls(url: str) -> list[str]:
    """URLs a recuperer pour obtenir la liste COMPLETE des victimes.

    La plupart des DLS servent tout sur la page d'accueil : on renvoie alors
    `[url]` et rien ne change.

    CMD ORGANIZATION fait exception, et de facon silencieuse : son accueil
    n'affiche que les 3 dernieres victimes sur 41 sans le moindre indice
    qu'il en manque 38. La liste complete vit sur `/items`, paginee par 6.
    L'appelant (adapter) s'arrete des qu'une page n'apporte plus rien, donc
    ces URLs sont un plafond, pas un nombre de requetes garanti."""
    host = canonical_host(urlparse(url).hostname)
    if "cmdnkiq" in host:
        base = url.rstrip("/")
        return [
            f"{base}/items?page={page}&per_page={_CMD_PAGE_SIZE}"
            f"&search=&sort=newest&filter=all"
            for page in range(1, _MAX_LISTING_PAGES + 1)
        ]
    # INC RANSOM et RANSOMHOUSE servent leur liste par une API JSON : le
    # chemin est construit ici, de sorte qu'une source declaree avec la seule
    # adresse du site fonctionne, et qu'un changement de miroir n'oblige pas a
    # reecrire l'URL stockee.
    if "incbacg" in host or "incblog" in host:
        base = _racine(url)
        return [
            f"{base}/api/v1/blog/get/announcements"
            f"?page={page}&perPage={_INCRANSOM_PAGE_SIZE}"
            for page in range(1, _INCRANSOM_PAGES + 1)
        ]
    if "zohlm7" in host:
        return [f"{_racine(url)}/a"]
    if "deadblog" in host:
        # Numerotation a partir de ZERO, relevee sur les liens `a.pg`.
        base = _racine(url)
        return [f"{base}/?page={page}" for page in range(_DEADLOCK_PAGES)]
    return [url]


def is_supported_dls_url(url: str) -> bool:
    return pick_parser(url) is not None


def parse_dls(html: str, base_url: str) -> list[DlsVictim]:
    """Extrait les victimes d'un DLS supporte. Liste vide si non supporte."""
    parser = pick_parser(base_url)
    if parser is None:
        return []
    return parser(html, base_url)


# Plafond de pages de detail recuperees par passe de collecte.
#
# Chaque page est une requete Tor supplementaire : le plafond borne le temps de
# la collecte, comme `DEFAULT_MAX_BODIES` cote Dread. 60 couvre largement une
# passe incrementale (un DLS publie rarement plus de quelques victimes par
# jour) tout en gardant la collecte sous quelques minutes.
DEFAULT_MAX_DETAIL_FETCHES = 60


def looks_truncated(description: str | None) -> bool:
    """La description issue de la LISTE est-elle un simple apercu ?

    Les sites de fuite affichent un extrait sur leur page d'accueil et le texte
    complet sur la page de la victime. Mesure du 2026-09-03 : **115 documents
    KRYBIT sur 115** se terminent par des points de suspension, 320 sur 494
    chez LOCKBIT. Le contenu stocke faisait 199 caracteres la ou la page de
    detail en contient 1788 -- neuf fois plus.
    """
    texte = (description or "").strip()
    if not texte:
        return True
    return texte.endswith("...") or texte.endswith("…") or len(texte) < 300


# Compteurs volatils affiches par les DLS dans leurs cartes de victime.
#
# ⚠️ MESURE DU 2026-09-04, ce n'est pas une precaution theorique. Ces
# compteurs changent a chaque consultation, donc le `content_hash` change,
# donc la deduplication exacte ne reconnait JAMAIS un document deja vu : la
# meme victime etait re-enregistree a chaque collecte. Constate en base :
# ORION 111 documents pour 12 victimes (x9,2), QILIN x2,0, KRYBIT x1,6.
# Aucune erreur, aucun signal -- la source paraissait simplement productive.
#
# Meme famille que le piege LockBit `data-timer` : un champ volatil au milieu
# d'un contenu stable.
# ⚠️ UN SEUL nombre, pas une suite de nombres separes par des espaces. Une
# premiere version acceptait `[\d\s.,]*` et avalait « Aug 30, 2026 5220 0
# photos » en entier -- la DATE partait avec le compteur. Attrape par un test
# temoin ; c'est exactement le risque de ce genre de nettoyage.
_NOMBRE = r"\d+(?:[.,]\d{3})*"
# ⚠️ `(?<![+-])` : sans lui, « Deadline ... UTC +0 Views: 97614 » voyait son
# DECALAGE HORAIRE avale (« UTC +n Views »). Le nombre qui precede l'etiquette
# doit etre autonome, pas la fin d'une autre valeur. Constate sur APT73 le
# 2026-09-04, une fois les pages de detail effectivement recuperees -- le
# defaut etait invisible tant que le contenu restait tronque.
_ETIQUETTES_COMPTEUR = r"views?|vues?|images?|photos?"
_COMPTEUR_ETIQUETE = re.compile(
    rf"(?<![+-]){_NOMBRE}\s*({_ETIQUETTES_COMPTEUR})\b", re.IGNORECASE
)
# ⚠️ LES DEUX SENS EXISTENT, et l'oublier casse la deduplication en silence.
# KRYBIT ecrit « 79437 VIEWS » (nombre puis etiquette), APT73 « Views: 97614 »
# (etiquette puis nombre). Le second n'etait pas couvert : le compteur variait
# donc a chaque consultation et APT73 recreait ses documents indefiniment --
# le meme defaut que celui corrige sur ORION, reapparu par un autre chemin des
# que les pages de detail ont ete recuperees.
_COMPTEUR_ETIQUETE_INVERSE = re.compile(
    rf"\b({_ETIQUETTES_COMPTEUR})\s*:?\s*{_NOMBRE}", re.IGNORECASE
)
# QILIN affiche « <vues> <images> photos » : le premier nombre n'a pas
# d'etiquette a lui, il ne se reconnait qu'a sa position.
_COMPTEURS_ADJACENTS = re.compile(
    rf"\b{_NOMBRE}\s+(?={_NOMBRE}\s*(?:images?|photos?)\b)", re.IGNORECASE
)
# Compte a rebours avant publication, volatil par nature. Les gangs l'ecrivent
# chacun a leur facon -- KRYBIT « 32h 00m 00s », QILIN « Time till publication:
# 43h : 36m » -- d'ou un motif par SUITE d'unites plutot qu'un format fige.
#
# ⚠️ Deux unites au minimum. Un nombre isole suivi d'une lettre d'unite est
# trop courant dans une description pour etre efface sans risque ; une suite
# « 43h : 36m » ne peut etre qu'un decompte.
_UNITE_DUREE = r"\d{1,4}\s*(?:d|j|h|m|s)\b"
_COMPTE_A_REBOURS = re.compile(
    rf"{_UNITE_DUREE}(?:\s*:?\s*{_UNITE_DUREE})+", re.IGNORECASE
)


def neutraliser_compteurs(texte: str) -> str:
    """Remplace les compteurs volatils par un marqueur stable.

    ⚠️ Ne retire QUE des nombres d'affichage (vues, images, compte a rebours).
    Un volume annonce (« 400 GB »), une date ou un domaine ne portent pas ces
    etiquettes et restent intacts : ce sont eux qui portent le renseignement.
    """
    if not texte:
        return texte
    # ⚠️ L'ORDRE COMPTE, et se tromper casse silencieusement la deduplication.
    # Le compte a rebours PASSE EN PREMIER : sinon le motif « etiquette puis
    # nombre » lit le « 00 » de « IMAGES 00m 00s » comme le compteur d'images,
    # coupe le decompte en deux et laisse « m 00s » varier a chaque
    # consultation. Attrape par un test qui a echoue sur KRYBIT.
    texte = _COMPTE_A_REBOURS.sub("compte a rebours", texte)
    texte = _COMPTEURS_ADJACENTS.sub("", texte)
    texte = _COMPTEUR_ETIQUETE.sub(r"n \1", texte)
    return _COMPTEUR_ETIQUETE_INVERSE.sub(r"\1 n", texte)


def extract_detail_text(html: str) -> str:
    """Texte lisible d'une page de victime.

    ⚠️ Extraction GENERIQUE, volontairement : contrairement aux listes, ou
    chaque gang code sa structure differemment et exige un parser dedie, la
    page de detail se reduit a un bloc de prose. On retire scripts et styles,
    puis on aplatit -- pas de selecteur devine, donc rien a maintenir par site.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for balise in soup(["script", "style", "noscript"]):
        balise.decompose()
    return " ".join(soup.get_text(" ").split())


# ⚠️ Nombre d'AUTRES victimes tolerees dans une page de detail. Mesure du
# 2026-09-15, et la separation est franche -- ce n'est pas un seuil arbitraire :
#   - pages de detail saines (PAYLOAD, DIRE WOLF, KRYBIT) : **0 autre victime**
#   - pages de liste servies a la place du detail (PAYLOAD) : **79 sur 83**
# 3 laisse la marge d'une mention fortuite sans jamais laisser passer une liste.
_MAX_AUTRES_VICTIMES = 3

# En deca, un nom est trop court pour qu'une correspondance en sous-chaine soit
# fiable (« Robinsons », « In.Sa.Cor »). Meme prudence que les frontieres de mot
# du classifieur d'annonces.
_LONGUEUR_NOM_FIABLE = 7


def detail_page_is_about(texte: str, nom_victime: str, autres_noms) -> bool:
    """La page de detail recuperee parle-t-elle bien de CETTE victime ?

    ⚠️ REMPLACE UN GARDE-FOU QUI NE GARDAIT RIEN. L'ancien test etait
    « la page de detail apporte-t-elle PLUS de texte que l'apercu ? » -- son
    commentaire annoncait pourtant l'intention juste (« certaines redirigent
    vers la liste »). Mais une page de LISTE apporte toujours plus de texte :
    le critere choisissait donc systematiquement le pire cas.

    Degat mesure le 2026-09-15 : **24 des 83 documents PAYLOAD** portaient la
    page entiere (~32 700 caracteres, toutes les victimes) au lieu de leur
    propre victime (~370 caracteres). Les 24 ne contenaient que **2 corps
    distincts**. Cause : le site sert la meme page pour chaque `/posts/<uuid>`
    et repartit cote navigateur -- l'URL par victime etait pourtant correcte.

    Consequence silencieuse : tout attribut derive du texte (categorie de
    donnees fuitees, volume, date) etait attribue a la MAUVAISE organisation.
    « the majority of the leaked data consists of customer information » se
    lisait sur tissage-exemple.com alors que la phrase parle de TFE Group.

    ⚠️ Ne PAS revenir a un critere de TAILLE : la page de detail de
    « Exemple Pet Health » (DIRE WOLF) depasse 20 000 caracteres et est
    parfaitement legitime -- elle ne cite aucune autre victime. La taille ne
    distingue pas une page riche d'une page de liste ; le nombre d'autres
    victimes citees, oui.

    ⚠️ ON NE VERIFIE PAS QUE LA PAGE NOMME SA VICTIME -- deux versions
    successives l'ont tente, la mesure a tranche contre.
      1. Titre exigé en sous-chaine : **29 descriptions correctes** du corpus
         ne le contiennent pas (BEAST 14, CMD 10, PAYLOAD 4, DAIXIN 1), pour
         des ecarts cosmetiques (« T Exemple Jewelers » vs « T. Simon
         Jewelers », « Bluewater Health (CA) » vs « Bluewater Health »).
      2. Jetons normalises, donc tolerant aux variantes : **714 rejets** sur
         le corpus reel, dont des contenus parfaitement valides. Cause de
         fond : un site de fuite TITRE par le domaine et DECRIT par la raison
         sociale -- `imagerie-exemple.com` est decrit comme « German Imaging
         Technologies (GIT) Dubai LLC », `design-exemple.com.au` comme
         « Intoto ». Aucun rapprochement lexical ne peut combler cet ecart,
         et c'est la meme realite que celle mesuree pour la corroboration
         (« la plupart des gangs publient des raisons sociales, pas des
         domaines »).
    Le SEUL critere qui separe proprement est donc le comptage des AUTRES
    victimes : 0 sur les pages saines, 79 sur les pages de liste.

    ⚠️ Ma premiere mesure de ce critere etait CIRCULAIRE : elle cherchait le
    titre dans le contenu STOCKE, lequel commence par « Victime annoncee:
    <titre> » -- il s'y trouvait par construction. Toujours mesurer sur le
    texte RECUPERE.
    """
    if not texte:
        return False
    autres = 0
    for autre in autres_noms:
        if not autre or len(autre) <= _LONGUEUR_NOM_FIABLE:
            continue
        # ⚠️ Les noms IMBRIQUES designent la meme organisation, pas une autre
        # victime. Constate sur ORION : « Orion RAAS Group » cohabite avec
        # « Orion RAAS », et une simple inegalite comptait 10 « autres
        # victimes » sur une page parfaitement specifique.
        if autre in nom_victime or nom_victime in autre:
            continue
        if autre in texte:
            autres += 1
            if autres > _MAX_AUTRES_VICTIMES:
                return False
    return True
