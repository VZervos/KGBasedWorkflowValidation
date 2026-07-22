# Per-rule benchmark experiment report

Generated: `2026-07-22T10:40:18.090305+00:00`

## Setup

- Datasets: **10declarations** (5 injected faults/rule) and **full** (100 injected faults/rule)
- One benchmark per rule (R1–R6, R5B), validated with only that rule enabled
- Seed: `42`
- R4 strategy (updated): **break_order only** (`later.startedAtTime < earlier`)

## Summary

Passed **14/14** cases.

| Dataset | Rule | Traces | Events | Triples | Conv (s) | Load (s) | Val (s) | Injected | Detected | P | R | Status |
|---------|------|--------|--------|---------|----------|----------|---------|----------|----------|---|---|--------|
| 10declarations | R1 | 10 | 52 | 787 | 0.0370 | 0.0167 | 0.3730 | 5 | 5 | 1.0000 | 1.0000 | PASS |
| 10declarations | R2 | 10 | 52 | 787 | 0.0370 | 0.0167 | 0.0106 | 5 | 5 | 1.0000 | 1.0000 | PASS |
| 10declarations | R3 | 10 | 52 | 787 | 0.0370 | 0.0167 | 0.0092 | 5 | 5 | 1.0000 | 1.0000 | PASS |
| 10declarations | R4 | 10 | 52 | 787 | 0.0370 | 0.0167 | 0.1413 | 5 | 5 | 1.0000 | 1.0000 | PASS |
| 10declarations | R5 | 10 | 52 | 787 | 0.0370 | 0.0167 | 0.0073 | 5 | 5 | 1.0000 | 1.0000 | PASS |
| 10declarations | R5B | 10 | 52 | 787 | 0.0370 | 0.0167 | 0.0071 | 5 | 5 | 1.0000 | 1.0000 | PASS |
| 10declarations | R6 | 10 | 52 | 787 | 0.0370 | 0.0167 | 0.0009 | 5 | 5 | 1.0000 | 1.0000 | PASS |
| full | R1 | 10500 | 56437 | 849664 | 37.6344 | 25.6962 | 12.5788 | 100 | 100 | 1.0000 | 1.0000 | PASS |
| full | R2 | 10500 | 56437 | 849664 | 37.6344 | 25.6962 | 7.5511 | 100 | 100 | 1.0000 | 1.0000 | PASS |
| full | R3 | 10500 | 56437 | 849664 | 37.6344 | 25.6962 | 7.3313 | 100 | 100 | 1.0000 | 1.0000 | PASS |
| full | R4 | 10500 | 56437 | 849664 | 37.6344 | 25.6962 | 15.9040 | 100 | 100 | 1.0000 | 1.0000 | PASS |
| full | R5 | 10500 | 56437 | 849664 | 37.6344 | 25.6962 | 2.1551 | 100 | 100 | 1.0000 | 1.0000 | PASS |
| full | R5B | 10500 | 56437 | 849664 | 37.6344 | 25.6962 | 0.8921 | 100 | 100 | 1.0000 | 1.0000 | PASS |
| full | R6 | 10500 | 56437 | 849664 | 37.6344 | 25.6962 | 2.7803 | 100 | 109 | 0.9174 | 1.0000 | PASS |

### Timing vs rule complexity

Validation times grow with dataset size. Per-rule asymptotic cost (A = activities/events, E = wasInformedBy edges, P = Payment Handled):

- **R1**: O(A) — scan activities for belongsToCase cardinality
- **R2**: O(A) — scan activities for startedAtTime presence
- **R3**: O(A) — scan activities for wasAssociatedWith
- **R4**: O(E) — scan wasInformedBy edges + compare timestamps
- **R5**: O(P) — Payment Handled resource check
- **R5B**: O(P) — Payment Handled role check
- **R6**: O(P · E_case) — BFS/ancestor search per Payment Handled over wasInformedBy

Empirically, R1–R5B stay near-linear on activities/payments, while **R6** is slower on the full log because each Payment Handled triggers a provenance ancestor search (BFS) over case edges.

### Validation time by rule (seconds)

