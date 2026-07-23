# Benchmark experiment report

Generated: `2026-07-23T10:49:06.345129+00:00`

## Setup

- Datasets: **10declarations** (5 faults/rule) and **full** (100 faults/rule)
- R1–R4: DECLARE-aligned control-flow (existence / response / precedence / succession);
  faults injected in XES; compared with KG SPARQL **and** PM4Py DECLARE on **violated cases**
- R5 / R5B / R6: KG-only domain rules (resource / role / provenance); no DECLARE
- Seed: `42`

## Isolated per-rule summary

Passed **14/14**.

| Dataset | Rule | Traces | Events | Triples | Conv (s) | Load (s) | KG val (s) | Inj. | KG cases | KG rows | DECLARE cases | DECLARE (s) | Case P | Case R | Status |
|---------|------|--------|--------|---------|----------|----------|------------|------|----------|---------|---------------|-------------|--------|--------|--------|
| 10declarations | R1 | 10 | 44 | 679 | 0.0713 | 0.0155 | 0.0004 | 5 | 5 | 5 | 5 | 0.0513 | 1.0000 | 1.0000 | PASS |
| 10declarations | R2 | 10 | 47 | 722 | 0.0344 | 0.0175 | 0.0008 | 5 | 5 | 7 | 5 | 0.0075 | 1.0000 | 1.0000 | PASS |
| 10declarations | R3 | 10 | 52 | 787 | 0.0367 | 0.0266 | 0.0008 | 5 | 5 | 5 | 5 | 0.0158 | 1.0000 | 1.0000 | PASS |
| 10declarations | R4 | 10 | 47 | 722 | 0.0663 | 0.0353 | 0.0016 | 5 | 5 | 5 | 5 | 0.0214 | 1.0000 | 1.0000 | PASS |
| 10declarations | R5 | 10 | 52 | 787 | 0.0952 | 0.0333 | 0.4530 | 5 | n/a | 5 | n/a | n/a | 1.0000 | 1.0000 | PASS |
| 10declarations | R5B | 10 | 52 | 787 | 0.1395 | 0.0324 | 0.0156 | 5 | n/a | 5 | n/a | n/a | 1.0000 | 1.0000 | PASS |
| 10declarations | R6 | 10 | 52 | 787 | 0.0761 | 0.0444 | 0.0027 | 5 | n/a | 5 | n/a | n/a | 1.0000 | 1.0000 | PASS |
| full | R1 | 10500 | 56331 | 848194 | 71.1228 | 48.1112 | 0.7199 | 100 | 235 | 235 | 235 | 4.0139 | 0.4255 | 1.0000 | PASS |
| full | R2 | 10500 | 56337 | 848364 | 174.6911 | 44.5863 | 2.2325 | 100 | 132 | 134 | 132 | 8.2431 | 0.7576 | 1.0000 | PASS |
| full | R3 | 10500 | 56437 | 849664 | 102.0772 | 46.9047 | 1.7258 | 100 | 107 | 107 | 107 | 4.8180 | 0.9346 | 1.0000 | PASS |
| full | R4 | 10500 | 56337 | 848364 | 110.6963 | 48.5761 | 2.1815 | 100 | 110 | 110 | 110 | 8.4172 | 0.9091 | 1.0000 | PASS |
| full | R5 | 10500 | 56437 | 849664 | 99.3617 | 36.6536 | 1.3594 | 100 | n/a | 100 | n/a | n/a | 1.0000 | 1.0000 | PASS |
| full | R5B | 10500 | 56437 | 849664 | 76.7801 | 27.9194 | 0.6964 | 100 | n/a | 100 | n/a | n/a | 1.0000 | 1.0000 | PASS |
| full | R6 | 10500 | 56437 | 849664 | 62.2564 | 27.3332 | 1.5771 | 100 | n/a | 109 | n/a | n/a | 0.9174 | 1.0000 | PASS |

### Notes on counting

- **Primary ground truth for R1–R4:** violated **cases** (injected `trace_id`).
- KG may emit more **rows** than cases (e.g. R2 multiple approvals, R4 both succession halves).
- DECLARE is scored on unfit cases for the single template of that rule.
- R5–R6 use entity-level precision/recall (no DECLARE).

