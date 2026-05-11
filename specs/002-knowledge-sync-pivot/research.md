# Research: Knowledge Sync Pivot

## Decision: Command-Based Private Sync
- **Rationale**: Using a private server (Command Room) allows full administrator permissions for the DanaTimmer bot without interfering with the restricted public server.
- **Alternatives**: Using a Self-Bot (Rejected due to Discord ToS and account risk). Asking for Admin on the main server (Rejected as per User request).

## Decision: DiscordChatExporter for Bulk Ingestion
- **Rationale**: `DiscordChatExporter` is the industry standard for safe, high-volume message extraction. It allows the user to export data they can see but can't "bot" live.
- **Alternatives**: Custom scraping (Rejected - fragile and risky).

## Research Findings
- `discord.py` can fetch historical messages across any channel the bot is currently in.
- `DiscordChatExporter` generates consistent JSON formats with `MessageId`, `Content`, and `Timestamp`. 
- Deduplication is best handled by storing a `Set` of ingested `MessageIds` or searching for the ID in the context pack before appending.
