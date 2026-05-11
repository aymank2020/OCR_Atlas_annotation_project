# Feature Specification: Unified Atlas Command Hub

**Feature Branch**: `004-unified-command-hub`  
**Created**: 2026-03-29  
**Status**: Draft  
**Input**: User description: "Unified Atlas Command Hub: a master localhost dashboard with fixed ports for all Atlas services (Scribe, Control Center, Pipeline Dashboard), plus integrated WhatsApp/Telegram messaging for remote VPS control"

## Overview

Atlas currently has multiple standalone dashboards and services, each requiring the user to manually start them on ad-hoc ports. This feature creates a single **Master Hub** that:

1. Provides a unified landing page with navigation to all Atlas services
2. Assigns permanent, fixed TCP ports to every service
3. Can start/stop all services from one place
4. Integrates WhatsApp and Telegram as remote command channels for VPS operations (inspired by OpenClaw agent concepts, but built securely within the Atlas ecosystem)

### Assumptions

- All services run on the local Windows PC (HP Victus, i7-13700H, RTX 4050)
- VPS communication for messaging bots runs on DigitalOcean Ubuntu VPS (`157.245.186.95`)
- WhatsApp integration will use the WhatsApp Business Cloud API (webhook-based)
- Telegram integration will use the Telegram Bot API
- The existing `atlas_vps_commander.py` (Discord bot) serves as the architecture reference for messaging integrations
- Port range 8500-8510 is available on the local machine
- The hub itself will be a Streamlit application (consistent with existing Atlas dashboards)

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Master Hub Landing Page (Priority: P1)

As a developer, I want to open a single URL (`http://localhost:8500`) and see all Atlas services with their status (running/stopped), so I can navigate to any service with one click instead of remembering individual ports and run commands.

**Why this priority**: This is the core value proposition — eliminating the need to remember and manually start multiple services. Without this, the whole feature has no entry point.

**Independent Test**: Open `http://localhost:8500` in the browser and verify all service tiles are visible with correct port assignments and clickable links.

**Acceptance Scenarios**:

1. **Given** the hub is running, **When** I open `http://localhost:8500`, **Then** I see a dashboard with tiles for each Atlas service showing name, description, port, and status (running/stopped)
2. **Given** a service tile shows "Running", **When** I click the tile's "Open" button, **Then** a new browser tab opens at the correct service URL (e.g., `http://localhost:8501`)
3. **Given** a service tile shows "Stopped", **When** I click "Start", **Then** the service process starts and the tile updates to "Running" within 10 seconds

---

### User Story 2 — Fixed Port Registry (Priority: P1)

As a developer, I want every Atlas service to have a permanent, well-known port number defined in a single configuration file, so I never have port conflicts or forget which port a service uses.

**Why this priority**: Without fixed ports, the hub cannot reliably link to services. This is a prerequisite for US1.

**Independent Test**: Check `atlas_hub_config.yaml` and verify each service has a unique port. Start two services simultaneously and confirm no port conflicts.

**Acceptance Scenarios**:

1. **Given** the port registry exists in `atlas_hub_config.yaml`, **When** I read it, **Then** I see every service mapped to a unique port in the 8500-8510 range
2. **Given** two services are configured on different ports, **When** I start both simultaneously, **Then** both bind successfully without EADDRINUSE errors

---

### User Story 3 — Service Lifecycle Management (Priority: P2)

As a developer, I want to start, stop, and restart any Atlas service directly from the hub dashboard, so I don't need to open separate terminals for each service.

**Why this priority**: Significantly reduces friction of managing multi-service workflows, but requires US1 and US2 first.

**Independent Test**: From the hub, click "Start" on Atlas Scribe, verify the Streamlit process spawns. Click "Stop", verify the process terminates.

**Acceptance Scenarios**:

1. **Given** Atlas Scribe is stopped, **When** I click "Start" on its tile in the hub, **Then** a new Streamlit process starts on port 8501 and the tile status updates to "Running"
2. **Given** Atlas Scribe is running, **When** I click "Stop", **Then** the Streamlit process is terminated gracefully and the tile status updates to "Stopped"
3. **Given** any service crashes unexpectedly, **When** I refresh the hub, **Then** the tile accurately shows "Stopped" (not stale "Running")

---

### User Story 4 — Telegram Bot for Remote VPS Control (Priority: P2)

As a developer, I want to send commands to my VPS via a Telegram bot (e.g., `/status`, `/pull`, `/logs`, `/run`), so I can monitor and control Atlas pipeline operations from my phone without SSH.

**Why this priority**: Provides mobile-friendly remote access. Telegram Bot API is simpler and faster to implement than WhatsApp, making it a better first integration.

**Independent Test**: Send `/status` to the Telegram bot from any Telegram client and verify it returns VPS system info and solver status.

**Acceptance Scenarios**:

