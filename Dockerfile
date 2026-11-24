FROM python:3.12-slim
WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt
COPY pvcore pvcore
COPY probe probe
COPY server server
COPY data data
ENV PV_DB=/var/pv/prezzi_vicini.db
VOLUME /var/pv
EXPOSE 8000
CMD ["python", "-m", "server.cli", "serve"]
