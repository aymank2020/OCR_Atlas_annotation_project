# Feature Specification: Knowledge Sync Pivot

**Feature Branch**: `002-knowledge-sync-pivot`  
**Created**: 2026-03-23  
**Status**: Draft  
**Input**: Pivot from monitoring a public server to a private "Control Room" and ingesting manual exports from DiscordChatExporter.

## User Scenarios & Testing *(mandatory)*

<!--
  IMPORTANT: User stories should be PRIORITIZED as user journeys ordered by importance.
  Each user story/journey must be INDEPENDENTLY TESTABLE - meaning if you implement just ONE of them,
  you should still have a viable MVP (Minimum Viable Product) that delivers value.
  
  Assign priorities (P1, P2, P3, etc.) to each story, where P1 is the most critical.
  Think of each story as a standalone slice of functionality that can be:
  - Developed independently
  - Tested independently
  - Deployed independently
  - Demonstrated to users independently
-->

### User Story 1 - Private Command Center (Priority: P1)

As the project owner, I want to host a private Discord server where I have full admin rights, invite the DanaTimmer bot, and paste specific rules or corrections into a dedicated channel.

**Why this priority**: Essential to bypass the "Manage Server" permission roadblock on the main annotation server. Allows for immediate, authorized knowledge synchronization.

**Independent Test**: Create a private server, invite bot, paste a rule, and verify Git/Vertex sync triggers successfully.

**Acceptance Scenarios**:

1. **Given** the bot is in a private server channel, **When** a user pastes a message containing a policy keyword (e.g., "rule:", "correction:"), **Then** the bot appends it to `atlas_vertex_context_pack.txt` and triggers full sync.
2. **Given** the bot is in a private server, **When** the 5-minute timer triggers, **Then** the bot exports the channel history to `data/discord_history_export.txt`.

---

### User Story 2 - Manual History Ingestion (Priority: P2)

As a researcher, I want to use the `DiscordChatExporter` tool to manually dump history from public servers and have a script that automatically parses these exports (JSON/TXT) into the Atlas Knowledge base.

**Why this priority**: Enables leveraging large amounts of historical knowledge from servers where bot-based "live" listening is blocked.

**Independent Test**: Provide a sample JSON export from DiscordChatExporter and verify that the ingestion script correctly extracts and deduplicates entries into the context pack.

**Acceptance Scenarios**:

1. **Given** a DiscordChatExporter JSON file, **When** the ingestion script is run, **Then** it extracts message content and metadata into the shared context pack.

---

### User Story 3 - The Perfect Automation Loop (Priority: P2)

As a Project Manager, I want the system to automatically harvest Discord history, extract key rules, and sync them every 8 hours so the knowledge base stays fresh without manual intervention.

**Why this priority**: Eliminates manual labor and ensures the AI "brain" is always updated with the latest team decisions without requiring human exports/imports.

**Independent Test**: Configure the automation script with a test channel, run it, and verify it performs the export, ingestion, and project-sync cycle correctly.

**Acceptance Scenarios**:

1. **Given** a valid User Token and Channel ID, **When** the 8-hour timer triggers, **Then** the system exports JSON history, runs the ingestor, and triggers a full project sync.

### Edge Cases

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right edge cases.
-->

- What happens when a duplicate message is pasted or re-exported? (System should deduplicate by ID).
- How does the system handle very large manual export files? (Chunked processing).
- What if the manual export contains sensitive user data? (Heuristic filtering).

## Requirements *(mandatory)*

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right functional requirements.
-->

### Functional Requirements

- **FR-001**: Bot MUST successfully join any guild where the owner has invited it with `bot` scopes.
- **FR-002**: Bot MUST prioritize messages from the "Private Command Center" channel for instant synchronization.
- **FR-003**: System MUST provide a standalone CLI tool/script to ingest `DiscordChatExporter` JSON exports.
- **FR-004**: Ingestion script MUST deduplicate messages by Discord Message ID to prevent context pack bloating.
- **FR-005**: All ingested knowledge MUST be formatted into `prompts/atlas_vertex_context_pack.txt` with timestamp and source markers.
- **FR-006**: System MUST support an automated 8-hour harvesting cycle using `DiscordChatExporter.Cli` on the Linux VPS.

*Example of marking unclear requirements:*

- **FR-006**: System MUST authenticate users via [NEEDS CLARIFICATION: auth method not specified - email/password, SSO, OAuth?]
- **FR-007**: System MUST retain user data for [NEEDS CLARIFICATION: retention period not specified]

### Key Entities *(include if feature involves data)*

- **[Entity 1]**: [What it represents, key attributes without implementation]
- **[Entity 2]**: [What it represents, relationships to other entities]

## Success Criteria *(mandatory)*

<!--
  ACTION REQUIRED: Define measurable success criteria.
  These must be technology-agnostic and measurable.
-->

### Measurable Outcomes

- **SC-001**: Knowledge from private command room is synced to Vertex/Git within 60 seconds of posting.
- **SC-002**: Ingestion script processes 1,000 exported messages in under 5 seconds.
- **SC-003**: Zero duplicate messages in the context pack after multiple overlapping ingestions.
