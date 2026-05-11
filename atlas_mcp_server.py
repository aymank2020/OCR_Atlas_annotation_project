import os
import subprocess
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server for the Eigent Workforce
mcp = FastMCP("Atlas AI Workforce")

@mcp.tool()
def trigger_stealth_scraper() -> str:
    """
    Agent Role: Scout
    Purpose: Trigger the Stealth Discord Scraper to harvest new rules from Level 3 Discord.
    """
    try:
        result = subprocess.run(
            ["python", "atlas_stealth_scraper.py"], 
            capture_output=True, text=True, timeout=600
        )
        return f"Scraper execution completed. Tail log: {result.stdout[-500:]}"
    except Exception as e:
        return f"Error running scraper: {str(e)}"

@mcp.tool()
def update_rag_database() -> str:
    """
    Agent Role: Librarian
    Purpose: Updates the policy RAG database with recently harvested rules.
    """
    try:
        result = subprocess.run(
            ["python", "atlas_knowledge_collector.py", "--discord", "--rag"], 
            capture_output=True, text=True, timeout=600
        )
        return f"RAG Database updated successfully! Log: {result.stdout[-500:]}"
    except Exception as e:
        return f"Error updating RAG DB: {str(e)}"

@mcp.tool()
def review_single_video(episode_id: str) -> str:
    """
    Agent Role: Auditor
    Purpose: Run a comprehensive 4-way evaluation on a specific video.
    """
    try:
        env = {**os.environ, "EPISODE_ID": episode_id}
        result = subprocess.run(
            ["bash", "./run_single_episode_4way.sh"], 
            env=env, capture_output=True, text=True, timeout=1200
        )
        return f"Episode {episode_id} processed. Summary: {result.stdout[-500:]}"
    except Exception as e:
        return f"Error reviewing video {episode_id}: {str(e)}"

@mcp.tool()
def dispatch_discord_question(question: str) -> str:
    """
    Agent Role: Diplomat
    Purpose: Immediately dispatches an urgent domain question to human admins.
    """
    try:
        result = subprocess.run(
            ["python", "atlas_question_dispatcher.py", "--send", question], 
            capture_output=True, text=True, timeout=30
        )
        return f"Question sent to Discord! Admins have been notified."
    except Exception as e:
        return f"Failed to dispatch question: {str(e)}"

if __name__ == "__main__":
    # Eigent will start this server and reflect these tools for the configured Agents.
    print("[MCP] Starting Atlas AI Workforce Server...")
    mcp.run()
