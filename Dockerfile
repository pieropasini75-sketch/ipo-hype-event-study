# Reproducible environment for the IPO hype event study.
#
#   docker build -t ipo-hype-event-study .
#   docker run --rm ipo-hype-event-study pytest
#   docker run --rm -v "$PWD/results:/app/results" -v "$PWD/data/prices:/app/data/prices" \
#       ipo-hype-event-study
#
# The two volumes keep the price cache and the results on your machine, so a
# second run reads cached prices instead of downloading them again.

# Same Python version the project was developed and tested with.
FROM python:3.15-slim

WORKDIR /app

# A C compiler: some pinned packages (arch) have no prebuilt wheel for Python 3.15.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first, in their own layer: they change rarely, so Docker reuses
# this layer and only re-copies the code when the code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY data/ipos.csv data/ipos_expanded.csv data/excluded.csv ./data/
COPY run_study.py build_sample.py ./
COPY tests ./tests

CMD ["python", "run_study.py"]
