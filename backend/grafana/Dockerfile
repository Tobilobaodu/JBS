# Production only — see prometheus/Dockerfile.prometheus for why
# provisioning is baked in rather than bind-mounted.
FROM grafana/grafana:latest
COPY datasources /etc/grafana/provisioning/datasources
COPY dashboards /etc/grafana/provisioning/dashboards