| Rule | 10declarations | full | full / 10decl | Complexity |
|------|----------------|------|---------------|------------|
| R1 | 0.3730 | 12.5788 | 33.7× | O(A) — scan activities for belongsToCase cardinality |
| R2 | 0.0106 | 7.5511 | 714.9× | O(A) — scan activities for startedAtTime presence |
| R3 | 0.0092 | 7.3313 | 800.1× | O(A) — scan activities for wasAssociatedWith |
| R4 | 0.1413 | 15.9040 | 112.5× | O(E) — scan wasInformedBy edges + compare timestamps |
| R5 | 0.0073 | 2.1551 | 295.4× | O(P) — Payment Handled resource check |
| R5B | 0.0071 | 0.8921 | 126.0× | O(P) — Payment Handled role check |
| R6 | 0.0009 | 2.7803 | 3028.7× | O(P · E_case) — BFS/ancestor search per Payment Handled over wasInformedBy |

## Finding: 9 pre-existing invalid payments (R6 / full)

On the **full** dataset, R6 reported **109** violations against **100** injected faults. The extra **9** are Payment Handled activities that already lack a valid provenance chain in the clean BPI Domestic Declarations log (eligible valid chains were 10,035 vs ~10,044 payments).

| Declaration | Payment activity | Reason |
|-------------|------------------|--------|
| `90815` | `dd_declaration_90815_20` | Supervisor REJECTED (no FINAL_APPROVED); has Request Payment |
| `95149` | `dd_declaration_95149_20` | Only SAVED → Request Payment → Payment Handled (no submission / final approval) |
| `115669` | `dd_declaration_115669_20` | Missing Request Payment between final approval and payment |
| `124535` | `dd_declaration_124535_20` | Missing Request Payment (reject/resubmit then pay) |
| `136996` | `dd_declaration_136996_20` | Missing Request Payment |
| `138147` | `dd_declaration_138147_20` | Missing Request Payment |
| `138710` | `dd_declaration_138710_20` | Missing Request Payment |
| `141310` | `dd_declaration_141310_20` | Missing Request Payment |
| `142992` | `dd_declaration_142992_20` | Missing Request Payment |

Required R6 chain: `Payment Handled ← Request Payment ← FINAL_APPROVED ← SUBMITTED` (via `wasInformedBy+`, same case).

## R4 regeneration note

R4 corruption previously mixed `break_order` and `remove_startedAtTime`. Removing start time on a mid-chain activity invalidated multiple edges (as informed **and** as informing), so violation count exceeded applied count (100 → 139 on full). R4 now uses **break_order only**; regenerated runs:

- `10declarations/R4`: applied=5, violations=5, load=0.0167s, val=0.1413s → `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r4_10declarations`
- `full/R4`: applied=100, violations=100, load=25.6962s, val=15.9040s → `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r4_10declarations`

## Per-case details (ground truth samples)

### 10declarations / R1

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r1_10declarations`
- Status: **PASS** (exact match)
- Size: traces=10, events=52, triples=787, xes_lines=442
- Times: conversion=0.0370s, load=0.0167s, validation=0.3730s
- Ground truth: injected=5, detected=5
- Precision/Recall: P=1.0000, R=1.0000 (TP=5, FP=0, FN=0)
- Complexity: O(A) — scan activities for belongsToCase cardinality
- Sample injected faults:

```json
[
  {
    "rule_id": "R1",
    "action": "removed_belongsToCase",
    "details": {
      "activity": "http://kg.workflow.validation/activity/st_step_86719_0",
      "removed_cases": "http://kg.workflow.validation/case/declaration_86716",
      "case_count_before": "1"
    }
  },
  {
    "rule_id": "R1",
    "action": "removed_belongsToCase",
    "details": {
      "activity": "http://kg.workflow.validation/activity/st_step_86799_0",
      "removed_cases": "http://kg.workflow.validation/case/declaration_86795",
      "case_count_before": "1"
    }
  },
  {
    "rule_id": "R1",
    "action": "removed_belongsToCase",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_86791_19",
      "removed_cases": "http://kg.workflow.validation/case/declaration_86791",
      "case_count_before": "1"
    }
  }
]
```

### 10declarations / R2

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r2_10declarations`
- Status: **PASS** (exact match)
- Size: traces=10, events=52, triples=787, xes_lines=442
- Times: conversion=0.0370s, load=0.0167s, validation=0.0106s
- Ground truth: injected=5, detected=5
- Precision/Recall: P=1.0000, R=1.0000 (TP=5, FP=0, FN=0)
- Complexity: O(A) — scan activities for startedAtTime presence
- Sample injected faults:

