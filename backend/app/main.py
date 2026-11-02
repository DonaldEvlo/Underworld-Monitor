from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    exports,
    gold,
    lookup,
    schedules,
    alerts,
    auth,
    detections,
    documents,
    dread,
    entities,
    health,
    links,
    llm,
    passwords,
    perimeter,
    search,
    sources,
    stats,
    telegram,
    users,
    source_addresses,
    watchlist,
)
from app.core.config import settings, verifier_secrets
from app.core.logging import setup_logging

setup_logging()
verifier_secrets(settings)

# Alias d'hôtes des sources déménagées (voir pipeline/collect/host_aliases.py) :
# la collecte lancée depuis l'API doit garder le parser dédié d'une source
# dont l'adresse a basculé.
from app.services.source_address_service import installer_alias  # noqa: E402

installer_alias()

app = FastAPI(
    title="Underworld Monitor API",
    version="0.1.0",
    description=(
        "API de la plateforme de threat intelligence : gestion des sources, "
        "déclenchement de collecte, sélection du modèle LLM d'analyse, watchlist "
        "de mots-clés surveillés."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # ⚠️ `Content-Disposition` n'est PAS lisible par defaut depuis le
    # navigateur : il ne fait pas partie des en-tetes de reponse exposes
    # d'office en CORS. Sans cette ligne, un telechargement (rapport PDF,
    # export CSV) recoit bien le fichier mais pas le nom propose par le
    # serveur -- l'analyste se retrouve avec un identifiant technique en guise
    # de nom de fichier. Constate a l'usage.
    expose_headers=["Content-Disposition"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(source_addresses.router)
app.include_router(sources.router)
app.include_router(documents.router)
app.include_router(detections.router)
app.include_router(llm.router)
app.include_router(watchlist.router)
app.include_router(users.router)
app.include_router(search.router)
app.include_router(dread.router)
app.include_router(entities.router)
app.include_router(stats.router)
app.include_router(alerts.router)
app.include_router(links.router)
app.include_router(passwords.router)
app.include_router(schedules.router)
app.include_router(lookup.router)
app.include_router(exports.router)
app.include_router(gold.router)
app.include_router(telegram.router)
app.include_router(perimeter.router)
