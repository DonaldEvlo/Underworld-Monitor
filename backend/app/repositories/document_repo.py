from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.contracts.raw_document import RawDocumentContract
from app.db.models.raw_document import RawDocument
from app.pipeline.detect.announcement_filter import (
    classify_announcement,
    source_publishes_victims,
)
from app.pipeline.collect.publication_status import (
    STATUS_KEY,
    merge_publication_status,
)
from app.pipeline.detect.keyword_match import find_keyword_matches
from app.pipeline.detect.registry import detect_all
from app.pipeline.process.clean import clean_text
from app.pipeline.process.dedup import compute_simhash, is_near_duplicate
from app.pipeline.process.lang import detect_language
from app.repositories.detection_repo import DetectionRepository


class DocumentSortBy(str, Enum):
    RELEVANCE = (
        "relevance"  # watchlist en tete, puis fraicheur (voir _freshness_column)
    )
    FETCHED_AT = "fetched_at"
    PUBLISHED_AT = "published_at"
    TITLE = "title"
    # Fraicheur reelle : date de publication quand elle existe, date de
    # collecte sinon (voir _freshness_column). C'est le defaut de l'interface.
    FRESHNESS = "freshness"


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class RawDocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, id: uuid.UUID) -> RawDocument | None:
        return self.db.get(RawDocument, id)

    def list_for_source(
        self, source_id: uuid.UUID, limit: int = 100
    ) -> list[RawDocument]:
        return list(
            self.db.query(RawDocument)
            .filter(RawDocument.source_id == source_id)
            # Fraicheur reelle, pas ordre d'insertion : voir
            # _freshness_column (sur AKIRA, fetched_at remontait 2023 en tete).
            .order_by(
                func.coalesce(RawDocument.published_at, RawDocument.fetched_at).desc()
            )
            .limit(limit)
            .all()
        )

    def list_by_ids(
        self, document_ids: list[uuid.UUID], offset: int = 0, limit: int = 50
    ) -> list[RawDocument]:
        """Documents identifies par une liste d'ids deja connue (typiquement
        les document_id de detections matchant une entite, voir
        api/routers/entities.py::list_entity_documents) -- pas de logique de
        matching ici, juste un fetch pagine, trie par fraicheur decroissante
        comme list_for_source (voir _freshness_column)."""
        if not document_ids:
            return []
        return list(
            self.db.query(RawDocument)
            .filter(RawDocument.id.in_(document_ids))
            .order_by(
                func.coalesce(RawDocument.published_at, RawDocument.fetched_at).desc()
            )
            .offset(offset)
            .limit(limit)
            .all()
        )

    def _filtered_query(
        self,
        source_id: uuid.UUID | None,
        collector: str | None,
        search: str | None,
        only_matched: bool = False,
        fetched_from: datetime | None = None,
        fetched_to: datetime | None = None,
        announcement_classes: list[str] | None = None,
    ):
        query = self.db.query(RawDocument)
        if source_id is not None:
            query = query.filter(RawDocument.source_id == source_id)
        if collector is not None:
            query = query.filter(RawDocument.collector == collector)
        if search:
            like = f"%{search}%"
            query = query.filter(
                (RawDocument.title.ilike(like)) | (RawDocument.content.ilike(like))
            )
        if only_matched:
            query = query.filter(RawDocument.matched_keywords.isnot(None))
        if fetched_from is not None:
            query = query.filter(RawDocument.fetched_at >= fetched_from)
        if fetched_to is not None:
            query = query.filter(RawDocument.fetched_at <= fetched_to)
        # Verdict du classifieur d'annonces (voir
        # detect/announcement_filter.py). Il etait calcule et persiste, mais
        # aucune couche ne l'exploitait : l'analyste voyait donc une publicite
        # de service exactement comme une annonce de fuite -- signale a
        # l'usage le 2026-09-02. Filtrer EN SQL, pas apres coup : la liste est
        # paginee, ecarter en memoire fausserait le total et les pages.
        if announcement_classes:
            query = query.filter(
                RawDocument.announcement_class.in_(announcement_classes)
            )
        return query

    @staticmethod
    def _freshness_column():
        """Fraicheur reelle d'un document : sa date de PUBLICATION quand elle
        est connue, sa date de collecte sinon.

        ⚠️ Trier sur `fetched_at` seul n'ordonne rien d'utile. Constate le
        2026-08-27 : tout le corpus a ete collecte sur 2 jours, les
        `fetched_at` d'une meme passe ne different que de microsecondes --
        l'ordre obtenu est donc celui d'insertion, c'est-a-dire l'ordre des
        blocs sur la page du site. Sur AKIRA, cela remontait des victimes de
        **2023** en tete alors que la source publie tous les jours.

        ⚠️ Trier sur `published_at` seul ne marche pas non plus : **25 % du
        corpus n'a pas de date** et plusieurs sources sont a 0 % (KRYBIT,
        NIGHT SPIRE, APT73, CMD, DRAGON FORCE...). Avec `nullslast`, ces
        sources disparaitraient toutes en fin de liste.

        Le COALESCE resout les deux : une victime datee est classee sur sa
        vraie date, une victime sans date reste visible a sa date de
        decouverte."""
        return func.coalesce(RawDocument.published_at, RawDocument.fetched_at)

    def _apply_sort(self, query, sort_by: DocumentSortBy, sort_order: SortOrder):
        # nullslast systematique sur published_at/title : une valeur absente
        # (frequent pour published_at, voir contrat RawDocumentContract) ne
        # doit jamais se retrouver en tete d'un tri, quel que soit l'ordre.
        if sort_by == DocumentSortBy.RELEVANCE:
            return query.order_by(
                RawDocument.matched_keywords.isnot(None).desc(),
                self._freshness_column().desc(),
            )
        if sort_by == DocumentSortBy.FRESHNESS:
            column = self._freshness_column()
            return query.order_by(
                column.asc() if sort_order == SortOrder.ASC else column.desc()
            )
        if sort_by == DocumentSortBy.PUBLISHED_AT:
            column = RawDocument.published_at
        elif sort_by == DocumentSortBy.TITLE:
            column = RawDocument.title
        else:
            column = RawDocument.fetched_at

        ordered = column.asc() if sort_order == SortOrder.ASC else column.desc()
        if sort_by in (DocumentSortBy.PUBLISHED_AT, DocumentSortBy.TITLE):
            ordered = ordered.nullslast()
        return query.order_by(ordered)

    def list_all(
        self,
        offset: int = 0,
        limit: int = 50,
        source_id: uuid.UUID | None = None,
        collector: str | None = None,
        search: str | None = None,
        only_matched: bool = False,
        fetched_from: datetime | None = None,
        fetched_to: datetime | None = None,
        sort_by: DocumentSortBy = DocumentSortBy.RELEVANCE,
        sort_order: SortOrder = SortOrder.DESC,
        announcement_classes: list[str] | None = None,
    ) -> list[RawDocument]:
        query = self._filtered_query(
            source_id,
            collector,
            search,
            only_matched,
            fetched_from,
            fetched_to,
            announcement_classes,
        )
        query = self._apply_sort(query, sort_by, sort_order)
        return list(query.offset(offset).limit(limit).all())

    def count_all(
        self,
        source_id: uuid.UUID | None = None,
        collector: str | None = None,
        search: str | None = None,
        only_matched: bool = False,
        fetched_from: datetime | None = None,
        fetched_to: datetime | None = None,
        announcement_classes: list[str] | None = None,
    ) -> int:
        return self._filtered_query(
            source_id,
            collector,
            search,
            only_matched,
            fetched_from,
            fetched_to,
            announcement_classes,
        ).count()

    def delete_all(self) -> tuple[int, int]:
        """Supprime tous les documents collectes ainsi que leurs detections
        (contrainte de cle etrangere detections.document_id -> raw_documents.id :
        les documents ne peuvent pas etre supprimes tant que leurs detections
        existent encore -- une detection n'a pas de sens sans le document
        qu'elle qualifie). Les sources et keywords restent intacts -- seule
        la base de collecte est videe.

        Retourne (documents_supprimes, detections_supprimees)."""
        deleted_detections = DetectionRepository(self.db).delete_all()
        deleted_documents = self.db.query(RawDocument).count()
        self.db.query(RawDocument).delete()
        self.db.commit()
        return deleted_documents, deleted_detections

    def existing_hashes_for_source(self, source_id: uuid.UUID) -> set[str]:
        rows = (
            self.db.query(RawDocument.content_hash)
            .filter(RawDocument.source_id == source_id)
            .all()
        )
        return {content_hash for (content_hash,) in rows}

    def existing_simhashes_for_source(self, source_id: uuid.UUID) -> list[int]:
        rows = (
            self.db.query(RawDocument.simhash)
            .filter(RawDocument.source_id == source_id, RawDocument.simhash.isnot(None))
            .all()
        )
        return [simhash for (simhash,) in rows if simhash is not None]

    def _to_model(
        self,
        doc: RawDocumentContract,
        cleaned_content: str,
        matched_keywords: list[str] | None,
        simhash: int | None,
        language: str | None,
        is_duplicate: bool,
    ) -> RawDocument:
        return RawDocument(
            id=doc.id,
            source_id=doc.source_id,
            url=doc.url,
            content=cleaned_content,
            content_hash=doc.content_hash,
            fetched_at=doc.fetched_at,
            source_type=doc.source_type.value,
            collector=doc.collector,
            collector_version=doc.collector_version,
            published_at=doc.published_at,
            title=doc.title,
            author=doc.author,
            raw_html=doc.raw_html,
            source_meta=doc.source_meta,
            simhash=simhash,
            language=language,
            is_duplicate=is_duplicate,
            matched_keywords=matched_keywords or None,
        )

    def save_new_documents(
        self,
        source_id: uuid.UUID,
        documents: list[RawDocumentContract],
        watchlist_terms: list[str] | None = None,
    ) -> list[RawDocument]:
        """Persiste uniquement les documents dont le `content_hash` n'existe pas
        deja pour cette source (dedup exacte -- un re-fetch d'une source qui n'a
        pas change ne doit pas dupliquer les lignes), puis passe chaque document
        restant par la couche process (voir pipeline/process/) avant ecriture :
        - clean_text : `content` stocke est la version nettoyee (images markdown
          residuelles, espaces normalises) -- raw_html garde la trace brute.
        - detect_language : langue detectee sur le texte nettoye.
        - compute_simhash + is_near_duplicate : marque `is_duplicate` si un
          document deja connu pour cette source est quasi-identique (repost
          avec titre/horodatage different) -- la dedup exacte par content_hash
          ne les detecte pas (hash totalement different pour un octet pres).
        - detect_all (voir pipeline/detect/registry.py) : patterns PII (email,
          card, iban, crypto_wallet) sur le texte nettoye, persistes a part
          (voir DetectionRepository) -- jamais de valeur brute, uniquement
          value_masked/value_hash (regle non negociable, voir CONTRIBUTING.md).

        `watchlist_terms`, si fourni, calcule et fige `matched_keywords` par
        document au moment de l'ecriture (precurseur simple de detect, voir
        keyword_match.py) -- pas recalcule a chaque lecture."""
        if not documents:
            return []

        existing_hashes = self.existing_hashes_for_source(source_id)
        existing_simhashes = self.existing_simhashes_for_source(source_id)
        # Deduit du collecteur plutot que demande a l'appelant : un seul
        # endroit a maintenir, aucun risque d'oubli dans un routeur ou une
        # tache Celery (voir announcement_filter.VICTIM_PUBLISHING_COLLECTORS).
        publishes_victims = source_publishes_victims(
            documents[0].collector if documents else None
        )
        rows = []
        pending_detections = []
        deja_connus: list[RawDocumentContract] = []
        for doc in documents:
            if doc.content_hash in existing_hashes:
                deja_connus.append(doc)
                continue

            cleaned_content = clean_text(doc.content)
            simhash = compute_simhash(cleaned_content)
            is_duplicate = simhash is not None and is_near_duplicate(
                simhash, existing_simhashes
            )
            language = detect_language(cleaned_content)

            # Classification AVANT la detection : un forum generaliste melange
            # des annonces de fuite reelles avec des tutoriels, de l'entraide
            # et des jeux pirates (20 a 96 % de bruit selon la source, mesure
            # du 2026-08-28). Le verdict est persiste pour que l'interface et
            # le calcul de gravite puissent l'exploiter.
            #
            # `source_publishes_victims` est decisif : sur un site de fuite,
            # un document EST une victime et son titre n'est souvent qu'une
            # raison sociale nue. Sans ce drapeau, 18 % de ces documents
            # etaient ecartes a tort.
            classification = classify_announcement(
                doc.title,
                cleaned_content,
                source_publishes_victims=publishes_victims,
            )

            # Un document hors perimetre ne doit pas alimenter la watchlist :
            # c'est elle qui porte `is_relevant`, donc la gravite. Un
            # tutoriel citant une organisation surveillee ne constitue pas
            # une fuite la concernant.
            matches = (
                find_keyword_matches(cleaned_content, watchlist_terms)
                if watchlist_terms and classification.is_actionable
                else None
            )

            model = self._to_model(
                doc, cleaned_content, matches, simhash, language, is_duplicate
            )
            model.announcement_class = classification.verdict.value
            model.announcement_score = classification.score
            model.announcement_reason = classification.reason[:255]
            model.content_truncated = classification.content_truncated
            rows.append(model)
            # Les liens sortants sont deja extraits par la couche collect
            # (source_meta["mentioned_urls"], voir collect/link_extraction.py)
            # -- les passer a detect_all plutot que de les re-parser depuis le
            # texte, voir patterns/distribution.py.
            mentioned_urls = (doc.source_meta or {}).get("mentioned_urls")
            pending_detections.extend(
                detect_all(
                    cleaned_content,
                    doc.id,
                    is_relevant=bool(matches),
                    mentioned_urls=(
                        mentioned_urls if isinstance(mentioned_urls, list) else None
                    ),
                )
            )
            existing_hashes.add(doc.content_hash)
            if simhash is not None:
                existing_simhashes.append(simhash)

        if rows:
            self.db.add_all(rows)
            self.db.commit()
            DetectionRepository(self.db).save_all(pending_detections)
        self.refresh_publication_status(source_id, deja_connus)
        return rows

    def refresh_publication_status(
        self, source_id: uuid.UUID, documents: list[RawDocumentContract]
    ) -> int:
        """Met a jour le statut de publication des documents DEJA connus.

        La deduplication ne reecrit jamais un document existant ; or le statut
        d'une victime change (« en attente » -> « publiee ») sans que son texte
        change forcement (LockBit : le compte a rebours n'est pas dans le
        texte). Seules les cles de statut de `source_meta` sont touchees, et
        seulement en cas de changement -- voir
        `pipeline/collect/publication_status.merge_publication_status`.

        Rend le nombre de documents mis a jour."""
        observes = {
            doc.content_hash: doc.source_meta
            for doc in documents
            if (doc.source_meta or {}).get(STATUS_KEY)
        }
        if not observes:
            return 0
        maintenant = datetime.now(timezone.utc).isoformat()
        modifies = 0
        existants = (
            self.db.query(RawDocument)
            .filter(
                RawDocument.source_id == source_id,
                RawDocument.content_hash.in_(list(observes)),
            )
            .all()
        )
        for existant in existants:
            nouveau = merge_publication_status(
                existant.source_meta, observes.get(existant.content_hash), maintenant
            )
            if nouveau is not None:
                # Nouveau dict assigne, pas une mutation en place : JSONB sans
                # MutableDict ne detecterait pas la modification.
                existant.source_meta = nouveau
                modifies += 1
        if modifies:
            self.db.commit()
        return modifies
