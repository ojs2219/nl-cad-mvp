FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1

# ── System packages ─────────────────────────────────────────────
# openscad: CAD → STL rendering
# xvfb: virtual display for headless OpenSCAD (Ubuntu 22.04 package)
# python3-pip: package installer
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
    && add-apt-repository ppa:openscad/releases \
    && apt-get update && apt-get install -y --no-install-recommends \
        openscad \
        xvfb \
        python3 \
        python3-pip \
        python3-setuptools \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ──────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# ── Application code ────────────────────────────────────────────
COPY . .

# Default static dir inside the container
RUN mkdir -p static/stl static/scad

# ── Startup script ───────────────────────────────────────────────
COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 8000

CMD ["/start.sh"]
