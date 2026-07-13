# Backend image for the VPS. CPU-only — no GPU needed to *run* the model
# (only training wanted one). This installs just what serving needs: the base
# package plus CPU torch and transformers. Training deps are left out to keep
# the image small.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch first, from PyTorch's CPU index. The default wheel pulls the
# multi-gigabyte CUDA build; this one is a fraction of the size and is all a
# CPU server can use anyway.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install the package. Copy only what the install needs first, so Docker can
# cache this layer and not reinstall on every code change.
COPY pyproject.toml ./
COPY deid ./deid
COPY service ./service
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir "transformers>=4.45"

EXPOSE 8000

# One worker: the model is loaded once into memory per worker, so more workers
# means more RAM. Start with one; add workers only if the VPS has the RAM.
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
