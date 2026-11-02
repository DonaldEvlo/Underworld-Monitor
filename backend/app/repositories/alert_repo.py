from __future__ import annotations

import builtins

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.models.alert import Alert, AlertDetection
from app.db.models.detection import Detection
from app.db.models.entity import Entity
from app.pipeline.alerting.matching import normalize_victim

# Ordre de lecture d'un analyste : le plus grave d'abord. Même ordre que
# `parGraviteEtFraicheur` côté interface.
_RANG_GRAVITE = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class AlertRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, id: uuid.UUID) -> Alert | None:
        return (
            self.db.query(Alert)
            .options(joinedload(Alert.detections))
            .filter(Alert.id == id)
            .first()
        )

    def get_by_region_victim_and_date(
        self, region: str, victim_key: str, alert_date: date
    ) -> Alert | None:
        """Equivalent de `get_by_entity_and_date` pour une alerte regionale.
        L'unicite est (region, victime, jour) depuis la migration 0032 -- une
        alerte par VICTIME -- garantie par un index partiel : un UNIQUE
        ordinaire ne contraindrait rien, `entity_id` etant NULL sur ces
        lignes."""
        return (
            self.db.query(Alert)
            .options(joinedload(Alert.detections))
            .filter(
                Alert.region == region,
                Alert.victim_key == victim_key,
                Alert.alert_date == alert_date,
            )
            .first()
        )

    def alerted_detection_ids_for_region(self, region: str) -> set[uuid.UUID]:
        """Detections deja rattachees a une alerte de cette region, tous jours
        confondus -- meme role que `alerted_detection_ids` pour une entite :
        ne pas re-alerter sur un incident deja signale."""
        rows = (
            self.db.query(AlertDetection.detection_id)
            .join(Alert, Alert.id == AlertDetection.alert_id)
            .filter(Alert.region == region)
            .all()
        )
        return {row[0] for row in rows}

    def alerted_victims(
        self,
        *,
        entity_id: uuid.UUID | None = None,
        region: str | None = None,
        before: date | None = None,
    ) -> set[str]:
        """Victimes deja signalees pour ce sujet, sous forme normalisee.

        ⚠️ Complete `alerted_detection_ids`, qui ne dedoublonne que par
        IDENTIFIANT de detection. Or une meme victime est souvent redetectee :
        mesure du 2026-09-02 -- **279 victimes ont plusieurs detections et 103
        sont publiees par plusieurs sources**. `transports-exemple.com` parait
        chez KRYBIT ET chez NIGHT SPIRE : deux detections distinctes, donc deux
        alertes pour un seul et meme incident.

        Dedoublonner sur la VALEUR ferme ce cas. Un analyste qui veut malgre
        tout etre re-sollicite dispose du rappel explicite (voir
        api/routers/alerts.py::remind), qui ne cree pas de doublon.

        ⚠️ `before` exclut le jour courant, et cette nuance est essentielle :
        dedoublonner sans elle empecherait une detection PLUS GRAVE de la meme
        victime d'elever l'alerte du jour. Or apprendre en fin de journee
        qu'une victime deja signalee est corroboree doit se voir. On bloque
        donc la RE-alerte d'un jour a l'autre, pas l'enrichissement du jour
        meme.
        """
        query = (
            self.db.query(Detection.value_masked)
            .join(AlertDetection, AlertDetection.detection_id == Detection.id)
            .join(Alert, Alert.id == AlertDetection.alert_id)
        )
        if entity_id is not None:
            query = query.filter(Alert.entity_id == entity_id)
        elif region is not None:
            query = query.filter(Alert.region == region)
        else:
            return set()
        if before is not None:
            query = query.filter(Alert.alert_date < before)
        return {normalize_victim(row[0]) for row in query.all() if row[0]}

    def get_by_entity_and_date(
        self, entity_id: uuid.UUID, alert_date: date
    ) -> Alert | None:
        """Recherche d'idempotence : une seule alerte par (entite, jour), voir
        services/alert_service.py et la contrainte unique en base (migration
        0011)."""
        return (
            self.db.query(Alert)
            .options(joinedload(Alert.detections))
            .filter(Alert.entity_id == entity_id, Alert.alert_date == alert_date)
            .first()
        )

    def _filtre(
        self,
        query,
        status: str | None,
        entity_id: uuid.UUID | None,
        severities: Sequence[str] | None,
        alert_date: date | None,
        group_id: uuid.UUID | None = None,
    ):
        """Criteres communs a `list` et `count`.

        ⚠️ Factorise pour que les deux ne puissent pas diverger : un total
        calcule sur d'autres criteres que la page servie afficherait « 42
        alertes » au-dessus de 3 lignes -- le meme defaut que le filtre
        `announcement_class` des documents, corrige le 2026-09-02.
        """
        if status is not None:
            query = query.filter(Alert.status == status)
        if entity_id is not None:
            query = query.filter(Alert.entity_id == entity_id)
        if severities:
            query = query.filter(Alert.severity.in_(list(severities)))
        if alert_date is not None:
            query = query.filter(Alert.alert_date == alert_date)
        if group_id is not None:
            # Le groupe ET ses filiales : la vue du RSSI du siege (2026-10-05).
            filiales = select(Entity.id).where(Entity.parent_id == group_id)
            query = query.filter(
                or_(Alert.entity_id == group_id, Alert.entity_id.in_(filiales))
            )
        return query

    def list(
        self,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        entity_id: uuid.UUID | None = None,
        severities: Sequence[str] | None = None,
        alert_date: date | None = None,
        group_id: uuid.UUID | None = None,
    ) -> builtins.list[Alert]:
        query = self._filtre(
            self.db.query(Alert).options(joinedload(Alert.detections)),
            status,
            entity_id,
            severities,
            alert_date,
            group_id,
        )
        # ⚠️ Gravité d'abord, fraîcheur ensuite, AVANT la pagination. Trier
        # après coup dans la page (ce que faisait l'interface) laissait une
        # alerte CRITIQUE ancienne en page 2 dès que 25 alertes plus récentes
        # existaient -- constaté le 2026-10-01 sur Compagnie Aérienne Exemple.
        rang = case(_RANG_GRAVITE, value=Alert.severity, else_=len(_RANG_GRAVITE))
        return list(
            query.order_by(rang, Alert.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count(
        self,
        status: str | None = None,
        entity_id: uuid.UUID | None = None,
        severities: Sequence[str] | None = None,
        alert_date: date | None = None,
        group_id: uuid.UUID | None = None,
    ) -> int:
        return self._filtre(
            self.db.query(Alert), status, entity_id, severities, alert_date, group_id
        ).count()

    def dates_disponibles(self, limit: int = 30) -> builtins.list[date]:
        """Jours qui portent au moins une alerte, du plus recent au plus ancien.

        Sert a proposer un choix de journee REEL plutot qu'un calendrier libre
        ou l'analyste tomberait sur des jours vides sans savoir lesquels sont
        peuplés.
        """
        rows = (
            self.db.query(Alert.alert_date)
            .distinct()
            .order_by(Alert.alert_date.desc())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]

    def create(self, alert: Alert) -> Alert:
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        return alert

    def update(self, alert: Alert) -> Alert:
        """Persiste les modifications faites sur une instance deja attachee a
        la session (attributs assignes par l'appelant avant l'appel) -- meme
        patron que EntityRepository.update."""
        self.db.commit()
        self.db.refresh(alert)
        return alert

    def delete_all(self) -> int:
        """Supprime toutes les alertes ainsi que leurs rattachements
        (alert_detections -> alerts, cascade ORM deja en place via
        Alert.detections). Appele avant de vider detections (voir
        DetectionRepository.delete_all) -- la contrainte de cle etrangere
        alert_detections.detection_id interdit sinon la suppression des
        detections tant que des alertes les referencent encore."""
        count = self.db.query(Alert).count()
        self.db.query(AlertDetection).delete()
        self.db.query(Alert).delete()
        self.db.commit()
        return count

    def add_detections(
        self, alert: Alert, detection_ids: builtins.list[uuid.UUID]
    ) -> Alert:
        """Rattache de nouvelles detections a une alerte existante, en
        ignorant celles deja rattachees (voir contrainte unique
        alert_id+detection_id, migration 0011) -- permet a
        alert_service.py de re-scanner sans dupliquer lors d'une
        re-execution le meme jour."""
        already_linked = {ad.detection_id for ad in alert.detections}
        new_links = [
            AlertDetection(
                id=uuid.uuid4(), alert_id=alert.id, detection_id=detection_id
            )
            for detection_id in detection_ids
            if detection_id not in already_linked
        ]
        if new_links:
            self.db.add_all(new_links)
            self.db.commit()
            self.db.refresh(alert)
        return alert

    def alerted_detection_ids(self, entity_id: uuid.UUID) -> set[uuid.UUID]:
        """Detections deja rattachees a une alerte de cette entite, TOUS
        JOURS CONFONDUS.

        Sert a ne pas realerter sur un incident deja signale. Sans cela,
        `generate_alerts` recreait chaque jour une alerte pour les memes
        detections : l'unicite etant posee sur (entite, jour), le service
        etait idempotent DANS une journee mais pas ENTRE deux journees.
        Constate le 2026-08-29 : 120 alertes pour 30 organisations, soit un
        facteur 4 apres quatre jours, qui croissait d'une unite par jour.
        """
        rows = (
            self.db.query(AlertDetection.detection_id)
            .join(Alert, Alert.id == AlertDetection.alert_id)
            .filter(Alert.entity_id == entity_id)
            .all()
        )
        return {row[0] for row in rows}
