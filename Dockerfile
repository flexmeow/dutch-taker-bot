FROM python:3.12

WORKDIR /app

# Copy source
COPY . .

# Install deps
RUN pip install uv && uv sync --no-dev --no-cache

# Ensure the project venv is on PATH
ENV PATH="/app/.venv/bin:${PATH}"

# Default entrypoint
ENTRYPOINT ["python", "-u", "-m", "bot"]
