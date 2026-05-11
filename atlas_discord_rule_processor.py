"""Process Discord export into golden rules for the AI pipeline."""
import json
import re
from pathlib import Path
from datetime import datetime

EXPORT_FILE = Path("outputs/discord_full_export.json")
GOLDEN_RULES_FILE = Path("prompts/golden_rules.md")

# Patterns that indicate a message contains a rule or labeling instruction
RULE_KEYWORDS = [
    "hold", "label", "segment", "annotation", "annotate", "required",
    "must be", "must label", "not acceptable", "key rule", "important",
    "effective immediately", "going forward", "reminder", "clarification",
    "update", "do not", "always", "never", "example",
]

def is_rule_message(content: str) -> bool:
    """Check if a message likely contains labeling rules."""
    lower_content = content.lower()
    # Must contain at least 2 rule keywords
    matches = sum(1 for kw in RULE_KEYWORDS if kw in lower_content)
    return matches >= 3

def extract_rules_from_message(msg: dict) -> list:
    """Extract individual rules from a Discord message."""
    rules = []
    content = msg["content"]
    author = msg["author"]
    timestamp = msg.get("timestamp", "")
    
    # Split by newlines and look for rule-like lines
    lines = content.split("\n")
    current_rule = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_rule:
                rules.append({
                    "text": "\n".join(current_rule),
                    "author": author,
                    "timestamp": timestamp,
                    "source_id": msg["id"],
                })
                current_rule = []
            continue
        current_rule.append(stripped)
    
    if current_rule:
        rules.append({
            "text": "\n".join(current_rule),
            "author": author,
            "timestamp": timestamp,
            "source_id": msg["id"],
        })
    
    return rules

def process_discord_export():
    """Main processing pipeline."""
    if not EXPORT_FILE.exists():
        print(f"ERROR: {EXPORT_FILE} not found.")
        return
    
    messages = json.loads(EXPORT_FILE.read_text(encoding="utf-8"))
    print(f"Loaded {len(messages)} messages from Discord export.")
    
    # Filter to rule-relevant messages
    rule_messages = [m for m in messages if is_rule_message(m["content"])]
    print(f"Found {len(rule_messages)} messages containing labeling rules.")
    
    # Extract rules
    all_rules = []
    for msg in rule_messages:
        rules = extract_rules_from_message(msg)
        all_rules.extend(rules)
    
    print(f"Extracted {len(all_rules)} rule segments.")
    
    # Append to golden_rules.md
    new_section = f"\n\n## DISCORD-EXTRACTED RULES ({datetime.utcnow():%Y-%m-%d})\n"
    new_section += f"*Auto-extracted from {len(rule_messages)} Discord messages.*\n\n"
    
    for i, rule in enumerate(rule_messages, 1):
        new_section += f"### Discord Rule #{i} (by {rule['author']}, {rule.get('timestamp', '')[:10]})\n"
        # Clean up the content for markdown
        content = rule["content"]
        # Remove @mentions
        content = re.sub(r"@\w+(?:\s+\w+)*", "", content)
        # Remove timestamps at end
        content = re.sub(r"\n\w+day, \w+ \d+, \d{4} at.*$", "", content)
        new_section += f"{content.strip()}\n\n"
    
    # Write to golden_rules.md
    with open(GOLDEN_RULES_FILE, "a", encoding="utf-8") as f:
        f.write(new_section)
    
    print(f"\n[OK] Appended {len(rule_messages)} rules to {GOLDEN_RULES_FILE}")
    
    # Save processed rules as JSON for future reference
    output_path = Path("outputs/discord_processed_rules.json")
    output_path.write_text(json.dumps(rule_messages, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Saved processed rules to {output_path}")

if __name__ == "__main__":
    process_discord_export()
