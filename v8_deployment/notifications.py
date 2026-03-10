import requests
import logging

logger = logging.getLogger()

def send_discord_alert(message, webhook_url=None):
    """
    Sends a message to a Discord channel via Webhook.
    
    Args:
        message (str): The message to send.
        webhook_url (str): The Discord Webhook URL. If None, it will try to load from env.
    """
    if not webhook_url:
        logger.warning("No Discord Webhook URL provided. Skipping notification.")
        return

    data = {
        "content": message,
        "username": "Alpaca Bot"
    }

    try:
        response = requests.post(webhook_url, json=data)
        response.raise_for_status()
        logger.info("Discord notification sent successfully.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Discord notification: {e}")