### Timing / complexity

| Rule | Complexity |
|------|------------|
| R1 | DECLARE existence / case-level submission presence |
| R2 | DECLARE response / approval→request path |
| R3 | DECLARE precedence / request before payment |
| R4 | DECLARE succession / request↔payment |
| R5 | O(P) Payment Handled resource check |
| R5B | O(P) Payment Handled role check |
| R6 | O(P·E_case) payment provenance chain BFS |

## Per-rule details

### 10declarations / R1

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r1_10declarations`
- Status: **PASS** (KG[cases=5 rows=5]; DECLARE cases=5 devs=5; sets_equal=True)
- Size: traces=10, events=44, triples=679
- Times: conversion=0.0713s, load=0.0155s, KG val=0.0004s
- DECLARE: cases=5, devs=5, time=0.0513s, template=`existence`
- Case PR (KG): P=1.0, R=1.0; (DECLARE): P=1.0, R=1.0; sets_equal=True
- Complexity: DECLARE existence / case-level submission presence
- Sample injected faults:

```json
[
  {
    "rule_id": "R1",
    "action": "removed_submission_events",
    "details": {
      "trace_id": "declaration 86795",
      "event_ids": "st_step 86798_0",
      "removed_count": "1",
      "activity": "Declaration SUBMITTED by EMPLOYEE"
    }
  },
  {
    "rule_id": "R1",
    "action": "removed_submission_events",
    "details": {
      "trace_id": "declaration 86791",
      "event_ids": "st_step 86794_0",
      "removed_count": "1",
      "activity": "Declaration SUBMITTED by EMPLOYEE"
    }
  },
  {
    "rule_id": "R1",
    "action": "removed_submission_events",
    "details": {
      "trace_id": "declaration 86735",
      "event_ids": "st_step 86738_0",
      "removed_count": "1",
      "activity": "Declaration SUBMITTED by EMPLOYEE"
    }
  }
]
```

### 10declarations / R2

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r2_10declarations`
- Status: **PASS** (KG[cases=5 rows=7]; DECLARE cases=5 devs=5; sets_equal=True)
- Size: traces=10, events=47, triples=722
- Times: conversion=0.0344s, load=0.0175s, KG val=0.0008s
- DECLARE: cases=5, devs=5, time=0.0075s, template=`response`
- Case PR (KG): P=1.0, R=1.0; (DECLARE): P=1.0, R=1.0; sets_equal=True
- Complexity: DECLARE response / approval→request path
- Sample injected faults:

```json
[
  {
    "rule_id": "R2",
    "action": "removed_request_payment_after_approval",
    "details": {
      "trace_id": "declaration 86795",
      "event_ids": "dd_declaration 86795_19",
      "removed_count": "1",
      "activity": "Request Payment"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_request_payment_after_approval",
    "details": {
      "trace_id": "declaration 86791",
      "event_ids": "dd_declaration 86791_19",
      "removed_count": "1",
      "activity": "Request Payment"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_request_payment_after_approval",
    "details": {
      "trace_id": "declaration 86735",
      "event_ids": "dd_declaration 86735_19",
      "removed_count": "1",
      "activity": "Request Payment"
    }
  }
]
```