```json
[
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 86716",
      "event_id": "dd_declaration 86716_20",
      "removed_values": "2017-01-16T17:32:14.000+01:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 86795",
      "event_id": "dd_declaration 86795_19",
      "removed_values": "2017-03-06T14:07:25.000+01:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 86791",
      "event_id": "st_step 86793_0",
      "removed_values": "2017-01-09T11:27:48.000+01:00"
    }
  }
]
```

### 10declarations / R3

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r3_10declarations`
- Status: **PASS** (exact match)
- Size: traces=10, events=52, triples=787, xes_lines=442
- Times: conversion=0.0370s, load=0.0167s, validation=0.0092s
- Ground truth: injected=5, detected=5
- Precision/Recall: P=1.0000, R=1.0000 (TP=5, FP=0, FN=0)
- Complexity: O(A) — scan activities for wasAssociatedWith
- Sample injected faults:

```json
[
  {
    "rule_id": "R3",
    "action": "removed_wasAssociatedWith",
    "details": {
      "activity": "http://kg.workflow.validation/activity/st_step_86719_0",
      "removed_agents": "http://kg.workflow.validation/agent/STAFF_MEMBER"
    }
  },
  {
    "rule_id": "R3",
    "action": "removed_wasAssociatedWith",
    "details": {
      "activity": "http://kg.workflow.validation/activity/st_step_86799_0",
      "removed_agents": "http://kg.workflow.validation/agent/STAFF_MEMBER"
    }
  },
  {
    "rule_id": "R3",
    "action": "removed_wasAssociatedWith",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_86791_19",
      "removed_agents": "http://kg.workflow.validation/agent/SYSTEM"
    }
  }
]
```

### 10declarations / R4

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r4_10declarations`
- Status: **PASS** (exact match)
- Size: traces=10, events=52, triples=787, xes_lines=442
- Times: conversion=0.0370s, load=0.0167s, validation=0.1413s
- Ground truth: injected=5, detected=5
- Precision/Recall: P=1.0000, R=1.0000 (TP=5, FP=0, FN=0)
- Complexity: O(E) — scan wasInformedBy edges + compare timestamps
- Sample injected faults:

```json
[
  {
    "rule_id": "R4",
    "action": "broke_wasInformedBy_temporal_order",
    "details": {
      "later_activity": "http://kg.workflow.validation/activity/st_step_86729_0",
      "earlier_activity": "http://kg.workflow.validation/activity/st_step_86728_0",
      "later_time_before": "2017-01-09T15:57:24+01:00",
      "earlier_time": "2017-01-09T15:57:21+01:00",
      "later_time_after": "2017-01-09T15:42:06+01:00"
    }
  },
  {
    "rule_id": "R4",
    "action": "broke_wasInformedBy_temporal_order",
    "details": {
      "later_activity": "http://kg.workflow.validation/activity/dd_declaration_86800_20",
      "earlier_activity": "http://kg.workflow.validation/activity/dd_declaration_86800_19",
      "later_time_before": "2017-02-13T17:32:14+01:00",
      "earlier_time": "2017-02-09T16:00:15+01:00",
      "later_time_after": "2017-02-09T15:50:43+01:00"
    }
  },
  {
    "rule_id": "R4",
    "action": "broke_wasInformedBy_temporal_order",
    "details": {
      "later_activity": "http://kg.workflow.validation/activity/dd_declaration_86791_19",
      "earlier_activity": "http://kg.workflow.validation/activity/st_step_86793_0",
      "later_time_before": "2017-01-10T09:34:44+01:00",
      "earlier_time": "2017-01-09T11:27:48+01:00",
      "later_time_after": "2017-01-09T10:37:31+01:00"
    }
  }
]
```

