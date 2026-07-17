FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir fastapi uvicorn[standard] markdown gitpython jinja2

# Copy app
COPY . .

# Keep seed wiki content in a separate dir so we can restore it on fresh volumes
RUN mkdir -p /app/seed_wiki && cp -r /app/wiki/* /app/seed_wiki/ 2>/dev/null; true

# Volume for persistent wiki content
VOLUME /app/wiki

# Start
CMD ["python", "-c", "from wiki_app import main; main()"]