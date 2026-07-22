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


# R3: every activity must be associated with an agent.
R3_ACTIVITY_HAS_AGENT = ValidationRule(
    rule_id="R3",
    name="ACTIVITY_HAS_AGENT",
    description="Every prov:Activity must have prov:wasAssociatedWith an agent.",
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>

        SELECT ?activity ?issue
        WHERE {
            ?activity a prov:Activity .
            FILTER NOT EXISTS { ?activity prov:wasAssociatedWith ?agent }
            BIND("missing_agent_association" AS ?issue)
        }
        ORDER BY ?activity
    """,
)


# R4: wasInformedBy must respect temporal order (and both sides need start times).
R4_WAS_INFORMED_BY_TEMPORAL_CONSISTENCY = ValidationRule(
    rule_id="R4",
    name="WAS_INFORMED_BY_TEMPORAL_CONSISTENCY",
    description=(
        "If activity B prov:wasInformedBy activity A, then both must have "
        "prov:startedAtTime and A.startedAtTime must be less than or equal "
        "to B.startedAtTime."
    ),
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>

        SELECT ?activity ?earlier ?earlierTime ?laterTime ?issue
        WHERE {
            {
                ?activity prov:wasInformedBy ?earlier ;
                          prov:startedAtTime ?laterTime .
                ?earlier prov:startedAtTime ?earlierTime .
                FILTER(?laterTime < ?earlierTime)
                BIND("non_monotonic_wasInformedBy" AS ?issue)
            }
            UNION
            {
                ?activity prov:wasInformedBy ?earlier .
                FILTER NOT EXISTS { ?activity prov:startedAtTime ?startedAtTime }
                OPTIONAL { ?earlier prov:startedAtTime ?earlierTime }
                BIND("missing_startedAtTime_on_informed_activity" AS ?issue)
            }
            UNION
            {
                ?activity prov:wasInformedBy ?earlier .
                FILTER NOT EXISTS { ?earlier prov:startedAtTime ?startedAtTime }
                OPTIONAL { ?activity prov:startedAtTime ?laterTime }
                BIND("missing_startedAtTime_on_informing_activity" AS ?issue)
            }
        }
        ORDER BY ?activity
    """,
)


# R5: payment handled must be performed by the system.
R5_PAYMENT_HANDLED_BY_SYSTEM = ValidationRule(
    rule_id="R5",
    name="PAYMENT_HANDLED_BY_SYSTEM",
    description=(
        "Every 'Payment Handled' activity must be associated with resource "
        "SYSTEM (xes-attr:org_resource)."
    ),
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX attr: <http://www.xes-standard.org/attribute/>

        SELECT ?activity ?resource ?issue
        WHERE {
            ?activity a prov:Activity ;
                      rdfs:label "Payment Handled" .
            FILTER NOT EXISTS { ?activity attr:xes-attr_org_resource "SYSTEM" }
            OPTIONAL { ?activity attr:xes-attr_org_resource ?resource }
            BIND("payment_not_handled_by_system" AS ?issue)
        }
        ORDER BY ?activity
    """,
)


# R5b: payment handled must not be performed by an employee.
R5B_PAYMENT_HANDLED_NOT_BY_EMPLOYEE = ValidationRule(
    rule_id="R5B",
    name="PAYMENT_HANDLED_NOT_BY_EMPLOYEE",
    description=(
        "Every 'Payment Handled' activity must not be associated with role "
        "EMPLOYEE (xes-attr:org_role)."
    ),
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX attr: <http://www.xes-standard.org/attribute/>

        SELECT ?activity ?role ?issue
        WHERE {
            ?activity a prov:Activity ;
                      rdfs:label "Payment Handled" ;
                      attr:xes-attr_org_role ?role .
            FILTER(?role = "EMPLOYEE")
            BIND("payment_handled_by_employee" AS ?issue)
        }
        ORDER BY ?activity
    """,
)


# R6: a payment is valid only via a multi-hop wasInformedBy provenance chain in one case.
R6_PAYMENT_PROVENANCE_CHAIN = ValidationRule(
    rule_id="R6",
    name="PAYMENT_PROVENANCE_CHAIN",
    description=(
        "A payment is valid only if Payment Handled wasInformedBy Request "
        "Payment, which wasInformedBy Final Approval, which wasInformedBy "
        "Declaration Submission, and all belong to the same case "
        "(prov:wasInformedBy+; optional steps such as PRE_APPROVER may appear "
        "between these milestones)."
    ),
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX wf: <http://kg.workflow.validation/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?payment ?case ?issue
        WHERE {
            ?payment a prov:Activity ;
                     rdfs:label "Payment Handled" ;
                     wf:belongsToCase ?case .
            FILTER NOT EXISTS {
                ?payment prov:wasInformedBy+ ?request .
                ?request rdfs:label "Request Payment" ;
                         wf:belongsToCase ?case .
                ?request prov:wasInformedBy+ ?approval .
                ?approval rdfs:label "Declaration FINAL_APPROVED by SUPERVISOR" ;
                          wf:belongsToCase ?case .
                ?approval prov:wasInformedBy+ ?submission .
                ?submission rdfs:label "Declaration SUBMITTED by EMPLOYEE" ;
                            wf:belongsToCase ?case .
            }
            BIND("invalid_payment_provenance_chain" AS ?issue)
        }
        ORDER BY ?payment
    """,
)


VALIDATION_RULES: tuple[ValidationRule, ...] = (
    R1_ACTIVITY_BELONGS_TO_CASE,
    R2_ACTIVITY_HAS_STARTED_AT_TIME,
    R3_ACTIVITY_HAS_AGENT,
    R4_WAS_INFORMED_BY_TEMPORAL_CONSISTENCY,
    R5_PAYMENT_HANDLED_BY_SYSTEM,
    R5B_PAYMENT_HANDLED_NOT_BY_EMPLOYEE,
    R6_PAYMENT_PROVENANCE_CHAIN,
)