### 10declarations / R3

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r3_10declarations`
- Status: **PASS** (KG[cases=5 rows=5]; DECLARE cases=5 devs=5; sets_equal=True)
- Size: traces=10, events=52, triples=787
- Times: conversion=0.0367s, load=0.0266s, KG val=0.0008s
- DECLARE: cases=5, devs=5, time=0.0158s, template=`precedence`
- Case PR (KG): P=1.0, R=1.0; (DECLARE): P=1.0, R=1.0; sets_equal=True
- Complexity: DECLARE precedence / request before payment
- Sample injected faults:

```json
[
  {
    "rule_id": "R3",
    "action": "swapped_request_payment_for_precedence",
    "details": {
      "trace_id": "declaration 86795",
      "request_event_id_before": "dd_declaration 86795_19",
      "payment_event_id_before": "dd_declaration 86795_20",
      "request_event_id_after": "dd_declaration 86795_20",
      "payment_event_id_after": "dd_declaration 86795_19",
      "note": "Timestamps stayed on their slots so conversion order places Payment before Request."
    }
  },
  {
    "rule_id": "R3",
    "action": "swapped_request_payment_for_precedence",
    "details": {
      "trace_id": "declaration 86791",
      "request_event_id_before": "dd_declaration 86791_19",
      "payment_event_id_before": "dd_declaration 86791_20",
      "request_event_id_after": "dd_declaration 86791_20",
      "payment_event_id_after": "dd_declaration 86791_19",
      "note": "Timestamps stayed on their slots so conversion order places Payment before Request."
    }
  },
  {
    "rule_id": "R3",
    "action": "swapped_request_payment_for_precedence",
    "details": {
      "trace_id": "declaration 86735",
      "request_event_id_before": "dd_declaration 86735_19",
      "payment_event_id_before": "dd_declaration 86735_20",
      "request_event_id_after": "dd_declaration 86735_20",
      "payment_event_id_after": "dd_declaration 86735_19",
      "note": "Timestamps stayed on their slots so conversion order places Payment before Request."
    }
  }
]
```

### 10declarations / R4

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r4_10declarations`
- Status: **PASS** (KG[cases=5 rows=5]; DECLARE cases=5 devs=5; sets_equal=True)
- Size: traces=10, events=47, triples=722
- Times: conversion=0.0663s, load=0.0353s, KG val=0.0016s
- DECLARE: cases=5, devs=5, time=0.0214s, template=`succession`
- Case PR (KG): P=1.0, R=1.0; (DECLARE): P=1.0, R=1.0; sets_equal=True
- Complexity: DECLARE succession / request↔payment
- Sample injected faults:

```json
[
  {
    "rule_id": "R4",
    "action": "removed_payment_handled_for_succession",
    "details": {
      "trace_id": "declaration 86795",
      "event_ids": "dd_declaration 86795_20",
      "removed_count": "1",
      "activity": "Payment Handled"
    }
  },
  {
    "rule_id": "R4",
    "action": "removed_payment_handled_for_succession",
    "details": {
      "trace_id": "declaration 86791",
      "event_ids": "dd_declaration 86791_20",
      "removed_count": "1",
      "activity": "Payment Handled"
    }
  },
  {
    "rule_id": "R4",
    "action": "removed_payment_handled_for_succession",
    "details": {
      "trace_id": "declaration 86735",
      "event_ids": "dd_declaration 86735_20",
      "removed_count": "1",
      "activity": "Payment Handled"
    }
  }
]
```

### 10declarations / R5

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r5_10declarations`
- Status: **PASS** (rows=5 P=1.0 R=1.0)
- Size: traces=10, events=52, triples=787
- Times: conversion=0.0952s, load=0.0333s, KG val=0.4530s
- Entity PR: P=1.0, R=1.0 (TP=5, FP=0, FN=0)
- Complexity: O(P) Payment Handled resource check
- Sample injected faults:

```json
[
  {
    "rule_id": "R5",
    "action": "changed_payment_resource_from_system",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_86795_20",
      "resource_before": "SYSTEM",
      "resource_after": "BOGUS_RESOURCE_2679"
    }
  },
  {
    "rule_id": "R5",
    "action": "changed_payment_resource_from_system",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_86791_20",
      "resource_before": "SYSTEM",
      "resource_after": "Fictional Payment Handler"
    }
  },
  {
    "rule_id": "R5",
    "action": "changed_payment_resource_from_system",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_86735_20",
      "resource_before": "SYSTEM",
      "resource_after": "BOGUS_RESOURCE_7912"
    }
  }
]
```

### 10declarations / R5B

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r5b_10declarations`
- Status: **PASS** (rows=5 P=1.0 R=1.0)
- Size: traces=10, events=52, triples=787
- Times: conversion=0.1395s, load=0.0324s, KG val=0.0156s
- Entity PR: P=1.0, R=1.0 (TP=5, FP=0, FN=0)
- Complexity: O(P) Payment Handled role check
- Sample injected faults:

