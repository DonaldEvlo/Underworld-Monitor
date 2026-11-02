import logging
from dataclasses import replace
from datetime import date, datetime, timezone

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceContract
from app.pipeline.collect.base import Collector
from app.pipeline.collect.dls.scraper import (
    detail_page_is_about,
    DEFAULT_MAX_DETAIL_FETCHES,
    extract_detail_text,
    looks_truncated,
    DlsVictim,
    is_supported_dls_url,
    listing_urls,
    neutraliser_compteurs,
    parse_dls,
)
from app.pipeline.collect.link_extraction import extract_mentioned_urls
from app.pipeline.collect.publication_status import status_fields
from app.pipeline.collect.page_diagnosis import diagnostiquer_page

logger = logging.getLogger(__name__)


class DlsCollectionError(RuntimeError):
    """Collecte DLS sans resultat, avec le MOTIF reel.

    Rendre `[]` faisait afficher « source injoignable ou vide » a l'analyste,
    quel que soit le cas : site demenage, anti-bot, structure modifiee. Trois
    situations aux suites tres differentes.
    """


class DlsCollector(Collector):
    """Collecteur des Data Leak Sites de gangs ransomware (voir scraper.py).

    Un `RawDocumentContract` par VICTIME, pas un blob par site : chaque
    organisation nommee est une unite d'alerte distincte, avec sa date et son
    volume -- meme principe que RansomLookCollector et AkiraCollector. Le
    collecteur generique produisait un document unique pour les 508 victimes
    de LockBit, ce qui rendait impossible une alerte par organisation.

    Le fetch HTML est injecte par l'appelant (`html_fetcher`) plutot que
    realise ici : cela garde ce module purement logique donc testable sans
    reseau, et laisse le choix du transport (requests via Tor, Playwright pour
    les sites a rendu JS) a la couche qui sait lequel s'applique."""

    COLLECTOR_NAME = "dls"
    COLLECTOR_VERSION = "1"

    def __init__(self, html_fetcher) -> None:
        self._fetch = html_fetcher

    def collect(self, source: SourceContract) -> list[RawDocumentContract]:
        url = str(source.url)
        if not is_supported_dls_url(url):
            logger.warning("DLS: aucun parser pour %s", url)
            return []

        # La plupart des DLS tiennent sur une page ; CMD pagine sa liste
        # (voir listing_urls). Une page en echec ne doit pas faire perdre
        # les autres : on journalise et on continue.
        victims: list[DlsVictim] = []
        seen: set[str] = set()
        # Conserve la PREMIERE page servie : si aucune victime n'en sort, c'est
        # elle qui dira pourquoi (deménagement, anti-bot, structure changee).
        premiere_page: str | None = None
        for page_url in listing_urls(url):
            try:
                html = self._fetch(page_url)
            except Exception:
                logger.exception("DLS: echec de recuperation de %s", page_url)
                continue
            if premiere_page is None:
                premiere_page = html
            if not html:
                continue
            try:
                page_victims = parse_dls(html, page_url)
            except Exception:
                logger.exception("DLS: echec du parsing de %s", page_url)
                continue
            # Une pagination qui deborde ne renvoie PAS une page vide : CMD
            # re-sert la derniere page a l'identique (mesure du 2026-08-25,
            # page 8 = page 7). On s'arrete donc sur "aucune victime
            # NOUVELLE", pas sur "page vide" -- sinon on boucle jusqu'au
            # plafond en rechargeant la meme page.
            added = 0
            for victim in page_victims:
                key = f"{victim.name}|{victim.site or ''}"
                if key in seen:
                    continue
                seen.add(key)
                victims.append(victim)
                added += 1
            if added == 0:
                break

        if not victims:
            # ⚠️ Ne PAS rendre une liste vide en silence. « 0 victime » et
            # « site injoignable » remontaient jusqu'ici sous le meme message,
            # alors que DRAGON FORCE avait demenage (correction en une minute)
            # et XSSF exigeait un CAPTCHA (non contournable). L'exception porte
            # le motif reel jusqu'a l'interface.
            raise DlsCollectionError(diagnostiquer_page(premiere_page))

        # ⚠️ Completer les descriptions TRONQUEES depuis la page de la victime.
        #
        # La liste n'affiche qu'un apercu : mesure du 2026-09-03, 115 documents
        # KRYBIT sur 115 se terminaient par des points de suspension, et le
        # contenu stocke faisait 199 caracteres la ou la page de detail en
        # contient 1788. On avait pourtant l'URL de cette page depuis le debut.
        #
        # Borne par `DEFAULT_MAX_DETAIL_FETCHES` : chaque page est une requete
        # Tor de plus. Une page en echec laisse simplement l'apercu en place --
        # une description courte vaut mieux qu'une victime perdue.
        victims = self._completer_descriptions(victims)

        # Construction protegee par victime : une entree malformee ne doit pas
        # faire perdre les 507 autres (meme lecon que xssf/adapter.py).
        documents: list[RawDocumentContract] = []
        for victim in victims:
            try:
                documents.append(self._build_document_for(source, victim))
            except Exception:
                logger.exception(
                    "DLS: victime ignoree (%s) sur %s", victim.name[:40], url
                )
        logger.info("DLS %s: %d victime(s)", source.name, len(documents))
        return documents

    def _completer_descriptions(
        self, victims: list[DlsVictim], *, rotation: int | None = None
    ) -> list[DlsVictim]:
        """Remplace l'apercu par le texte de la page de la victime.

        `DlsVictim` est `frozen` : on reconstruit plutot que de muter, ce qui
        garde le parsing pur et rend cette etape sans effet de bord.

        ⚠️ LE BUDGET TOURNE D'UNE PASSE A L'AUTRE. Sans rotation, les memes
        `DEFAULT_MAX_DETAIL_FETCHES` premieres victimes etaient completees a
        chaque cycle et les suivantes JAMAIS -- l'apercu de la LISTE reste
        tronque quoi qu'on ait deja en base, le compteur repartait donc
        toujours du debut.

        Mesure du 2026-09-04 sur APT73 : deux passes successives ont rendu
        **0 nouveau document** et laisse **112 documents tronques sur 252**,
        figes. Ce n'etait pas « une progression par vagues » comme je l'avais
        d'abord annonce : c'etait un plafond definitif sur 60 victimes.

        La rotation depend du JOUR : le cout reseau par passe est inchange,
        mais l'ensemble des victimes finit couvert en quelques cycles.
        `rotation` est injectable pour rendre le comportement testable.
        """
        if rotation is None:
            rotation = date.today().toordinal() * DEFAULT_MAX_DETAIL_FETCHES
        depart = rotation % len(victims) if victims else 0
        # On parcourt en anneau a partir de `depart`, puis on restitue l'ordre
        # d'origine : l'ordre des documents produits ne doit pas dependre du
        # jour.
        ordre = list(range(depart, len(victims))) + list(range(depart))

        # Calcule UNE fois : sert a reconnaitre une page de liste servie a la
        # place d'une page de detail.
        noms_des_victimes = [v.name for v in victims if v.name]

        recuperees = 0
        completees: dict[int, DlsVictim] = {}
        for index in ordre:
            victim = victims[index]
            if (
                recuperees >= DEFAULT_MAX_DETAIL_FETCHES
                or not victim.detail_url
                or not looks_truncated(victim.description)
            ):
                completees[index] = victim
                continue
            try:
                html = self._fetch(victim.detail_url)
            except Exception:
                logger.exception(
                    "DLS: page de detail illisible pour %s", victim.name[:40]
                )
                completees[index] = victim
                continue
            recuperees += 1
            texte = extract_detail_text(html)
            # ⚠️ La page recuperee doit parler de CETTE victime -- voir
            # `detail_page_is_about`. L'ancien test (« apporte plus de texte »)
            # choisissait systematiquement la page de LISTE quand le site en
            # servait une : 24 des 83 documents PAYLOAD portaient les 83
            # victimes au lieu d'une seule, et tout attribut derive du texte
            # etait attribue a la mauvaise organisation.
            if not detail_page_is_about(texte, victim.name, noms_des_victimes):
                logger.warning(
                    "DLS: page de detail non specifique a %s -- apercu conserve",
                    victim.name[:40],
                )
                completees[index] = victim
                continue
            # A ce stade la page est bien la sienne : on ne remplace que si
            # elle apporte davantage que l'apercu.
            if len(texte) > len(victim.description or ""):
                victim = replace(victim, description=texte)
            completees[index] = victim
        if recuperees:
            logger.info("DLS: %d description(s) completee(s)", recuperees)
        return [completees[i] for i in range(len(victims))]

    def _build_document_for(
        self, source: SourceContract, victim: DlsVictim
    ) -> RawDocumentContract:
        parts = [f"Victime annoncee: {victim.name}"]
        if victim.site:
            parts.append(f"Site: {victim.site}")
        if victim.volume:
            parts.append(f"Volume annonce: {victim.volume}")
        if victim.description:
            # ⚠️ Point de passage UNIQUE pour neutraliser les compteurs de
            # vues. Sans cela le `content_hash` change a chaque consultation et
            # la deduplication exacte ne reconnait jamais un document deja vu :
            # ORION avait 111 documents pour 12 victimes (mesure 2026-09-04).
            parts.append(f"\n{neutraliser_compteurs(victim.description)}")

        content = "\n".join(parts)

        # `link_extraction` reste PASSIF : il extrait les URLs sans jamais les
        # requeter (CONTRIBUTING.md §8). Le site de la victime en fait partie -- il
        # sera verifie, si besoin, par la passe `link_health` separee.
        doc_url = (
            victim.detail_url or f"{str(source.url).rstrip('/')}#{_slug(victim.name)}"
        )
        mentioned = extract_mentioned_urls(content, exclude_url=doc_url)

        meta: dict = {"victim_name": victim.name}
        if victim.site:
            meta["victim_site"] = victim.site
        if victim.volume:
            meta["announced_volume"] = victim.volume
        if mentioned:
            meta["mentioned_urls"] = mentioned
        # ⚠️ Dans `source_meta`, JAMAIS dans `content` : le statut change
        # (« SOON » -> « PUBLISHED ») et changerait le `content_hash`, donc
        # recreerait le document a chaque bascule. Voir publication_status.py.
        meta.update(
            status_fields(
                victim.publication_status,
                victim.publication_evidence,
                datetime.now(timezone.utc).isoformat(),
            )
        )

        return self._build_document(
            source,
            doc_url,
            content,
            title=victim.name,
            published_at=victim.published_at,
            source_meta=meta,
        )


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")[:60]