1. **Given** the Telegram bot is running on the VPS, **When** I send `/status`, **Then** I receive a message with disk space, process status, and last solver run time
2. **Given** code has been pushed to GitHub, **When** I send `/pull`, **Then** the VPS runs `git pull origin main` and replies with the result
3. **Given** the solver is running, **When** I send `/logs 20`, **Then** I receive the last 20 lines of `production.log`
4. **Given** an unauthorized Telegram user sends a command, **Then** the bot ignores it (only responds to whitelisted chat IDs)

---

### User Story 5 — WhatsApp Integration for Notifications (Priority: P3)

As a developer, I want to receive WhatsApp notifications when important events occur (solver complete, error, manual review needed), so I stay informed without checking dashboards.

**Why this priority**: Notification-only is simpler than full bidirectional control. WhatsApp Cloud API requires more setup (Meta business account, webhook verification) so it's lower priority than Telegram.

**Independent Test**: Trigger a test notification event and verify a WhatsApp message arrives on the configured phone number.

**Acceptance Scenarios**:

1. **Given** the WhatsApp notifier is configured, **When** a solver run completes, **Then** I receive a WhatsApp message with episode count and pass rate
2. **Given** a manual review is needed, **When** an episode is added to manual queue, **Then** I receive a WhatsApp alert with episode ID and reason
3. **Given** WhatsApp API is temporarily unavailable, **When** a notification fails, **Then** the error is logged but does not crash the solver pipeline

---

### Edge Cases

- What happens when the hub starts but a service's port is already occupied by another program? → Show an error badge on the tile with the conflicting process name
- What happens when the hub process itself crashes? → Services started by the hub continue running independently (they are separate processes)
- What happens when the Telegram bot receives an unrecognized command? → Reply with a help message listing available commands
- What happens when VPS SSH is unreachable from the Telegram bot? → Reply "VPS unreachable" and retry once after 30 seconds
- What happens when multiple messaging channels (Discord + Telegram) both issue a command simultaneously? → Each processes independently; no cross-channel locking needed

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a master hub dashboard accessible at a fixed URL (`http://localhost:8500`)
- **FR-002**: System MUST maintain a YAML configuration file (`atlas_hub_config.yaml`) mapping each service to a unique port
- **FR-003**: Hub MUST display real-time status (running/stopped) for each registered service by checking if the port is responding
- **FR-004**: Hub MUST provide start/stop controls for each service, spawning/terminating subprocesses
- **FR-005**: Hub MUST provide clickable links that open each running service in a new browser tab
- **FR-006**: System MUST include a Telegram bot script (`atlas_telegram_bot.py`) that runs on the VPS and accepts whitelisted commands
- **FR-007**: Telegram bot MUST support these commands: `/status`, `/pull`, `/logs [N]`, `/run [config]`, `/stop`, `/help`
- **FR-008**: Telegram bot MUST only respond to messages from whitelisted Telegram chat IDs (configured in `.env`)
- **FR-009**: System MUST include a WhatsApp notification module that sends alerts via WhatsApp Business Cloud API
- **FR-010**: WhatsApp notifier MUST be callable from any Atlas script via a simple function: `send_whatsapp_alert(message)`
- **FR-011**: All service ports MUST be defined in a single configuration file, eliminating hardcoded port numbers across scripts
- **FR-012**: Hub MUST show system resource metrics (CPU, RAM, disk) for the local machine

### Port Registry (Fixed Assignments)

| Port | Service | Script |
|------|---------|--------|
| 8500 | Atlas Command Hub (Master) | `atlas_command_hub.py` |
| 8501 | Atlas Scribe Dashboard | `atlas_scribe_dashboard.py` |
| 8502 | Atlas Control Center | `atlas_control_center.py` |
| 8503 | Atlas Pipeline Dashboard | `atlas_dashboard_gen.py` (served) |
| 8504 | Atlas Rules Viewer | `atlas_rules_viewer.html` (served) |
| 8505 | Atlas Review Viewer | `atlas_review_viewer_gen.py` (served) |
| 8506-8510 | Reserved for future services | — |

### Key Entities

- **Service**: Represents a registered Atlas dashboard/tool (name, port, script path, process ID, status, description)
- **Port Registry**: The canonical mapping of services to ports (stored in `atlas_hub_config.yaml`)
- **Telegram Command**: An inbound message from Telegram with sender ID, command, arguments, and timestamp
- **WhatsApp Notification**: An outbound message with recipient, template, parameters, and delivery status
- **Hub Session**: State of the hub including which services are running and their PIDs

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: User can access all Atlas services from a single URL within 3 clicks
- **SC-002**: All services start without port conflicts when launched from the hub simultaneously
- **SC-003**: Service status indicators reflect actual process state within 5 seconds of a change
- **SC-004**: Telegram bot responds to valid commands within 10 seconds
- **SC-005**: WhatsApp notifications are delivered within 30 seconds of the triggering event
- **SC-006**: Zero unauthorized command executions (only whitelisted users can control the VPS)
- **SC-007**: Hub startup time is under 5 seconds (excluding service pre-loading)
- **SC-008**: The port registry eliminates all hardcoded port numbers across Atlas scripts