```json
[
  {
    "rule_id": "R5B",
    "action": "set_payment_role_to_employee",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_86795_20",
      "role_before": "UNDEFINED",
      "role_after": "EMPLOYEE"
    }
  },
  {
    "rule_id": "R5B",
    "action": "set_payment_role_to_employee",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_86791_20",
      "role_before": "UNDEFINED",
      "role_after": "EMPLOYEE"
    }
  },
  {
    "rule_id": "R5B",
    "action": "set_payment_role_to_employee",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_86735_20",
      "role_before": "UNDEFINED",
      "role_after": "EMPLOYEE"
    }
  }
]
```

### 10declarations / R6

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r6_10declarations`
- Status: **PASS** (rows=5 recall=1)
- Size: traces=10, events=52, triples=787
- Times: conversion=0.0761s, load=0.0444s, KG val=0.0027s
- Entity PR: P=1.0, R=1.0 (TP=5, FP=0, FN=0)
- Complexity: O(P·E_case) payment provenance chain BFS
- Sample injected faults:

```json
[
  {
    "rule_id": "R6",
    "action": "scrambled_payment_provenance_order",
    "details": {
      "payment": "http://kg.workflow.validation/activity/dd_declaration_86795_20",
      "request": "http://kg.workflow.validation/activity/dd_declaration_86795_19",
      "approval": "http://kg.workflow.validation/activity/st_step_86797_0",
      "submission": "http://kg.workflow.validation/activity/st_step_86798_0",
      "payment_wasInformedBy": "http://kg.workflow.validation/activity/dd_declaration_86795_19",
      "request_wasInformedBy": "http://kg.workflow.validation/activity/st_step_86797_0",
      "approval_wasInformedBy": "http://kg.workflow.validation/activity/st_step_86799_0",
      "case": "http://kg.workflow.validation/case/declaration_86795",
      "new_order": "http://kg.workflow.validation/activity/dd_declaration_86795_20 -> http://kg.workflow.validation/activity/st_step_86798_0 -> http://kg.workflow.validation/activity/st_step_86797_0 -> http://kg.workflow.validation/activity/dd_declaration_86795_19"
    }
  },
  {
    "rule_id": "R6",
    "action": "removed_payment_wasInformedBy",
    "details": {
      "payment": "http://kg.workflow.validation/activity/dd_declaration_86791_20",
      "request": "http://kg.workflow.validation/activity/dd_declaration_86791_19",
      "approval": "http://kg.workflow.validation/activity/st_step_86793_0",
      "submission": "http://kg.workflow.validation/activity/st_step_86794_0",
      "case": "http://kg.workflow.validation/case/declaration_86791",
      "removed_earlier": "http://kg.workflow.validation/activity/dd_declaration_86791_19"
    }
  },
  {
    "rule_id": "R6",
    "action": "removed_payment_wasInformedBy",
    "details": {
      "payment": "http://kg.workflow.validation/activity/dd_declaration_86735_20",
      "request": "http://kg.workflow.validation/activity/dd_declaration_86735_19",
      "approval": "http://kg.workflow.validation/activity/st_step_86737_0",
      "submission": "http://kg.workflow.validation/activity/st_step_86738_0",
      "case": "http://kg.workflow.validation/case/declaration_86735",
      "removed_earlier": "http://kg.workflow.validation/activity/dd_declaration_86735_19"
    }
  }
]
```

### full / R1

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r1_full`
- Status: **PASS** (KG[cases=235 rows=235 (+135 baseline/collateral cases)]; DECLARE cases=235 devs=235; sets_equal=True)
- Size: traces=10500, events=56331, triples=848194
- Times: conversion=71.1228s, load=48.1112s, KG val=0.7199s
- DECLARE: cases=235, devs=235, time=4.0139s, template=`existence`
- Case PR (KG): P=0.4255, R=1.0; (DECLARE): P=0.4255, R=1.0; sets_equal=True
- Complexity: DECLARE existence / case-level submission presence
- Sample injected faults:

