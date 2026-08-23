"""Transactional email delivery for DECIDAI invitations."""
from dataclasses import dataclass
import html
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class EmailDeliveryResult:
    status: str


class ResendEmailProvider:
    """Small Resend REST adapter configured exclusively through environment variables."""

    endpoint = "https://api.resend.com/emails"

    def __init__(self, api_key: str, from_address: str, reply_to: str | None = None):
        self.api_key = api_key
        self.from_address = from_address
        self.reply_to = reply_to

    def send(self, *, recipient: str, subject: str, html_body: str, text_body: str) -> None:
        payload = {
            "from": self.from_address,
            "to": [recipient],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }
        if self.reply_to:
            payload["reply_to"] = self.reply_to
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError("transactional email provider returned an unsuccessful status")


def _provider() -> ResendEmailProvider | None:
    provider = os.getenv("EMAIL_PROVIDER", "resend").strip().lower()
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_address = os.getenv("EMAIL_FROM", "").strip()
    if not api_key or not from_address:
        return None
    if provider != "resend":
        raise ValueError("unsupported transactional email provider")
    return ResendEmailProvider(api_key, from_address, os.getenv("EMAIL_REPLY_TO", "").strip() or None)


def _invitation_bodies(inviter_name: str, workspace_name: str, role: str, invite_url: str) -> tuple[str, str]:
    inviter = html.escape(inviter_name)
    workspace = html.escape(workspace_name)
    assigned_role = html.escape(role.title())
    link = html.escape(invite_url, quote=True)
    text_body = (
        f"{inviter_name} invited you to join {workspace_name} on DECIDAI as a {role}.\n\n"
        f"Accept your invitation: {invite_url}\n\n"
        "This invitation expires in 7 days.\n\nAI Advises. Human Decides."
    )
    html_body = f"""<!doctype html>
<html><body style=\"margin:0;background:#f4f7fb;font-family:Arial,sans-serif;color:#263a55\">
  <main style=\"max-width:560px;margin:32px auto;background:#ffffff;border-radius:12px;padding:36px\">
    <div style=\"font-weight:800;letter-spacing:.08em;color:#2f6fc1\">DECIDAI</div>
    <h1 style=\"font-size:24px;margin:20px 0 12px\">You’re invited to {workspace}</h1>
    <p>{inviter} invited you to join this workspace as a <strong>{assigned_role}</strong>.</p>
    <p style=\"margin:28px 0\"><a href=\"{link}\" style=\"background:#2f6fc1;color:#fff;padding:12px 18px;border-radius:7px;text-decoration:none;font-weight:700\">Accept Invitation</a></p>
    <p style=\"font-size:13px;color:#62738a\">This invitation expires in 7 days. If the button does not work, use this link:<br><a href=\"{link}\">{link}</a></p>
    <p style=\"font-size:13px;color:#62738a;margin-top:26px\"><strong>AI Advises. Human Decides.</strong></p>
  </main>
</body></html>"""
    return html_body, text_body


def send_team_invitation_email(*, recipient: str, inviter_name: str, workspace_name: str,
                               role: str, invite_url: str) -> EmailDeliveryResult:
    """Deliver an invitation without leaking provider details or credentials to callers."""
    try:
        provider = _provider()
        if provider is None:
            return EmailDeliveryResult("not_configured")
        html_body, text_body = _invitation_bodies(inviter_name, workspace_name, role, invite_url)
        provider.send(
            recipient=recipient,
            subject=f"Join {workspace_name} on DECIDAI",
            html_body=html_body,
            text_body=text_body,
        )
        return EmailDeliveryResult("sent")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError):
        return EmailDeliveryResult("failed")
