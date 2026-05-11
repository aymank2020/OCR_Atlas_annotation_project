# Implementation Plan: Knowledge Sync Pivot

**Branch**: `002-knowledge-sync-pivot` | **Date**: 2026-03-23 | **Spec**: [specs/002-knowledge-sync-pivot/spec.md](file:///e:/OCR_annotation_Atlas/specs/002-knowledge-sync-pivot/spec.md)

## Summary

This plan pivots the Atlas Knowledge synchronization strategy from passive monitoring of restricted public Discord servers to a two-pronged approach:
1. **Private Command Center**: A user-owned Discord server where the bot has full permissions to listen for "Golden Rules" and trigger instant syncs.
2. **Bulk Ingestion Utility**: A new CLI tool to process historical data exported via `DiscordChatExporter`, enabling the ingestion of knowledge from servers where bot access is restricted.
3. **Perfect Automation Loop**: A scheduled orchestrator that automates export and ingestion on a recurring 8-hour cycle.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.10+  
**Primary Dependencies**: `discord.py`, `google-cloud-aiplatform`, `python-dotenv`  
**Storage**: Text-based Knowledge Packs (`.txt`), Git repository  
**Testing**: manual verification, `pytest` for ingestion logic  
**Target Platform**: Ubuntu VPS / Windows Local  
**Project Type**: CLI / Bot Service  
**Performance Goals**: <60s end-to-end sync for live commands  
**Constraints**: Avoid PII in context packs, ensure gapless timestamped entries  
**Scale/Scope**: Support 10,000+ historical message ingestion

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **P5 (Security)**: `DiscordChatExporter` tokens (User Tokens) must NEVER be stored in the codebase or logged.
- **P6 (Visibility)**: Ingestion errors (broken JSON) must be logged and reported to CLI.
- **P7 (Timezone)**: Use `datetime.now(timezone.utc)` for all sync timestamps.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
```text
e:\OCR_annotation_Atlas\
├── atlas_discord_bot.py         # [MODIFY] Refactored for Command Center logic
├── atlas_knowledge_ingest.py    # [NEW] Manual ingestion CLI
├── atlas_auto_harvest.sh        # [NEW] US3 Automation Orchestrator
├── prompts/
│   └── atlas_vertex_context_pack.txt # [DATA] Target for all knowledge
└── tests/
    └── test_ingest.py           # [NEW] Unit tests for deduplication
```

**Structure Decision**: Refactoring the existing bot for command-and-control while adding a dedicated utility for batch processing.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
