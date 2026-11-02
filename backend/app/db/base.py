from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import des modèles pour qu'Alembic les détecte via Base.metadata.
from app.db.models import alert, alert_access, detection, entity, gold_annotation, keyword, raw_document, scheduled_task, source, source_address_change, user, user_session  # noqa: E402,F401  # fmt: skip
