FROM python:3.12-slim

WORKDIR /app

# Use Tsinghua mirror for apt
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list

# curl_cffi needs C compiler at build time
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Use Tsinghua mirror for pip
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# Install Python deps (server + sidecar)
COPY requirements.txt ./
COPY sidecars/chatgpt_pool/requirements.txt ./sidecar-reqs.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r sidecar-reqs.txt && \
    rm requirements.txt sidecar-reqs.txt

# Copy source code
COPY backend/ backend/
COPY sidecars/ sidecars/
COPY frontend/ frontend/
COPY prompt_skills/ prompt_skills/
COPY static/ static/
COPY workflows/ workflows/
COPY server.py ./
COPY docker/settings.docker.json ./
COPY docker/docker-entrypoint.sh /usr/local/bin/
COPY docker/sidecar-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/sidecar-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