### 10declarations / R5

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r5_10declarations`
- Status: **PASS** (exact match)
- Size: traces=10, events=52, triples=787, xes_lines=442
- Times: conversion=0.0370s, load=0.0167s, validation=0.0073s
- Ground truth: injected=5, detected=5
- Precision/Recall: P=1.0000, R=1.0000 (TP=5, FP=0, FN=0)
- Complexity: O(P) — Payment Handled resource check
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
- Status: **PASS** (exact match)
- Size: traces=10, events=52, triples=787, xes_lines=442
- Times: conversion=0.0370s, load=0.0167s, validation=0.0071s
- Ground truth: injected=5, detected=5
- Precision/Recall: P=1.0000, R=1.0000 (TP=5, FP=0, FN=0)
- Complexity: O(P) — Payment Handled role check
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
- Status: **PASS** (exact match)
- Size: traces=10, events=52, triples=787, xes_lines=442
- Times: conversion=0.0370s, load=0.0167s, validation=0.0009s
- Ground truth: injected=5, detected=5
- Precision/Recall: P=1.0000, R=1.0000 (TP=5, FP=0, FN=0)
- Complexity: O(P · E_case) — BFS/ancestor search per Payment Handled over wasInformedBy
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

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r1_10declarations`
- Status: **PASS** (exact match)
- Size: traces=10500, events=56437, triples=849664, xes_lines=468572
- Times: conversion=37.6344s, load=25.6962s, validation=12.5788s
- Ground truth: injected=100, detected=100
- Precision/Recall: P=1.0000, R=1.0000 (TP=100, FP=0, FN=0)
- Complexity: O(A) — scan activities for belongsToCase cardinality
- Sample injected faults:

```json
[
  {
    "rule_id": "R1",
    "action": "removed_belongsToCase",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_123041_19",
      "removed_cases": "http://kg.workflow.validation/case/declaration_123041",
      "case_count_before": "1"
    }
  },
  {
    "rule_id": "R1",
    "action": "removed_belongsToCase",
    "details": {
      "activity": "http://kg.workflow.validation/activity/st_step_96437_0",
      "removed_cases": "http://kg.workflow.validation/case/declaration_96433",
      "case_count_before": "1"
    }
  },
  {
    "rule_id": "R1",
    "action": "removed_belongsToCase",
    "details": {
      "activity": "http://kg.workflow.validation/activity/st_step_89605_0",
      "removed_cases": "http://kg.workflow.validation/case/declaration_89602",
      "case_count_before": "1"
    }
  }
]
```

### full / R2

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r2_10declarations`
- Status: **PASS** (exact match)
- Size: traces=10500, events=56437, triples=849664, xes_lines=468572
- Times: conversion=37.6344s, load=25.6962s, validation=7.5511s
- Ground truth: injected=100, detected=100
- Precision/Recall: P=1.0000, R=1.0000 (TP=100, FP=0, FN=0)
- Complexity: O(A) — scan activities for startedAtTime presence
- Sample injected faults:

```json
[
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 123041",
      "event_id": "st_step 123044_0",
      "removed_values": "2018-09-20T19:30:18.000+02:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 96433",
      "event_id": "dd_declaration 96433_19",
      "removed_values": "2017-10-17T17:21:57.000+02:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 89602",
      "event_id": "dd_declaration 89602_20",
      "removed_values": "2017-03-16T17:31:06.000+01:00"
    }
  }
]
```

### full / R3

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r3_10declarations`
- Status: **PASS** (exact match)
- Size: traces=10500, events=56437, triples=849664, xes_lines=468572
- Times: conversion=37.6344s, load=25.6962s, validation=7.3313s
- Ground truth: injected=100, detected=100
- Precision/Recall: P=1.0000, R=1.0000 (TP=100, FP=0, FN=0)
- Complexity: O(A) — scan activities for wasAssociatedWith
- Sample injected faults:

```json
[
  {
    "rule_id": "R3",
    "action": "removed_wasAssociatedWith",
    "details": {
      "activity": "http://kg.workflow.validation/activity/dd_declaration_123041_19",
      "removed_agents": "http://kg.workflow.validation/agent/SYSTEM"
    }
  },
  {
    "rule_id": "R3",
    "action": "removed_wasAssociatedWith",
    "details": {
      "activity": "http://kg.workflow.validation/activity/st_step_96437_0",
      "removed_agents": "http://kg.workflow.validation/agent/STAFF_MEMBER"
    }
  },
  {
    "rule_id": "R3",
    "action": "removed_wasAssociatedWith",
    "details": {
      "activity": "http://kg.workflow.validation/activity/st_step_89605_0",
      "removed_agents": "http://kg.workflow.validation/agent/STAFF_MEMBER"
    }
  }
]
```

