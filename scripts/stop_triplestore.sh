#!/usr/bin/env bash
# Stop Apache Jena Fuseki.
#
# Usage:
#   source scripts/stop_triplestore.sh
#   # or: bash scripts/stop_triplestore.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$ROOT/docker-compose.fuseki.yml"

echo "==> Stopping Fuseki..."
docker compose -f "$COMPOSE" down

unset KG_SPARQL_QUERY_ENDPOINT KG_SPARQL_UPDATE_ENDPOINT KG_SPARQL_GSP_ENDPOINT
unset KG_SPARQL_USER KG_SPARQL_PASSWORD

echo "==> Fuseki stopped."