```json
[
  {
    "rule_id": "R1",
    "action": "removed_submission_events",
    "details": {
      "trace_id": "declaration 94206",
      "event_ids": "st_step 94208_0",
      "removed_count": "1",
      "activity": "Declaration SUBMITTED by EMPLOYEE"
    }
  },
  {
    "rule_id": "R1",
    "action": "removed_submission_events",
    "details": {
      "trace_id": "declaration 89000",
      "event_ids": "st_step 89003_0",
      "removed_count": "1",
      "activity": "Declaration SUBMITTED by EMPLOYEE"
    }
  },
  {
    "rule_id": "R1",
    "action": "removed_submission_events",
    "details": {
      "trace_id": "declaration 104162",
      "event_ids": "st_step 104164_0",
      "removed_count": "1",
      "activity": "Declaration SUBMITTED by EMPLOYEE"
    }
  }
]
```

### full / R2

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r2_full`
- Status: **PASS** (KG[cases=132 rows=134 (+32 baseline/collateral cases)]; DECLARE cases=132 devs=132; sets_equal=True)
- Size: traces=10500, events=56337, triples=848364
- Times: conversion=174.6911s, load=44.5863s, KG val=2.2325s
- DECLARE: cases=132, devs=132, time=8.2431s, template=`response`
- Case PR (KG): P=0.7576, R=1.0; (DECLARE): P=0.7576, R=1.0; sets_equal=True
- Complexity: DECLARE response / approval→request path
- Sample injected faults:

```json
[
  {
    "rule_id": "R2",
    "action": "removed_request_payment_after_approval",
    "details": {
      "trace_id": "declaration 87145",
      "event_ids": "dd_declaration 87145_19",
      "removed_count": "1",
      "activity": "Request Payment"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_request_payment_after_approval",
    "details": {
      "trace_id": "declaration 89680",
      "event_ids": "dd_declaration 89680_19",
      "removed_count": "1",
      "activity": "Request Payment"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_request_payment_after_approval",
    "details": {
      "trace_id": "declaration 100131",
      "event_ids": "dd_declaration 100131_19",
      "removed_count": "1",
      "activity": "Request Payment"
    }
  }
]
```

### full / R3

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r3_full`
- Status: **PASS** (KG[cases=107 rows=107 (+7 baseline/collateral cases)]; DECLARE cases=107 devs=107; sets_equal=True)
- Size: traces=10500, events=56437, triples=849664
- Times: conversion=102.0772s, load=46.9047s, KG val=1.7258s
- DECLARE: cases=107, devs=107, time=4.8180s, template=`precedence`
- Case PR (KG): P=0.9346, R=1.0; (DECLARE): P=0.9346, R=1.0; sets_equal=True
- Complexity: DECLARE precedence / request before payment
- Sample injected faults:

```json
[
  {
    "rule_id": "R3",
    "action": "swapped_request_payment_for_precedence",
    "details": {
      "trace_id": "declaration 91957",
      "request_event_id_before": "dd_declaration 91957_19",
      "payment_event_id_before": "dd_declaration 91957_20",
      "request_event_id_after": "dd_declaration 91957_20",
      "payment_event_id_after": "dd_declaration 91957_19",
      "note": "Timestamps stayed on their slots so conversion order places Payment before Request."
    }
  },
  {
    "rule_id": "R3",
    "action": "swapped_request_payment_for_precedence",
    "details": {
      "trace_id": "declaration 89680",
      "request_event_id_before": "dd_declaration 89680_19",
      "payment_event_id_before": "dd_declaration 89680_20",
      "request_event_id_after": "dd_declaration 89680_20",
      "payment_event_id_after": "dd_declaration 89680_19",
      "note": "Timestamps stayed on their slots so conversion order places Payment before Request."
    }
  },
  {
    "rule_id": "R3",
    "action": "swapped_request_payment_for_precedence",
    "details": {
      "trace_id": "declaration 100137",
      "request_event_id_before": "dd_declaration 100137_19",
      "payment_event_id_before": "dd_declaration 100137_20",
      "request_event_id_after": "dd_declaration 100137_20",
      "payment_event_id_after": "dd_declaration 100137_19",
      "note": "Timestamps stayed on their slots so conversion order places Payment before Request."
    }
  }
]
```

### full / R4

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r4_full`
- Status: **PASS** (KG[cases=110 rows=110 (+10 baseline/collateral cases)]; DECLARE cases=110 devs=110; sets_equal=True)
- Size: traces=10500, events=56337, triples=848364
- Times: conversion=110.6963s, load=48.5761s, KG val=2.1815s
- DECLARE: cases=110, devs=110, time=8.4172s, template=`succession`
- Case PR (KG): P=0.9091, R=1.0; (DECLARE): P=0.9091, R=1.0; sets_equal=True
- Complexity: DECLARE succession / request↔payment
- Sample injected faults:

```json
[
  {
    "rule_id": "R4",
    "action": "removed_payment_handled_for_succession",
    "details": {
      "trace_id": "declaration 91957",
      "event_ids": "dd_declaration 91957_20",
      "removed_count": "1",
      "activity": "Payment Handled"
    }
  },
  {
    "rule_id": "R4",
    "action": "removed_payment_handled_for_succession",
    "details": {
      "trace_id": "declaration 89680",
      "event_ids": "dd_declaration 89680_20",
      "removed_count": "1",
      "activity": "Payment Handled"
    }
  },
  {
    "rule_id": "R4",
    "action": "removed_payment_handled_for_succession",
    "details": {
      "trace_id": "declaration 100137",
      "event_ids": "dd_declaration 100137_20",
      "removed_count": "1",
      "activity": "Payment Handled"
    }
  }
]
```

### full / R5

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r5_full`
- Status: **PASS** (rows=100 P=1.0 R=1.0)
- Size: traces=10500, events=56437, triples=849664
- Times: conversion=99.3617s, load=36.6536s, KG val=1.3594s
- Entity PR: P=1.0, R=1.0 (TP=100, FP=0, FN=0)
- Complexity: O(P) Payment Handled resource check
- Sample injected faults:

```json
[
  {
    "rule_id": "R5",
    "action": "changed_payment_resource_from_system",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_91957_20",
      "resource_before": "SYSTEM",
      "resource_after": "Fictional Payment Handler"
    }
  },
  {
    "rule_id": "R5",
    "action": "changed_payment_resource_from_system",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_89680_20",
      "resource_before": "SYSTEM",
      "resource_after": "BOGUS_RESOURCE_8019"
    }
  },
  {
    "rule_id": "R5",
    "action": "changed_payment_resource_from_system",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_100137_20",
      "resource_before": "SYSTEM",
      "resource_after": "UNDEFINED"
    }
  }
]
```

### full / R5B

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r5b_full`
- Status: **PASS** (rows=100 P=1.0 R=1.0)
- Size: traces=10500, events=56437, triples=849664
- Times: conversion=76.7801s, load=27.9194s, KG val=0.6964s
- Entity PR: P=1.0, R=1.0 (TP=100, FP=0, FN=0)
- Complexity: O(P) Payment Handled role check
- Sample injected faults:

```json
[
  {
    "rule_id": "R5B",
    "action": "set_payment_role_to_employee",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_91957_20",
      "role_before": "UNDEFINED",
      "role_after": "EMPLOYEE"
    }
  },
  {
    "rule_id": "R5B",
    "action": "set_payment_role_to_employee",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_89680_20",
      "role_before": "UNDEFINED",
      "role_after": "EMPLOYEE"
    }
  },
  {
    "rule_id": "R5B",
    "action": "set_payment_role_to_employee",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_100137_20",
      "role_before": "UNDEFINED",
      "role_after": "EMPLOYEE"
    }
  }
]
```

### full / R6

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r6_full`
- Status: **PASS** (rows=109 recall=1)
- Size: traces=10500, events=56437, triples=849664
- Times: conversion=62.2564s, load=27.3332s, KG val=1.5771s
- Entity PR: P=0.9174, R=1.0 (TP=100, FP=9, FN=0)
- Complexity: O(P·E_case) payment provenance chain BFS
- Sample injected faults:

