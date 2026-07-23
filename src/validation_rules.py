"""SPARQL validation rules for PROV-O workflow knowledge graphs.

R1–R4 are control-flow constraints aligned with DECLARE templates so the same
faults can be checked on XES (PM4Py DECLARE) and on the provenance KG.
R5–R6 remain domain-specific KG rules outside classic DECLARE scope.

Each rule exposes a SPARQL SELECT that returns one row per violation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationRule:
    rule_id: str
    name: str
    description: str
    query: str


# R1 / DECLARE existence: every case must contain a submission.
R1_SUBMISSION_EXISTENCE = ValidationRule(
    rule_id="R1",
    name="SUBMISSION_EXISTENCE",
    description=(
        "Every case must contain at least one activity labelled "
        "'Declaration SUBMITTED by EMPLOYEE' (DECLARE existence)."
    ),
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX wf: <http://kg.workflow.validation/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?case ?issue
        WHERE {
            {
                SELECT DISTINCT ?case
                WHERE { ?activity wf:belongsToCase ?case }
            }
            FILTER NOT EXISTS {
                ?submission a prov:Activity ;
                            rdfs:label "Declaration SUBMITTED by EMPLOYEE" ;
                            wf:belongsToCase ?case .
            }
            BIND("missing_submission_existence" AS ?issue)
        }
        ORDER BY ?case
    """,
)


# R2 / DECLARE response: after final approval, Request Payment must eventually follow.
R2_APPROVAL_REQUEST_RESPONSE = ValidationRule(
    rule_id="R2",
    name="APPROVAL_REQUEST_RESPONSE",
    description=(
        "If a case has 'Declaration FINAL_APPROVED by SUPERVISOR', then "
        "'Request Payment' must occur later in the same case "
        "(DECLARE response; KG: request wasInformedBy+ approval)."
    ),
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX wf: <http://kg.workflow.validation/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?case ?approval ?issue
        WHERE {
            ?approval a prov:Activity ;
                      rdfs:label "Declaration FINAL_APPROVED by SUPERVISOR" ;
                      wf:belongsToCase ?case .
            FILTER NOT EXISTS {
                ?request a prov:Activity ;
                         rdfs:label "Request Payment" ;
                         wf:belongsToCase ?case .
                ?request prov:wasInformedBy+ ?approval .
            }
            BIND("missing_response_request_after_approval" AS ?issue)
        }
        ORDER BY ?case ?approval
    """,
)


# R3 / DECLARE precedence: Payment Handled only if Request Payment occurred earlier.
R3_REQUEST_BEFORE_PAYMENT = ValidationRule(
    rule_id="R3",
    name="REQUEST_BEFORE_PAYMENT",
    description=(
        "A 'Payment Handled' activity is valid only if 'Request Payment' "
        "occurred earlier in the same case (DECLARE precedence; KG: payment "
        "wasInformedBy+ request)."
    ),
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX wf: <http://kg.workflow.validation/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?case ?payment ?issue
        WHERE {
            ?payment a prov:Activity ;
                     rdfs:label "Payment Handled" ;
                     wf:belongsToCase ?case .
            FILTER NOT EXISTS {
                ?request a prov:Activity ;
                         rdfs:label "Request Payment" ;
                         wf:belongsToCase ?case .
                ?payment prov:wasInformedBy+ ?request .
            }
            BIND("missing_precedence_request_before_payment" AS ?issue)
        }
        ORDER BY ?case ?payment
    """,
)


# R4 / DECLARE succession: Request Payment and Payment Handled in both directions.
R4_REQUEST_PAYMENT_SUCCESSION = ValidationRule(
    rule_id="R4",
    name="REQUEST_PAYMENT_SUCCESSION",
    description=(
        "In each case, 'Request Payment' and 'Payment Handled' must form a "
        "succession: every request is followed by a payment, and every payment "
        "is preceded by a request (DECLARE succession)."
    ),
    query="""
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX wf: <http://kg.workflow.validation/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?case ?activity ?issue
        WHERE {
            {
                ?request a prov:Activity ;
                         rdfs:label "Request Payment" ;
                         wf:belongsToCase ?case .
                FILTER NOT EXISTS {
                    ?payment a prov:Activity ;
                             rdfs:label "Payment Handled" ;
                             wf:belongsToCase ?case .
                    ?payment prov:wasInformedBy+ ?request .
                }
                BIND(?request AS ?activity)
                BIND("missing_succession_response_payment_after_request" AS ?issue)
            }
            UNION
            {
                ?payment a prov:Activity ;
                         rdfs:label "Payment Handled" ;
                         wf:belongsToCase ?case .
                FILTER NOT EXISTS {
                    ?request a prov:Activity ;
                             rdfs:label "Request Payment" ;
                             wf:belongsToCase ?case .
                    ?payment prov:wasInformedBy+ ?request .
                }
                BIND(?payment AS ?activity)
                BIND("missing_succession_precedence_request_before_payment" AS ?issue)
            }
        }
        ORDER BY ?case ?activity
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
    R1_SUBMISSION_EXISTENCE,
    R2_APPROVAL_REQUEST_RESPONSE,
    R3_REQUEST_BEFORE_PAYMENT,
    R4_REQUEST_PAYMENT_SUCCESSION,
    R5_PAYMENT_HANDLED_BY_SYSTEM,
    R5B_PAYMENT_HANDLED_NOT_BY_EMPLOYEE,
    R6_PAYMENT_PROVENANCE_CHAIN,
)

# Canonical DECLARE model matching R1–R4 (for PM4Py conformance_declare).
DECLARE_MODEL_R1_R4: dict[str, dict] = {
    "existence": {
        "Declaration SUBMITTED by EMPLOYEE": {"support": 1.0, "confidence": 1.0},
    },
    "response": {
        (
            "Declaration FINAL_APPROVED by SUPERVISOR",
            "Request Payment",
        ): {"support": 1.0, "confidence": 1.0},
    },
    "precedence": {
        ("Request Payment", "Payment Handled"): {"support": 1.0, "confidence": 1.0},
    },
    "succession": {
        ("Request Payment", "Payment Handled"): {"support": 1.0, "confidence": 1.0},
    },
}
