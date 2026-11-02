"""Tri des documents par FRAICHEUR REELLE (repositories/document_repo.py).

Le bug constate le 2026-08-27 sur AKIRA : la liste commencait par des
victimes de **2023** alors que la source publie tous les jours. Cause : le
tri portait sur `fetched_at`, or tout le corpus avait ete collecte en une
passe -- les `fetched_at` ne differaient que de microsecondes, l'ordre obtenu
etait donc celui d'insertion (l'ordre des blocs sur la page du site).

Le correctif trie sur `COALESCE(published_at, fetched_at)` : la vraie date
quand elle existe, la date de decouverte sinon. Ces tests verrouillent les
deux moities -- sans le COALESCE, les 25 % de documents sans date (KRYBIT,
NIGHT SPIRE, APT73... sont a 0 %) disparaitraient en fin de liste."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.db.session import SessionLocal
from app.repositories.document_repo import (
    DocumentSortBy,
    RawDocumentRepository,
    SortOrder,
)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_source(db) -> Source:
    source = Source(
        id=uuid.uuid4(),
        name="Test source (ordering)",
        type="onion",
        url=f"http://test-{uuid.uuid4().hex}.onion",
        active=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(source)
    db.commit()
    return source


def _make_document(
    db, source, *, title, published_at, fetched_at, announcement_class=None
) -> RawDocument:
    document = RawDocument(
        id=uuid.uuid4(),
        source_id=source.id,
        url=f"http://test.onion/{uuid.uuid4().hex}",
        title=title,
        content="contenu",
        content_hash=uuid.uuid4().hex,
        fetched_at=fetched_at,
        published_at=published_at,
        source_type="onion",
        collector="test",
        collector_version="1",
        is_duplicate=False,
        announcement_class=announcement_class,
    )
    db.add(document)
    db.commit()
    return document


class TestFreshnessOrdering:
    def test_recent_publication_comes_first(self, db):
        """Le cas AKIRA : une passe de collecte unique, des dates de
        publication tres ecartees. C'est la publication qui doit primer."""
        source = _make_source(db)
        # Meme seconde de collecte pour les deux -- comme dans une vraie passe.
        collected = datetime(2026, 8, 26, 18, 40, tzinfo=timezone.utc)
        try:
            _make_document(
                db,
                source,
                title="vieille victime 2023",
                published_at=datetime(2023, 5, 15, tzinfo=timezone.utc),
                fetched_at=collected + timedelta(microseconds=500),
            )
            _make_document(
                db,
                source,
                title="victime recente 2026",
                published_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
                fetched_at=collected,
            )

            docs = RawDocumentRepository(db).list_all(
                source_id=source.id, sort_by=DocumentSortBy.FRESHNESS
            )
            assert [d.title for d in docs] == [
                "victime recente 2026",
                "vieille victime 2023",
            ]
        finally:
            db.query(RawDocument).filter(RawDocument.source_id == source.id).delete()
            db.query(Source).filter(Source.id == source.id).delete()
            db.commit()

    def test_undated_document_uses_fetched_at_and_stays_visible(self, db):
        """25 % du corpus n'a pas de `published_at`, et des sources entieres
        sont a 0 % (KRYBIT, NIGHT SPIRE, APT73). Avec un tri `nullslast` sur
        published_at seul, elles disparaitraient toutes en fin de liste : le
        COALESCE les classe a leur date de decouverte."""
        source = _make_source(db)
        try:
            _make_document(
                db,
                source,
                title="datee mais ancienne",
                published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
            )
            _make_document(
                db,
                source,
                title="sans date, collectee aujourd'hui",
                published_at=None,
                fetched_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
            )

            docs = RawDocumentRepository(db).list_all(
                source_id=source.id, sort_by=DocumentSortBy.FRESHNESS
            )
            assert docs[0].title == "sans date, collectee aujourd'hui"
        finally:
            db.query(RawDocument).filter(RawDocument.source_id == source.id).delete()
            db.query(Source).filter(Source.id == source.id).delete()
            db.commit()

    def test_ascending_order_is_supported(self, db):
        source = _make_source(db)
        try:
            _make_document(
                db,
                source,
                title="ancienne",
                published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
            )
            _make_document(
                db,
                source,
                title="recente",
                published_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
            )
            docs = RawDocumentRepository(db).list_all(
                source_id=source.id,
                sort_by=DocumentSortBy.FRESHNESS,
                sort_order=SortOrder.ASC,
            )
            assert [d.title for d in docs] == ["ancienne", "recente"]
        finally:
            db.query(RawDocument).filter(RawDocument.source_id == source.id).delete()
            db.query(Source).filter(Source.id == source.id).delete()
            db.commit()


