# Archived: Python / rdflib validation engine

This folder preserves the pre–triple-store validation implementation.

## What was archived

`validate_kg.py` (snapshot) implemented:

- **R1–R4, R6** as in-memory Python graph traversals on an `rdflib.Graph`
- **R5, R5B** via local `rdflib` SPARQL (`graph.query`)
- Optional dual mode (`KG_VALIDATION_ENGINE=python|sparql`) before SPARQL-only became the default

## Why it was archived

The paper’s focus is graph-query / SPARQL validation on a triple store with a query
optimizer. The Python runners existed only because `rdflib` SPARQL was too slow on
the full BPI Domestic Declarations graph; they are not the evaluation target.

## Do not use for new experiments

Current validation lives in `src/validate_kg.py` and always runs pure SPARQL against
a configured SPARQL 1.1 endpoint (see root README: Triple-store validation).
