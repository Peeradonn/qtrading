# One bot per container. The EC2 deployment uses deploy/setup_ec2.sh (a venv under systemd) instead; this image
# exists so a judge can run the bot anywhere with the same code and the same commit hash in its journal.
#
#   docker build -t qtrading .
#   docker run --env-file .env -v "$PWD/data:/app/data" -v "$PWD/logs:/app/logs" qtrading configs/paper-eqvt3.toml
#
FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY scripts ./scripts
COPY configs ./configs
COPY data/snapshots ./data/snapshots
COPY .git ./.git

ENTRYPOINT ["python", "scripts/run_bot.py", "--config"]
CMD ["configs/eqvt3.toml"]