```json
[
  {
    "rule_id": "R6",
    "action": "removed_payment_wasInformedBy",
    "details": {
      "payment": "http://kg.workflow.validation/activity/dd_declaration_87871_20",
      "request": "http://kg.workflow.validation/activity/dd_declaration_87871_19",
      "approval": "http://kg.workflow.validation/activity/st_step_87874_0",
      "submission": "http://kg.workflow.validation/activity/st_step_87873_0",
      "case": "http://kg.workflow.validation/case/declaration_87871",
      "removed_earlier": "http://kg.workflow.validation/activity/dd_declaration_87871_19"
    }
  },
  {
    "rule_id": "R6",
    "action": "removed_payment_wasInformedBy",
    "details": {
      "payment": "http://kg.workflow.validation/activity/dd_declaration_89680_20",
      "request": "http://kg.workflow.validation/activity/dd_declaration_89680_19",
      "approval": "http://kg.workflow.validation/activity/st_step_89683_0",
      "submission": "http://kg.workflow.validation/activity/st_step_89682_0",
      "case": "http://kg.workflow.validation/case/declaration_89680",
      "removed_earlier": "http://kg.workflow.validation/activity/dd_declaration_89680_19"
    }
  },
  {
    "rule_id": "R6",
    "action": "removed_payment_wasInformedBy",
    "details": {
      "payment": "http://kg.workflow.validation/activity/dd_declaration_100149_20",
      "request": "http://kg.workflow.validation/activity/dd_declaration_100149_19",
      "approval": "http://kg.workflow.validation/activity/st_step_100153_0",
      "submission": "http://kg.workflow.validation/activity/st_step_100151_0",
      "case": "http://kg.workflow.validation/case/declaration_100149",
      "removed_earlier": "http://kg.workflow.validation/activity/dd_declaration_100149_19"
    }
  }
]
```
## Combined all-rules benchmarks