### full / R4

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r4_10declarations`
- Status: **PASS** (exact match)
- Size: traces=10500, events=56437, triples=849664, xes_lines=468572
- Times: conversion=37.6344s, load=25.6962s, validation=15.9040s
- Ground truth: injected=100, detected=100
- Precision/Recall: P=1.0000, R=1.0000 (TP=100, FP=0, FN=0)
- Complexity: O(E) — scan wasInformedBy edges + compare timestamps
- Sample injected faults:

```json
[
  {
    "rule_id": "R4",
    "action": "broke_wasInformedBy_temporal_order",
    "details": {
      "later_activity": "http://kg.workflow.validation/activity/st_step_134204_0",
      "earlier_activity": "http://kg.workflow.validation/activity/st_step_134203_0",
      "later_time_before": "2018-12-13T08:21:09+01:00",
      "earlier_time": "2018-12-11T12:26:55+01:00",
      "later_time_after": "2018-12-11T11:31:57+01:00"
    }
  },
  {
    "rule_id": "R4",
    "action": "broke_wasInformedBy_temporal_order",
    "details": {
      "later_activity": "http://kg.workflow.validation/activity/st_step_91453_0",
      "earlier_activity": "http://kg.workflow.validation/activity/st_step_91452_0",
      "later_time_before": "2017-12-08T11:49:16+01:00",
      "earlier_time": "2017-12-08T11:46:16+01:00",
      "later_time_after": "2017-12-08T11:24:43+01:00"
    }
  },
  {
    "rule_id": "R4",
    "action": "broke_wasInformedBy_temporal_order",
    "details": {
      "later_activity": "http://kg.workflow.validation/activity/st_step_89729_0",
      "earlier_activity": "http://kg.workflow.validation/activity/st_step_89730_0",
      "later_time_before": "2017-03-29T10:49:29+02:00",
      "earlier_time": "2017-03-29T10:49:19+02:00",
      "later_time_after": "2017-03-29T10:21:55+02:00"
    }
  }
]
```

### full / R5

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r5_10declarations`
- Status: **PASS** (exact match)
- Size: traces=10500, events=56437, triples=849664, xes_lines=468572
- Times: conversion=37.6344s, load=25.6962s, validation=2.1551s
- Ground truth: injected=100, detected=100
- Precision/Recall: P=1.0000, R=1.0000 (TP=100, FP=0, FN=0)
- Complexity: O(P) — Payment Handled resource check
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

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r5b_10declarations`
- Status: **PASS** (exact match)
- Size: traces=10500, events=56437, triples=849664, xes_lines=468572
- Times: conversion=37.6344s, load=25.6962s, validation=0.8921s
- Ground truth: injected=100, detected=100
- Precision/Recall: P=1.0000, R=1.0000 (TP=100, FP=0, FN=0)
- Complexity: O(P) — Payment Handled role check
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

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks\bench_r6_10declarations`
- Status: **PASS** (violations 109 >= applied 100 (+9 pre-existing invalid payments))
- Size: traces=10500, events=56437, triples=849664, xes_lines=468572
- Times: conversion=37.6344s, load=25.6962s, validation=2.7803s
- Ground truth: injected=100, detected=109
- Precision/Recall: P=0.9174, R=1.0000 (TP=100, FP=9, FN=0)
- Complexity: O(P · E_case) — BFS/ancestor search per Payment Handled over wasInformedBy
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

## Precision / recall notes

P/R are computed by matching injected corruption entity keys to detected violation entity keys (activity / payment / wasInformedBy edge). For R6 on full, false positives include the 9 baseline invalid payments above — they are real rule failures, not validator errors. Where conversion stats were missing on older benchmarks, traces/events/conversion time are `n/a` unless re-measured from the stored TTL (triples + load time).
## Combined all-rules benchmarks

Updated: `2026-07-22T11:27:27.688474+00:00`

These benchmarks inject **all rules together** on one KG (same per-rule counts as the isolated experiments: 5 on 10declarations, 100 on full; seed `42`). Validation then runs **all rules** on that KG.

Because corruptions interact, detected violations are expected to be **≥ injected** per rule (collateral). Entity-level recall of injected faults should still be 1.0; precision drops when collateral/baseline violations appear.

Combined suites passed verification: **2/2**.

### Combined suite overview

| Dataset | Traces | Events | Triples | Conv (s) | Load (s) | Val total (s) | Injected | Detected | Status |
|---------|--------|--------|---------|----------|----------|---------------|----------|----------|--------|
| 10declarations | 10 | 52 | 772 | 0.0438 | 0.0172 | 0.2150 | 35 | 52 | PASS |
| full | 10500 | 56437 | 849364 | 59.9502 | 46.3802 | 39.3640 | 700 | 1121 | PASS |

