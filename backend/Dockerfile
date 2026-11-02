FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Dépendances système : build tools + libs navigateur (Patchright/Chrome, pour le
# scraping clearnet). Le proxy Tor tourne dans son propre conteneur (`tor`) —
# aucun paquet Tor nécessaire ici.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    curl \
    build-essential \
    python3-dev \
    libffi-dev \
    procps \
    libglib2.0-0 \
    libnspr4 \
    libnss3 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libcairo2 \
    libpango-1.0-0 \
    libasound2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
# ⚠️ CACHE pip CONSERVÉ ENTRE LES CONSTRUCTIONS (2026-10-06). Avec
# `--no-cache-dir`, chaque tentative retéléchargeait tout, torch compris
# (192 Mo) : sur une connexion à ~500 ko/s, deux reconstructions ont échoué
# après 20 puis 65 minutes (DNS interne, puis un fichier corrompu refusé par
# la vérification d'empreinte de pip). Le cache est un montage de
# construction : il n'entre pas dans l'image.
# Trois étapes distinctes : un échec du navigateur ou du modèle spaCy ne fait
# plus refaire l'installation pip.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 120 --retries 10 -r requirements-dev.txt
RUN patchright install --with-deps chrome
RUN python -m spacy download en_core_web_sm

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
