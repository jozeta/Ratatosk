import smtplib
import ssl
from email.message import EmailMessage


class EmailNotConfigured(Exception):
    pass


def send_email(cfg: dict, to_email: str, subject: str, body: str) -> None:
    if not cfg.get("smtp_enabled"):
        raise EmailNotConfigured("Email sending is disabled in Admin Settings")
    if not cfg.get("smtp_host") or not cfg.get("smtp_from_email"):
        raise EmailNotConfigured("SMTP host and from-address must be configured in Admin Settings")

    msg = EmailMessage()
    from_name = cfg.get("smtp_from_name") or cfg.get("brand_name") or "SecureDrop"
    msg["From"] = f"{from_name} <{cfg['smtp_from_email']}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    host = cfg["smtp_host"]
    port = cfg.get("smtp_port") or 587
    encryption = cfg.get("smtp_encryption") or "starttls"
    username = cfg.get("smtp_username") or None
    password = cfg.get("smtp_password") or None

    if encryption == "ssl":
        smtp_cls, kwargs = smtplib.SMTP_SSL, {"context": ssl.create_default_context()}
    else:
        smtp_cls, kwargs = smtplib.SMTP, {}

    with smtp_cls(host, port, timeout=15, **kwargs) as server:
        if encryption == "starttls":
            server.starttls(context=ssl.create_default_context())
        if username and password:
            server.login(username, password)
        server.send_message(msg)


def send_password_reset_email(cfg: dict, to_email: str, reset_url: str) -> None:
    brand = cfg.get("brand_name") or "SecureDrop"
    expiry = cfg.get("password_reset_token_expiry_minutes", 60)
    subject = f"Reset your {brand} password"
    body = (
        f"A password reset was requested for your {brand} account.\n\n"
        f"To choose a new password, open this link:\n{reset_url}\n\n"
        f"This link expires in {expiry} minutes and can only be used once.\n\n"
        "If you didn't request this, you can safely ignore this email - "
        "your password will not be changed."
    )
    send_email(cfg, to_email, subject, body)


def send_download_notification_email(cfg: dict, to_email: str, size_bytes: int) -> None:
    brand = cfg.get("brand_name") or "SecureDrop"
    subject = f"A file you shared on {brand} was downloaded"
    # The server never learns the original filename (zero-knowledge design),
    # so this can only describe the download, not name the file.
    body = (
        f"A file you shared via {brand} ({size_bytes:,} bytes) was just downloaded.\n\n"
        "You're receiving this because you turned on download notifications for that "
        "file when you uploaded it. You can turn this off per-file next time, or "
        "site-wide in Admin Settings."
    )
    send_email(cfg, to_email, subject, body)