### Per-rule results on combined benchmarks

| Dataset | Rule | Injected | Detected | Extra | Val (s) | P | R | Status |
|---------|------|----------|----------|-------|---------|---|---|--------|
| 10declarations | R1 | 5 | 5 | 0 | 0.1439 | 1.0000 | 1.0000 | PASS |
| 10declarations | R2 | 5 | 7 | 2 | 0.0097 | 0.7143 | 1.0000 | PASS |
| 10declarations | R3 | 5 | 7 | 2 | 0.0175 | 0.7143 | 1.0000 | PASS |
| 10declarations | R4 | 5 | 14 | 9 | 0.0274 | 0.3571 | 1.0000 | PASS |
| 10declarations | R5 | 5 | 5 | 0 | 0.0090 | 1.0000 | 1.0000 | PASS |
| 10declarations | R5B | 5 | 5 | 0 | 0.0065 | 1.0000 | 1.0000 | PASS |
| 10declarations | R6 | 5 | 9 | 4 | 0.0009 | 0.5556 | 1.0000 | PASS |
| full | R1 | 100 | 100 | 0 | 8.6631 | 1.0000 | 1.0000 | PASS |
| full | R2 | 100 | 138 | 38 | 4.2650 | 0.7246 | 1.0000 | PASS |
| full | R3 | 100 | 138 | 38 | 4.3271 | 0.7246 | 1.0000 | PASS |
| full | R4 | 100 | 323 | 223 | 16.5089 | 0.3106 | 1.0000 | PASS |
| full | R5 | 100 | 100 | 0 | 2.1627 | 1.0000 | 1.0000 | PASS |
| full | R5B | 100 | 100 | 0 | 1.0086 | 1.0000 | 1.0000 | PASS |
| full | R6 | 100 | 222 | 122 | 2.4283 | 0.4505 | 1.0000 | PASS |

### Comparison: isolated vs combined (detected counts)

Isolated = one-rule benchmarks from the earlier section. Combined extras are mainly collateral across rules (plus the 9 baseline R6 payments on full).

| Dataset | Rule | Isolated detected | Combined detected | Δ |
|---------|------|-------------------|-------------------|---|
| 10declarations | R1 | 5 | 5 | 0 |
| 10declarations | R2 | 5 | 7 | 2 |
| 10declarations | R3 | 5 | 7 | 2 |
| 10declarations | R4 | 5 | 14 | 9 |
| 10declarations | R5 | 5 | 5 | 0 |
| 10declarations | R5B | 5 | 5 | 0 |
| 10declarations | R6 | 5 | 9 | 4 |
| full | R1 | 100 | 100 | 0 |
| full | R2 | 100 | 138 | 38 |
| full | R3 | 100 | 138 | 38 |
| full | R4 | 100 | 323 | 223 |
| full | R5 | 100 | 100 | 0 |
| full | R5B | 100 | 100 | 0 |
| full | R6 | 109 | 222 | 113 |

### Combined detail: 10declarations

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks/bench_all_10declarations`
- Validation report: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\output\per_rule_validation\val_all_10declarations\validation.json`
- Size: traces=10, events=52, triples=772
- Times: conversion=0.0438s, load=0.0172s, validation_total=0.2150s
- Totals: injected=35, detected=52
- **R1**: injected=5, detected=5, val=0.1439s, P=1.0000, R=1.0000, issues={'missing_belongsToCase': 5} — detected 5 >= applied 5
- **R2**: injected=5, detected=7, val=0.0097s, P=0.7143, R=1.0000, issues={'missing_startedAtTime': 7} — detected 7 >= applied 5 (+2 collateral/baseline)
- **R3**: injected=5, detected=7, val=0.0175s, P=0.7143, R=1.0000, issues={'missing_agent_association': 7} — detected 7 >= applied 5 (+2 collateral/baseline)
- **R4**: injected=5, detected=14, val=0.0274s, P=0.3571, R=1.0000, issues={'missing_startedAtTime_on_informed_activity': 1, 'non_monotonic_wasInformedBy': 7, 'missing_startedAtTime_on_informing_activity': 6} — detected 14 >= applied 5 (+9 collateral/baseline)
- **R5**: injected=5, detected=5, val=0.0090s, P=1.0000, R=1.0000, issues={'payment_not_handled_by_system': 5} — detected 5 >= applied 5
- **R5B**: injected=5, detected=5, val=0.0065s, P=1.0000, R=1.0000, issues={'payment_handled_by_employee': 5} — detected 5 >= applied 5
- **R6**: injected=5, detected=9, val=0.0009s, P=0.5556, R=1.0000, issues={'invalid_payment_provenance_chain': 9} — detected 9 >= applied 5 (+4 collateral/baseline)

