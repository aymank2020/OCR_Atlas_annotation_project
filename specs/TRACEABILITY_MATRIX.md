# Atlas Capture — Spec ↔ Code Traceability Matrix

> **Operation Phoenix Atlas — Sprint 9**
> Maps every Functional Requirement to its implementing code.

## Spec-001: 4-Way Episode Solver

| FR | Description | Implementing File(s) | Status |
|----|-------------|---------------------|--------|
| FR-001 | 4-Way Solver Pipeline | `atlas_web_auto_solver.py`, `pipeline_runner.py` | ✅ Implemented |
| FR-002 | Quality Gate (≥95%) | `submit_gate.py` | ✅ Implemented |
| FR-003 | 5-Check Submit Gate | `submit_gate.py` | ✅ Implemented |
| FR-004 | Hallucination Detection | `atlas_triplet_compare.py` | ✅ Implemented |
| FR-005 | Label Start Verb Policy | `validator.py` | ✅ Implemented |
| FR-006 | Disallowed Tool Terms | `validator.py`, `atlas/shared/constants.py` | ✅ Implemented |
| FR-007 | Overlap Detection | `validator.py` | ✅ Implemented |
| FR-008 | Gap Detection | `validator.py` | ✅ Implemented |
| FR-009 | Auto-Repair Loop | `atlas_repair_loop.py` | ✅ Implemented |
| FR-010 | Cost Tracking | `cost_report.py` | ✅ Implemented |
| FR-011 | Dashboard | `atlas_dashboard_v2.py` | ✅ Implemented |
| FR-012 | Drive Sync | `run_production.sh` (Step 7) | ✅ Implemented |
| FR-013 | Context Pack Build | `atlas_build_vertex_fewshot.py` | ✅ Implemented |

## Spec-002: Knowledge Sync Pivot

| FR | Description | Implementing File(s) | Status |
|----|-------------|---------------------|--------|
| FR-001 | Private Command Center | `atlas_discord_bot.py` | ✅ Implemented |
| FR-002 | Manual Harvest Initiation | `.agent/workflows/knowledge-ingest.md` | ✅ Documented |
| FR-003 | DiscordChatExporter JSON Ingest | `atlas_knowledge_ingest.py` | ✅ Implemented |
| FR-004 | Pre-Purified Rules JSON Ingest | `atlas_knowledge_ingest.py` | ✅ Implemented (Sprint 0.5) |
| FR-005 | Deduplication by Message ID | `atlas_knowledge_ingest.py` | ✅ Implemented |
| FR-006 | Git + Vertex Sync | `src/sync/sync_utils.py` | ⚠️ Partial (Vertex Studio stub) |
| FR-007 | Context Pack Merge | `run_production.sh` (Step 2) | ✅ Implemented |

## Spec-003: AI Purifier

| FR | Description | Implementing File(s) | Status |
|----|-------------|---------------------|--------|
| FR-001 | Gemini-based Rule Extraction | `src/purify/knowledge_builder.py` | ✅ Implemented |
| FR-002 | Category Filtering | `atlas_knowledge_ingest.py` (`ALLOWED_RULE_CATEGORIES`) | ✅ Implemented |
| FR-003 | Batch Processing | `src/purify/knowledge_builder.py` | ✅ Implemented |
| FR-004 | Integration with Prod Pipeline | `run_production.sh` (Step 0) | ⚠️ Partial |

## Clean Architecture Modules (Operation Phoenix Atlas)

| Module | Layer | Purpose | Tests |
|--------|-------|---------|-------|
| `atlas/infra/config.py` | Infra | Pydantic config with fail-fast | `test_config.py` ✅ |
| `atlas/domain/models.py` | Domain | 8 Pydantic models (Episode, Segment, etc.) | `test_models.py` ✅ |
| `atlas/shared/logging.py` | Shared | JSON + Human formatters, `@log_spec` | `test_logging.py` ✅ |
| `atlas/infra/resilience.py` | Infra | Circuit breaker + retry backoff | `test_resilience.py` ✅ |
| `atlas/shared/constants.py` | Shared | Constants & forbidden terms | `test_shared_constants.py` ✅ |
| `atlas/shared/io.py` | Shared | File I/O utilities | `test_shared_io.py` ✅ |

## ⚠️ Gaps

1. `update_vertex_studio_prompt()` in `src/sync/sync_utils.py` — still a placeholder
2. AI Purifier not fully wired into `run_production.sh` Step 0
3. Domain models not yet adopted by existing pipeline files (Strangler Fig in progress)
