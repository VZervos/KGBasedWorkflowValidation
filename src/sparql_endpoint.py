"""SPARQL 1.1 client for remote triple stores (Fuseki, GraphDB, Blazegraph, …).

Turtle is bulk-loaded via the Graph Store Protocol; rule SELECTs go to the query endpoint.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests


class SparqlEndpointError(RuntimeError):
    """Raised when a SPARQL / Graph Store HTTP call fails."""


def _infer_sibling(query_url: str, suffix: str) -> str:
    """Map .../sparql or .../query → .../<suffix>."""
    base = query_url.rstrip("/")
    for ending in ("/sparql", "/query"):
        if base.endswith(ending):
            return base[: -len(ending)] + "/" + suffix
    return base.rsplit("/", 1)[0] + "/" + suffix


@dataclass(frozen=True)
class SparqlEndpointConfig:
    query_endpoint: str
    update_endpoint: str
    gsp_endpoint: str
    username: str | None = None
    password: str | None = None
    timeout_seconds: float = 3600.0

    @classmethod
    def from_env(cls) -> "SparqlEndpointConfig":
        query = (os.environ.get("KG_SPARQL_QUERY_ENDPOINT") or "").strip()
        if not query:
            raise SparqlEndpointError(
                "KG_SPARQL_QUERY_ENDPOINT is not set. Example for Fuseki:\n"
                "  KG_SPARQL_QUERY_ENDPOINT=http://localhost:3030/ds/sparql\n"
                "  KG_SPARQL_UPDATE_ENDPOINT=http://localhost:3030/ds/update\n"
                "  KG_SPARQL_GSP_ENDPOINT=http://localhost:3030/ds/data\n"
                "Start a local store with: docker compose -f docker-compose.fuseki.yml up -d"
            )
        update = (os.environ.get("KG_SPARQL_UPDATE_ENDPOINT") or "").strip() or _infer_sibling(
            query, "update"
        )
        gsp = (os.environ.get("KG_SPARQL_GSP_ENDPOINT") or "").strip() or _infer_sibling(
            query, "data"
        )
        user = (os.environ.get("KG_SPARQL_USER") or "").strip() or None
        password = os.environ.get("KG_SPARQL_PASSWORD") or None
        if password == "":
            password = None
        timeout_raw = (os.environ.get("KG_SPARQL_TIMEOUT_SECONDS") or "").strip()
        timeout = float(timeout_raw) if timeout_raw else 3600.0
        return cls(
            query_endpoint=query,
            update_endpoint=update,
            gsp_endpoint=gsp,
            username=user,
            password=password,
            timeout_seconds=timeout,
        )


class SparqlEndpoint:
    """SPARQL Query / Update + Graph Store Protocol client."""

    def __init__(self, config: SparqlEndpointConfig | None = None) -> None:
        self.config = config or SparqlEndpointConfig.from_env()
        self._session = requests.Session()
        if self.config.username is not None:
            self._session.auth = (self.config.username, self.config.password or "")

    def _raise(self, action: str, response: requests.Response) -> None:
        raise SparqlEndpointError(
            f"{action} failed ({response.status_code}): {response.text[:800]}"
        )

    def select(self, query: str) -> list[dict[str, str]]:
        """Run a SELECT query; return rows as {var: lexical_value}."""
        response = self._session.post(
            self.config.query_endpoint,
            data={"query": query},
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=self.config.timeout_seconds,
        )
        if response.status_code >= 400:
            self._raise("SPARQL SELECT", response)
        payload = response.json()
        rows: list[dict[str, str]] = []
        for binding in payload.get("results", {}).get("bindings", []):
            rows.append({name: str(cell.get("value", "")) for name, cell in binding.items()})
        return rows

    def update(self, update: str) -> None:
        response = self._session.post(
            self.config.update_endpoint,
            data={"update": update},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.config.timeout_seconds,
        )
        if response.status_code >= 400:
            self._raise("SPARQL UPDATE", response)

    def clear(self) -> None:
        """Remove triples (ALL, else DEFAULT)."""
        try:
            self.update("CLEAR ALL")
        except SparqlEndpointError:
            self.update("CLEAR DEFAULT")

    def load_turtle(self, turtle_path: Path) -> None:
        """Replace store contents with the given Turtle file (CLEAR + GSP upload)."""
        path = Path(turtle_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        data = path.read_bytes()
        self.clear()
        # Prefer PUT (replace default graph). Fall back to POST after CLEAR.
        response = self._session.put(
            self.config.gsp_endpoint,
            data=data,
            headers={"Content-Type": "text/turtle"},
            timeout=self.config.timeout_seconds,
        )
        if response.status_code < 400:
            return
        response = self._session.post(
            self.config.gsp_endpoint,
            data=data,
            headers={"Content-Type": "text/turtle"},
            timeout=self.config.timeout_seconds,
        )
        if response.status_code >= 400:
            self._raise("Graph Store load", response)

    def ping(self) -> dict[str, Any]:
        """Cheap connectivity check."""
        rows = self.select("SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }")
        count = int(rows[0]["c"]) if rows and "c" in rows[0] else 0
        return {
            "query_endpoint": self.config.query_endpoint,
            "update_endpoint": self.config.update_endpoint,
            "gsp_endpoint": self.config.gsp_endpoint,
            "triple_count": count,
        }


def default_fuseki_base(port: int = 3030, dataset: str = "ds") -> str:
    return f"http://localhost:{port}/{dataset}"


def suggest_fuseki_env(base: str | None = None) -> dict[str, str]:
    root = (base or default_fuseki_base()).rstrip("/")
    return {
        "KG_SPARQL_QUERY_ENDPOINT": urljoin(root + "/", "sparql"),
        "KG_SPARQL_UPDATE_ENDPOINT": urljoin(root + "/", "update"),
        "KG_SPARQL_GSP_ENDPOINT": urljoin(root + "/", "data"),
        "KG_SPARQL_USER": "admin",
        "KG_SPARQL_PASSWORD": "admin",
    }
