"""Email notification tool using Resend API."""

from typing import Any, Dict

import httpx

from config import Config
from tools.base import BaseTool

RESEND_API_URL = "https://api.resend.com/emails"


class NotifyTool(BaseTool):
    """Send email notifications via Resend."""

    @property
    def name(self) -> str:
        return "notify"

    @property
    def description(self) -> str:
        return "Send an email notification via Resend."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "recipient": {
                "type": "string",
                "description": "Recipient email address.",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line.",
            },
            "body": {
                "type": "string",
                "description": "Email body (plain text).",
            },
        }

    async def execute(self, recipient: str, subject: str, body: str) -> str:
        if not recipient:
            return "Error: recipient email address is required."

        api_key = Config.RESEND_API_KEY
        if not api_key:
            return "Error: RESEND_API_KEY is not configured in .aloop/config."

        from_addr = Config.NOTIFY_EMAIL_FROM
        if not from_addr:
            return "Error: NOTIFY_EMAIL_FROM is not configured in .aloop/config."

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    RESEND_API_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "from": from_addr,
                        "to": [recipient],
                        "subject": subject,
                        "text": body,
                    },
                )
            if resp.status_code == 200:
                return f"Email sent successfully to {recipient}."
            return f"Error sending email: {resp.status_code} {resp.text}"
        except Exception as e:
            return f"Error sending email: {e}"
