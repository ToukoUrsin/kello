# Kello on Fly.io: the API and the built web app in one small image. Built by deploy/fly.sh.
# Ships data/processed, data/model, data/evidence, science/out and the stored plans, checks, scouts
# and reads (app/server/cache). Never data/raw, .venv, node_modules, science/.session or film/
# (.dockerignore allows only what is named there).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /srv/kello

COPY requirements.txt .
# pytest is for the repo, not the server. Chromium and Xvfb are what "Read a report" renders web pages with.
RUN grep -v '^pytest' requirements.txt > /tmp/req.txt && pip install -r /tmp/req.txt \
    && apt-get update && apt-get install -y --no-install-recommends xvfb libatomic1 \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /tmp/req.txt

COPY model ./model
COPY data ./data
COPY science ./science
COPY app/server ./app/server
COPY deploy/dist ./app/web/dist
COPY deploy/start.sh ./deploy/start.sh

# KELLO_HOSTED: this copy serves stored Claude-written plans; the web check and
# scout use Gemini, and a failed live run answers with the stored result.
ENV PORT=8080 KELLO_HOSTED=1
EXPOSE 8080
CMD ["bash", "deploy/start.sh"]