Updated: `2026-07-23T10:52:14.601244+00:00`

All rules injected together (same counts/seed as isolated). KG validates all rules; DECLARE is run per R1–R4 template on the corrupted XES. R1–R4 scored by **case recall**; R5–R6 by entity recall. Collateral may raise row counts.

Combined suites passed: **2/2**.

### Overview

| Dataset | Traces | Events | Triples | Conv (s) | Load (s) | Val total (s) | Injected | KG rows | Status |
|---------|--------|--------|---------|----------|----------|---------------|----------|---------|--------|
| 10declarations | 10 | 37 | 588 | 0.0339 | 0.0148 | 0.0196 | 22 | 40 | PASS |
| full | 10500 | 56131 | 845594 | 68.7322 | 29.6271 | 7.3829 | 700 | 1829 | PASS |

### Combined detail: 10declarations

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_all_10declarations`

| Rule | Inj. | KG cases | KG rows | KG (s) | DECLARE cases | DECLARE (s) | Case/Entity R | OK |
|------|-----:|---------:|--------:|-------:|--------------:|------------:|--------------:|----|
| R1 | 5 | 5 | 5 | 0.0003 | 5 | 0.0065 | 1.0 | Y |
| R2 | 5 | 5 | 5 | 0.0007 | 5 | 0.0084 | 1.0 | Y |
| R3 | 0 | 5 | 5 | 0.0005 | 5 | 0.0057 | 1.0 | Y |
| R4 | 2 | 7 | 7 | 0.0006 | 7 | 0.0065 | 1.0 | Y |
| R5 | 5 | n/a | 5 | 0.0083 | n/a | n/a | 1.0 | Y |
| R5B | 5 | n/a | 5 | 0.0078 | n/a | n/a | 1.0 | Y |
| R6 | 0 | n/a | 8 | 0.0015 | n/a | n/a | 1.0 | Y |

### Combined detail: full

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_all_full`

| Rule | Inj. | KG cases | KG rows | KG (s) | DECLARE cases | DECLARE (s) | Case/Entity R | OK |
|------|-----:|---------:|--------:|-------:|--------------:|------------:|--------------:|----|
| R1 | 100 | 235 | 235 | 0.4709 | 235 | 2.4251 | 1.0 | Y |
| R2 | 100 | 154 | 156 | 1.2467 | 132 | 3.5282 | 1.0 | Y |
| R3 | 100 | 279 | 279 | 0.8972 | 207 | 2.7178 | 1.0 | Y |
| R4 | 100 | 382 | 554 | 1.3237 | 310 | 3.7868 | 1.0 | Y |
| R5 | 100 | n/a | 100 | 1.2769 | n/a | n/a | 1.0 | Y |
| R5B | 100 | n/a | 100 | 0.5905 | n/a | n/a | 1.0 | Y |
| R6 | 100 | n/a | 405 | 1.5769 | n/a | n/a | 1.0 | Y |
