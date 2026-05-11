# Quickstart: Knowledge Sync Pivot

## Live Command Center
1. Invite **DanaTimmer** to your private Discord server.
2. Get the `channel_id` of your command channel.
3. Run the bot:
   ```bash
   python atlas_discord_bot.py --token "..." --channel <YOUR_PRIVATE_CHANNEL_ID>
   ```
4. Post a rule to test:
   ```text
   rule: Always identify the hand holding the object first.
   ```
5. Observe the bot appending to the context pack and triggering the Vertex sync.

## Manual Batch Ingestion
1. Use `DiscordChatExporter` to export a channel to `knowledge.json`.
2. Run the ingestion tool:
   ```bash
   python atlas_knowledge_ingest.py --file knowledge.json
   ```
3. The tool will deduplicate and append new knowledge to `prompts/atlas_vertex_context_pack.txt`.
