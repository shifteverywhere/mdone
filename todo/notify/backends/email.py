"""
EmailBackend — SMTP notification delivery.

Configuration (config.toml):

    [notifications.email]
    smtp_host    = "smtp.gmail.com"
    smtp_port    = 587
    from         = "todo-agent@example.com"
    to           = "you@example.com"
    username_env = "SMTP_USER"      # env var name holding the username
    password_env = "SMTP_PASSWORD"  # env var name holding the password

Credentials are NEVER stored in config.toml — only the env var names.
"""

import os
import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from . import BaseBackend


class EmailBackend(BaseBackend):
    name = "email"

    def send(self, payload: dict, config: dict) -> bool:
        cfg = config.get("notifications", {}).get("email", {})

        smtp_host = cfg.get("smtp_host", "")
        smtp_port = int(cfg.get("smtp_port", 587))
        from_addr = cfg.get("from", "")
        to_addr   = cfg.get("to", "")

        username_env = cfg.get("username_env", "SMTP_USER")
        password_env = cfg.get("password_env", "SMTP_PASSWORD")
        username = os.environ.get(username_env, "")
        password = os.environ.get(password_env, "")

        if not all([smtp_host, from_addr, to_addr]):
            print(
                "[EmailBackend] Missing smtp_host / from / to in config.",
                file=sys.stderr,
            )
            return False

        subject, body = self._format(payload)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = from_addr
        msg["To"]      = to_addr
        msg.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls()
                if username and password:
                    server.login(username, password)
                server.sendmail(from_addr, to_addr, msg.as_string())
            return True
        except Exception as e:
            print(f"[EmailBackend] Failed to send email: {e}", file=sys.stderr)
            return False

    @staticmethod
    def _format(payload: dict) -> tuple:
        """Return (subject, plain-text body) for the notification payload."""
        status = "OVERDUE" if payload.get("overdue") else "Due soon"
        title  = payload["title"]
        subject = f"[Todo] {status}: {title}"

        lines = [
            f"Task:     {title}",
            f"Status:   {status}",
        ]
        if payload.get("due"):
            lines.append(f"Due:      {payload['due']}")
        if payload.get("priority", 4) < 4:
            lines.append(f"Priority: p{payload['priority']}")
        if payload.get("tags"):
            lines.append(f"Tags:     {', '.join('@' + t for t in payload['tags'])}")
        lines.append(f"ID:       {payload['id']}")

        body = "\n".join(lines)
        return subject, body
