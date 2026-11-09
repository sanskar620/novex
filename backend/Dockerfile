FROM python:3.11-slim

# System dependencies for GDAL, rasterio, geopandas, pyproj
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -e .

# Copy backend code
COPY . .

# Run database migrations and generate demo data on startup
RUN python -c "from app.db.base import Base; from app.db.session import engine; Base.metadata.create_all(bind=engine)"

EXPOSE 8000

# Start server using dynamic PORT environment variable (supports Render, Railway, Fly.io)
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port \${PORT:-8000}"