class TestRelevanceStillPrioritisesWatchlist:
    """Le tri « pertinence » garde la watchlist en tete -- on n'a change que
    son critere secondaire (fetched_at -> fraicheur reelle)."""

    def test_matched_document_comes_first_even_if_older(self, db):
        source = _make_source(db)
        try:
            recent = _make_document(
                db,
                source,
                title="recente sans mot-cle",
                published_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
            )
            matched = _make_document(
                db,
                source,
                title="ancienne AVEC mot-cle",
                published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
            )
            matched.matched_keywords = ["acme"]
            db.commit()
            assert recent.id is not None

            docs = RawDocumentRepository(db).list_all(
                source_id=source.id, sort_by=DocumentSortBy.RELEVANCE
            )
            assert docs[0].title == "ancienne AVEC mot-cle"
        finally:
            db.query(RawDocument).filter(RawDocument.source_id == source.id).delete()
            db.query(Source).filter(Source.id == source.id).delete()
            db.commit()


class TestListForSourceOrdering:
    """`list_for_source` alimente le panneau d'une source : meme regle."""

    def test_orders_by_freshness(self, db):
        source = _make_source(db)
        try:
            _make_document(
                db,
                source,
                title="2023",
                published_at=datetime(2023, 5, 15, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 8, 26, 18, 40, tzinfo=timezone.utc),
            )
            _make_document(
                db,
                source,
                title="2026",
                published_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 8, 26, 18, 39, tzinfo=timezone.utc),
            )
            docs = RawDocumentRepository(db).list_for_source(source.id)
            assert [d.title for d in docs] == ["2026", "2023"]
        finally:
            db.query(RawDocument).filter(RawDocument.source_id == source.id).delete()
            db.query(Source).filter(Source.id == source.id).delete()
            db.commit()


class TestAnnouncementClassFilter:
    """Le verdict du classifieur etait calcule et persiste depuis le
    2026-08-28, mais aucune couche ne l'exploitait : l'analyste voyait une
    publicite de service (« iCLOUD UNLOCK ») exactement comme une annonce de
    fuite. Signale a l'usage le 2026-09-02.

    Le filtre est pousse EN SQL, pas applique apres coup : la liste est
    paginee, ecarter en memoire fausserait le total et les pages."""

    def test_filters_and_keeps_the_total_consistent(self, db):
        source = _make_source(db)
        now = datetime.now(timezone.utc)
        for cls in ("leak", "uncertain", "noise"):
            _make_document(
                db,
                source,
                title=f"doc {cls}",
                published_at=now,
                fetched_at=now,
                announcement_class=cls,
            )
        try:
            repo = RawDocumentRepository(db)
            retenus = repo.list_all(
                limit=50,
                source_id=source.id,
                announcement_classes=["leak", "uncertain"],
            )
            assert {d.announcement_class for d in retenus} == {"leak", "uncertain"}
            # Le total doit suivre le filtre, sinon la pagination annonce plus
            # de documents qu'elle n'en sert.
            assert (
                repo.count_all(
                    source_id=source.id, announcement_classes=["leak", "uncertain"]
                )
                == 2
            )
            assert repo.count_all(source_id=source.id) == 3
        finally:
            db.query(RawDocument).filter(RawDocument.source_id == source.id).delete()
            db.query(Source).filter(Source.id == source.id).delete()
            db.commit()

    def test_uncertain_is_never_hidden_with_noise(self, db):
        """`uncertain` n'est pas un demi-bruit : c'est ce que les regles n'ont
        pas su trancher. Le confondre avec le bruit perdrait des victimes -- la
        raison meme pour laquelle cette classe existe."""
        source = _make_source(db)
        now = datetime.now(timezone.utc)
        doc = _make_document(
            db,
            source,
            title="ni l'un ni l'autre",
            published_at=now,
            fetched_at=now,
            announcement_class="uncertain",
        )
        try:
            repo = RawDocumentRepository(db)
            retenus = repo.list_all(
                limit=50,
                source_id=source.id,
                announcement_classes=["leak", "uncertain"],
            )
            assert [d.id for d in retenus] == [doc.id]
        finally:
            db.query(RawDocument).filter(RawDocument.source_id == source.id).delete()
            db.query(Source).filter(Source.id == source.id).delete()
            db.commit()
