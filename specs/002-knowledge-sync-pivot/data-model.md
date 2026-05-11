# Data Model: Knowledge Sync Pivot

## Knowledge Entry
Represents a single piece of "Golden Rule" or correction knowledge ingested into the Atlas system.

- **ID**: Discord Message ID (Primary deduplication key)
- **Content**: The raw text of the rule/correction
- **Timestamp**: UTC time of message creation
- **Source**: Server/Channel name where it originated
- **Author**: User who posted the rule

## Atlas Knowledge Pack (Storage)
Current implementation uses a text file (`atlas_vertex_context_pack.txt`).
- **Format**: 
  ```text
  [YYYY-MM-DD HH:MM:SS] [Source] [Author]
  Content...
  ---
  ```
- **Validation**: Ingestion must ensure no duplicate IDs are appended.