- Sample injected faults (first 5 across rules):

```json
[
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 86716",
      "event_id": "dd_declaration 86716_20",
      "removed_values": "2017-01-16T17:32:14.000+01:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 86795",
      "event_id": "dd_declaration 86795_19",
      "removed_values": "2017-03-06T14:07:25.000+01:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 86791",
      "event_id": "st_step 86793_0",
      "removed_values": "2017-01-09T11:27:48.000+01:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 86720",
      "event_id": "st_step 86724_0",
      "removed_values": "2017-01-19T16:13:16.000+01:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 86731",
      "event_id": "dd_declaration 86731_20",
      "removed_values": "2017-01-16T17:32:14.000+01:00"
    }
  }
]
```

### Combined detail: full

- Benchmark: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\benchmarks/bench_all_full`
- Validation report: `C:\Valantis\JetBrains\projects\isl\KGBasedWorkflowValidation\output\per_rule_validation\val_all_full\validation.json`
- Size: traces=10500, events=56437, triples=849364
- Times: conversion=59.9502s, load=46.3802s, validation_total=39.3640s
- Totals: injected=700, detected=1121
- **R1**: injected=100, detected=100, val=8.6631s, P=1.0000, R=1.0000, issues={'missing_belongsToCase': 100} — detected 100 >= applied 100
- **R2**: injected=100, detected=138, val=4.2650s, P=0.7246, R=1.0000, issues={'missing_startedAtTime': 138} — detected 138 >= applied 100 (+38 collateral/baseline)
- **R3**: injected=100, detected=138, val=4.3271s, P=0.7246, R=1.0000, issues={'missing_agent_association': 138} — detected 138 >= applied 100 (+38 collateral/baseline)
- **R4**: injected=100, detected=323, val=16.5089s, P=0.3106, R=1.0000, issues={'missing_startedAtTime_on_informed_activity': 33, 'non_monotonic_wasInformedBy': 152, 'missing_startedAtTime_on_informing_activity': 138} — detected 323 >= applied 100 (+223 collateral/baseline)
- **R5**: injected=100, detected=100, val=2.1627s, P=1.0000, R=1.0000, issues={'payment_not_handled_by_system': 100} — detected 100 >= applied 100
- **R5B**: injected=100, detected=100, val=1.0086s, P=1.0000, R=1.0000, issues={'payment_handled_by_employee': 100} — detected 100 >= applied 100
- **R6**: injected=100, detected=222, val=2.4283s, P=0.4505, R=1.0000, issues={'invalid_payment_provenance_chain': 222} — detected 222 >= applied 100 (+122 collateral/baseline)

- Sample injected faults (first 5 across rules):

```json
[
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 123041",
      "event_id": "st_step 123044_0",
      "removed_values": "2018-09-20T19:30:18.000+02:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 96433",
      "event_id": "dd_declaration 96433_19",
      "removed_values": "2017-10-17T17:21:57.000+02:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 89602",
      "event_id": "dd_declaration 89602_20",
      "removed_values": "2017-03-16T17:31:06.000+01:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 131287",
      "event_id": "st_step 131291_0",
      "removed_values": "2018-11-08T14:37:41.000+01:00"
    }
  },
  {
    "rule_id": "R2",
    "action": "removed_time_timestamp",
    "details": {
      "trace_id": "declaration 109087",
      "event_id": "dd_declaration 109087_19",
      "removed_values": "2018-03-15T22:15:37.000+01:00"
    }
  }
]
```

### Combined-benchmark notes

- **Verification criterion**: per rule, `detected >= applied` and entity-level recall of injected faults = 1.0 (no false negatives).
- **Precision < 1** is expected here: collateral from other rules and (on full R6) the 9 pre-existing invalid payments count as FP relative to that rule's injection set.
- R2 XES timestamp removal can also feed R4 (`missing_startedAtTime_on_*`) as collateral.
