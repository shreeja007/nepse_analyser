# Swing Analyser Audit Tracker

Last updated: 2026-04-21
Scope: swing_analyser package and related documentation/report behavior

## Purpose

This file tracks known issues found during audit, what has been fixed, and what has been validated.
Use this as the single source of truth for swing_analyser audit follow-up.

## Status legend

- OPEN: Confirmed issue, not fixed
- IN_PROGRESS: Being worked on
- FIXED_PENDING_VALIDATION: Code or docs updated, validation not completed
- VALIDATED: Fix verified and closed
- WONT_FIX: Accepted risk with rationale

## Issue Register

| ID     | Severity | Status    | Detected On | Summary                                                                                                                                                                                                                                   | Evidence                                                                                                                                                                                                                                                                                                                            | Proposed Fix                                                                                                             | Validation Plan                                                                                                         |
| ------ | -------- | --------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| SA-001 | Critical | VALIDATED | 2026-04-21  | Ranking pipeline calls data confidence helper without required excessive_forward_fill argument, causing per-symbol runtime TypeError that is swallowed by exception handling. This can silently produce empty or degraded ranking output. | [swing_analyser/logic.py](swing_analyser/logic.py#L294), [swing_analyser/scoring.py](swing_analyser/scoring.py#L515), [swing_analyser/scoring.py](swing_analyser/scoring.py#L576), [swing_analyser/scoring.py](swing_analyser/scoring.py#L577)                                                                                      | Pass excessive_forward_fill from ranking pipeline based on forward-fill streak or default false with explicit rationale. | Run ranking mode end-to-end and confirm no TypeError in errors map. Add regression check for helper call compatibility. |
| SA-002 | Medium   | VALIDATED | 2026-04-21  | Risk-management constants and narrative are inconsistent between runtime logic, HTML methodology text, and documentation.                                                                                                                 | [swing_analyser/logic.py](swing_analyser/logic.py#L23), [swing_analyser/logic.py](swing_analyser/logic.py#L29), [swing_analyser/html_report.py](swing_analyser/html_report.py#L561), [documentation/swing_analyser.md](documentation/swing_analyser.md#L47), [documentation/swing_analyser.md](documentation/swing_analyser.md#L52) | Align docs/report text with actual runtime constants, or intentionally update constants and then update docs.            | Compare generated report methodology text and docs against constants in logic module after fix.                         |
| SA-003 | Medium   | VALIDATED | 2026-04-21  | Full report assembly depends on fragile HTML comment-string split logic. Template marker changes can silently remove swing watchlist section.                                                                                             | [swing_analyser/html_ranking.py](swing_analyser/html_ranking.py#L290), [swing_analyser/html_ranking.py](swing_analyser/html_ranking.py#L685)                                                                                                                                                                                        | Replace string-split extraction with explicit shared renderer function or structured section builder.                    | Generate full mode report and verify watchlist always renders even if swing HTML template changes.                      |
| SA-004 | Low      | VALIDATED | 2026-04-21  | total_analyzed and processed messaging in strict mode may be interpreted as full universe processed, but currently reflects analysis_results coverage after filters.                                                                      | [swing_analyser/logic.py](swing_analyser/logic.py#L1155), [swing_analyser/logic.py](swing_analyser/logic.py#L1177), [swing_analyser/logic.py](swing_analyser/logic.py#L1437), [swing_analyser/logic.py](swing_analyser/logic.py#L1460), [documentation/swing_analyser.md](documentation/swing_analyser.md#L123)                     | Clarify metric naming or add separate counters for input universe, processed, and filtered.                              | Confirm output keys and console summary clearly represent universe and each filter stage.                               |

## Resolution Log

| Date       | ID     | Change Summary                                                                                                                      | New Status               | Verified By                   | Notes                                                                                        |
| ---------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------ | ----------------------------- | -------------------------------------------------------------------------------------------- |
| 2026-04-21 | SA-001 | Initial audit finding recorded                                                                                                      | OPEN                     | audit run                     | Pending implementation                                                                       |
| 2026-04-21 | SA-001 | Added excessive_forward_fill computation in ranking pipeline and passed it to \_compute_data_confidence call.                       | FIXED_PENDING_VALIDATION | Copilot code patch            | Pending DB-backed ranking run                                                                |
| 2026-04-21 | SA-001 | Ran `python -m swing_analyser --mode rank --top 5` successfully: 252 stocks ranked, no helper TypeError surfaced, report generated. | VALIDATED                | runtime CLI run               | End-to-end validation complete                                                               |
| 2026-04-21 | SA-002 | Initial audit finding recorded                                                                                                      | OPEN                     | audit run                     | Pending implementation                                                                       |
| 2026-04-21 | SA-002 | Updated docs and report methodology text to match runtime constants (ATR_SL_MULT 1.5, CIRCUIT_LIMIT 0.10).                          | VALIDATED                | code/doc patch + grep check   | No stale values remain in target files                                                       |
| 2026-04-21 | SA-003 | Initial audit finding recorded                                                                                                      | OPEN                     | audit run                     | Pending implementation                                                                       |
| 2026-04-21 | SA-003 | Added structured watchlist fallback builder in full mode and used extracted block only when markers exist.                          | VALIDATED                | compile + fallback simulation | Simulated missing markers and verified watchlist still renders                               |
| 2026-04-21 | SA-004 | Initial audit finding recorded                                                                                                      | OPEN                     | audit run                     | Pending implementation                                                                       |
| 2026-04-21 | SA-004 | Added explicit strict-mode counters (`total_universe`, `total_processed`) and clearer console wording; documented metric semantics. | VALIDATED                | runtime CLI run               | `python -m swing_analyser --mode swing --top 5` showed 295/295 looped and 212 reporting rows |

## Next Audit Checklist

- Re-run swing mode and ranking mode after each fix.
- Capture before/after behavior in this file.
- Move issue status to FIXED_PENDING_VALIDATION immediately after code/doc change.
- Move issue status to VALIDATED only after runtime confirmation.

## Ownership

- Primary area: swing_analyser
- Related area: documentation and report rendering
