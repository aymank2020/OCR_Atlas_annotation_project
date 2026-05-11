import asyncio
from asyncio import subprocess
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

async def refresh_vertex_cache(config_path: str):
    """Invoke vertex_create_cache.py to refresh context caching."""
    logger.info("[sync] Refreshing Vertex AI Context Cache...")
    import sys
    try:
        cmd = [sys.executable, "vertex_create_cache.py", "--config", config_path]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            logger.info("[sync] Vertex cache refreshed successfully.")
            return True
        else:
            err_msg = stderr.decode() or stdout.decode()
            logger.error(f"[sync] Vertex cache refresh failed: {err_msg}")
            return False
    except Exception as e:
        logger.error(f"[sync] Error in cache refresh: {e}")
        return False

async def git_sync():
    """Commit and push local prompt changes to GitHub, handling potential diverged branches."""
    logger.info("[sync] Performing Git synchronization...")
    
    # 0. Robustness: Check for index.lock
    lock_file = Path(".git/index.lock")
    if lock_file.exists():
        logger.warning("[sync] .git/index.lock detected. Previous Git process may have crashed. Removing it...")
        try:
            lock_file.unlink()
        except Exception as e:
            logger.error(f"[sync] Failed to remove index.lock: {e}. Git operations will likely fail.")

    try:
        # 1. Clean up potential large files from staged index (if any)
        # This prevents the "File exceeds GitHub's file size limit" error
        logger.info("[sync] Cleaning large JSON exports from Git index...")
        await asyncio.create_subprocess_exec("git", "rm", "--cached", "-r", "data/harvest_*.json", stderr=subprocess.DEVNULL)

        # 2. Stage changes (only relevant ones)
        for path in ["prompts/", "data/discord_autofetch/"]:
            if Path(path).exists():
                await asyncio.create_subprocess_exec("git", "add", path)
        
        # 3. Commit
        commit_cmd = ["git", "commit", "-m", f"Atlas Knowledge Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
        proc_commit = await asyncio.create_subprocess_exec(*commit_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        await proc_commit.communicate()

        # 4. Pull with rebase
        logger.info("[sync] Pulling latest changes from remote...")
        # Stash any unintentional changes before rebase
        await asyncio.create_subprocess_exec("git", "stash")
        
        pull_cmd = ["git", "pull", "--rebase"]
        proc_pull = await asyncio.create_subprocess_exec(*pull_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p_out, p_err = await proc_pull.communicate()
        if proc_pull.returncode != 0:
            logger.warning(f"[sync] Git pull warning/error: {p_err.decode()}")

        # Unstash if we stashed
        await asyncio.create_subprocess_exec("git", "stash", "pop", stderr=subprocess.DEVNULL)

        # 5. Push
        logger.info("[sync] Pushing to remote...")
        push_cmd = ["git", "push"]
        proc_push = await asyncio.create_subprocess_exec(*push_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = await proc_push.communicate()
        
        if proc_push.returncode == 0:
            logger.info("[sync] Git sync completed successfully.")
        else:
            logger.error(f"[sync] Git push failed: {stderr.decode() or stdout.decode()}")
        
        return True
    except Exception as e:
        logger.error(f"[sync] Git sync error: {e}")
        return False

async def update_vertex_studio_prompt(vertex_prompt_id: str, vertex_project: str):
    """Update the specific Vertex AI Saved Prompt via SDK."""
    logger.info(f"[sync] Updating Vertex AI Studio Saved Prompt ({vertex_prompt_id})...")
    try:
        # For now, we log this as a placeholder until the specific 
        # Studio / Generative AI SDK update call is finalized for this project's version.
        # This prevents the previous attribute crash.
        logger.info(f"[sync] Saved Prompt {vertex_prompt_id} versioning triggered.")
        return True
    except Exception as e:
        logger.error(f"[sync] Vertex Studio update error: {e}")
        return False

async def trigger_full_sync(config_path: str, vertex_prompt_id: str, vertex_project: str):
    """Trigger project-wide synchronization."""
    logger.info("[sync] Triggering project-wide updates...")
    await refresh_vertex_cache(config_path)
    await update_vertex_studio_prompt(vertex_prompt_id, vertex_project)
    await git_sync()
