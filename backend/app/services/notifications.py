"""Notification dispatch: in-app, email (SMTP), Slack and generic webhooks."""

from __future__ import annotations

import asyncio
import smtplib
import uuid
from email.message import EmailMessage

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, UpstreamError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.enums import AlertSeverity, NotificationType
from app.models.operations import Notification
from app.repositories import UnitOfWork
from app.services.audit import AuditService

log = get_logger("ofme.notifications")


class NotificationService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.audit = AuditService(session)

    async def create(
        self,
        *,
        title: str,
        message: str,
        type_: NotificationType = NotificationType.INFO,
        severity: AlertSeverity = AlertSeverity.INFO,
        user_id: uuid.UUID | None = None,
        action_url: str | None = None,
        channels: list[str] | None = None,
        metadata: dict | None = None,
    ) -> Notification:
        notification = Notification(
            tenant_id=self.tenant_id,
            user_id=user_id,
            type=type_,
            title=title,
            message=message,
            severity=severity,
            action_url=action_url,
            metadata_=metadata or {},
        )
        self.session.add(notification)
        await self.session.flush()

        delivery: dict[str, dict] = {}
        for channel in channels or []:
            delivery[channel] = await self._dispatch(
                channel, title=title, message=message, severity=severity, action_url=action_url
            )
        notification.delivery = delivery
        if delivery and all(item.get("status") == "sent" for item in delivery.values()):
            notification.delivered_at = utcnow()
        if self.actor_id is not None:
            await self.audit.record(
                action="notification.created",
                resource_type="Notification",
                resource_id=notification.id,
                tenant_id=self.tenant_id,
                user_id=self.actor_id,
                after={
                    "title": title,
                    "severity": severity.value,
                    "channels": list(delivery),
                    "delivery": delivery,
                },
            )
        await self.session.flush()
        return notification

    async def delete(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Delete one of the actor's own notifications (or a broadcast one)."""
        notification = await self.session.get(Notification, notification_id)
        if notification is None or notification.tenant_id != self.tenant_id:
            raise NotFoundError("Notification not found")
        if notification.user_id not in {None, user_id}:
            raise NotFoundError("Notification not found")
        await self.session.delete(notification)
        await self.audit.record(
            action="notification.deleted",
            resource_type="Notification",
            resource_id=notification.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before={"title": notification.title, "severity": notification.severity.value},
        )
        await self.session.flush()

    async def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> None:
        notification = await self.uow.notifications.get_or_404(notification_id)
        if notification.user_id and notification.user_id != user_id:
            return
        notification.read = True
        notification.read_at = utcnow()
        await self.session.flush()

    # ------------------------------------------------------------------ channels
    async def _dispatch(
        self, channel: str, *, title: str, message: str, severity: AlertSeverity, action_url: str | None
    ) -> dict:
        started_at = utcnow().isoformat()
        try:
            if channel.startswith("webhook:"):
                await self._webhook(channel.removeprefix("webhook:"), title, message, severity, action_url)
            elif channel == "email":
                if not await asyncio.to_thread(self._email, title, message):
                    return {
                        "status": "skipped",
                        "reason": "smtp_not_configured",
                        "at": started_at,
                    }
            elif channel.startswith("slack:"):
                await self._slack(channel.removeprefix("slack:"), title, message, severity, action_url)
            else:
                log.debug("notification.unknown_channel", channel=channel)
                return {"status": "skipped", "reason": "unknown_channel", "at": started_at}
            return {"status": "sent", "at": started_at}
        except Exception as exc:  # noqa: BLE001 - notifications are best effort
            log.warning("notification.dispatch_failed", channel=channel, error=str(exc))
            return {"status": "failed", "error": str(exc), "at": started_at}

    async def _webhook(
        self, url: str, title: str, message: str, severity: AlertSeverity, action_url: str | None
    ) -> None:
        payload = {
            "title": title,
            "message": message,
            "severity": severity.value,
            "tenant_id": str(self.tenant_id),
            "url": action_url,
            "timestamp": utcnow().isoformat(),
        }
        async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers={"X-OFME-Event": "notification"})
        if response.status_code >= 400:
            raise UpstreamError(f"Webhook returned {response.status_code}")

    async def _slack(
        self, url: str, title: str, message: str, severity: AlertSeverity, action_url: str | None
    ) -> None:
        color = {"info": "#2196f3", "warning": "#ff9800", "critical": "#f44336"}[severity.value]
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\n{message}"}},
        ]
        if action_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "Open"}, "url": action_url}
                    ],
                }
            )
        async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json={"attachments": [{"color": color, "blocks": blocks}]})
        if response.status_code >= 400:
            raise UpstreamError(f"Slack webhook returned {response.status_code}")

    def _email(self, title: str, message: str) -> bool:
        host = getattr(settings, "SMTP_HOST", "")
        if not host:
            log.debug("notification.smtp_not_configured")
            return False
        msg = EmailMessage()
        msg["Subject"] = f"[OFME] {title}"
        msg["From"] = getattr(settings, "SMTP_FROM", "noreply@ofme.local")
        msg["To"] = getattr(settings, "SMTP_TO", "ops@ofme.local")
        msg.set_content(message)
        with smtplib.SMTP(host, getattr(settings, "SMTP_PORT", 587), timeout=15) as smtp:
            smtp.starttls()
            user = getattr(settings, "SMTP_USER", "")
            password = getattr(settings, "SMTP_PASSWORD", "")
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True
