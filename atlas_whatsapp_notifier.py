"""
Atlas WhatsApp Notifier
===================================
A lightweight module to send WhatsApp notifications for important Atlas pipeline events.
Uses Meta's WhatsApp Cloud API.

Setup:
  1. Create Meta Developer App -> WhatsApp -> API Setup
  2. Add to .env:
     WHATSAPP_PHONE_ID=your_phone_number_id
     WHATSAPP_TOKEN=your_permanent_access_token
     WHATSAPP_RECIPIENT=your_phone_number_with_country_code
"""

import os
import json
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import requests
except ImportError:
    requests = None

# Configure logging
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] whatsapp: %(message)s")
log = logging.getLogger("whatsapp")

# ── Config ──────────────────────────────────────────────────────────
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "").strip()
TOKEN = os.getenv("WHATSAPP_TOKEN", "").strip()
RECIPIENT = os.getenv("WHATSAPP_RECIPIENT", "").strip()

API_URL = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages" if PHONE_ID else ""


def is_configured() -> bool:
    """Check if WhatsApp credentials are provided."""
    return bool(PHONE_ID and TOKEN and RECIPIENT)


def send_whatsapp_alert(message: str) -> bool:
    """
    Send a free-form text message via WhatsApp.
    Note: Free-form messages only work within the 24-hour service window
    after the user has messaged the business account. Otherwise, a pre-approved
    template must be used. For personal/internal dev alerts, messaging the bot
    once every 24h keeps the window open.
    """
    if not is_configured():
        log.warning("WhatsApp not configured (missing WHATSAPP_PHONE_ID, TOKEN, or RECIPIENT).")
        return False

    if requests is None:
        log.error("requests library is not installed. Run: pip install requests")
        return False

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    
    # Format message to be WhatsApp friendly (bolding)
    formatted_msg = message.replace("**", "*")

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": RECIPIENT,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": formatted_msg
        }
    }

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            log.info("✅ Alert sent successfully.")
            return True
        else:
            log.error(f"❌ Failed to send alert: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        log.error(f"❌ Error sending WhatsApp alert: {e}")
        return False


def test_alert():
    """Send a test message to verify configuration."""
    if not is_configured():
        print("❌ Missing configuration in .env:")
        if not PHONE_ID: print("  - WHATSAPP_PHONE_ID")
        if not TOKEN: print("  - WHATSAPP_TOKEN")
        if not RECIPIENT: print("  - WHATSAPP_RECIPIENT")
        print("\nPlease add these to your .env file.")
        return

    print(f"Sending test alert to {RECIPIENT}...")
    success = send_whatsapp_alert(
        "🏛️ *Atlas Control Center*\n\n"
        "✅ WhatsApp notification testing is successful.\n"
        "Your pipeline alerts will be sent here."
    )
    if success:
        print("✅ Test message sent. Check your WhatsApp!")
    else:
        print("❌ Test message failed. Check logs above.")


if __name__ == "__main__":
    test_alert()
