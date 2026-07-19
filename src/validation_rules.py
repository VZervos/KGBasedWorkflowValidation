"""SPARQL validation rules for PROV-O workflow knowledge graphs.

Each rule exposes a SPARQL SELECT that returns one row per violation.
Additional rules can be appended to VALIDATION_RULES without changing the runner.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationRule:
    rule_id: str
    name: str
    description: str
    query: str


# R1: every activity must belong to exactly one case.
R1_ACTIVITY_BELONGS_TO_CASE = ValidationRule(
    rule_id="R1",
    name="ACTIVITY_BELONGS_TO_CASE",
    description=(
        "Every prov:Activity must have exactly one wf:belongsToCase link "
        "(integrity: each event belongs to exactly one case)."
    ),
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX wf: <http://kg.workflow.validation/>

        SELECT ?activity ?issue ?caseCount
        WHERE {
            {
                SELECT ?activity (COUNT(?case) AS ?caseCount)
                WHERE {
                    ?activity a prov:Activity .
                    OPTIONAL { ?activity wf:belongsToCase ?case }
                }
                GROUP BY ?activity
            }
            FILTER(?caseCount != 1)
            BIND(
                IF(?caseCount = 0, "missing_belongsToCase", "multiple_belongsToCase")
                AS ?issue
            )
        }
        ORDER BY ?activity
    """,
)


# R2: every activity must have a start timestamp.
R2_ACTIVITY_HAS_STARTED_AT_TIME = ValidationRule(
    rule_id="R2",
    name="ACTIVITY_HAS_STARTED_AT_TIME",
    description="Every prov:Activity must have prov:startedAtTime.",
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>

        SELECT ?activity ?issue
        WHERE {
            ?activity a prov:Activity .
            FILTER NOT EXISTS { ?activity prov:startedAtTime ?startedAtTime }
            BIND("missing_startedAtTime" AS ?issue)
        }
        ORDER BY ?activity
    """,
)


# R3: wasInformedBy must respect temporal order (earlier <= later).
R3_WAS_INFORMED_BY_TEMPORAL_CONSISTENCY = ValidationRule(
    rule_id="R3",
    name="WAS_INFORMED_BY_TEMPORAL_CONSISTENCY",
    description=(
        "If activity B prov:wasInformedBy activity A, then A.startedAtTime "
        "must be less than or equal to B.startedAtTime."
    ),
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>

        SELECT ?activity ?earlier ?earlierTime ?laterTime ?issue
        WHERE {
            ?activity prov:wasInformedBy ?earlier ;
                      prov:startedAtTime ?laterTime .
            ?earlier prov:startedAtTime ?earlierTime .
            FILTER(?laterTime < ?earlierTime)
            BIND("non_monotonic_wasInformedBy" AS ?issue)
        }
        ORDER BY ?activity
    """,
)


VALIDATION_RULES: tuple[ValidationRule, ...] = (
    R1_ACTIVITY_BELONGS_TO_CASE,
    R2_ACTIVITY_HAS_STARTED_AT_TIME,
    R3_WAS_INFORMED_BY_TEMPORAL_CONSISTENCY,
)
