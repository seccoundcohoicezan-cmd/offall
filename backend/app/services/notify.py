"""User notifications. A failed send is logged and swallowed; it never fails a job."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx
from sqlalchemy import delete, select

from app.core.config import Settings
from app.db.session import SessionFactory
from app.models import PushSubscription, User

log = logging.getLogger(__name__)


@dataclass
class Event:
    kind: str  # job_done | job_failed | key_invalid
    title: str
    body: str
    url: str = "/chat"


class Channel(Protocol):
    async def send(self, user: User, event: Event) -> None: ...


class TelegramChannel:
    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token

    async def send(self, user: User, event: Event) -> None:
        chat_id = str(user.settings.get("notify_telegram_chat_id") or "").strip()
        if not (self.bot_token and chat_id):
            return
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": f"{event.title}\n{event.body}"},
            )
            resp.raise_for_status()


class WebPushChannel:
    def __init__(self, sessions: SessionFactory, settings: Settings) -> None:
        self.sessions = sessions
        self.settings = settings

    async def send(self, user: User, event: Event) -> None:
        if not (self.settings.vapid_private_key and user.settings.get("notify_webpush")):
            return
        async with self.sessions() as session:
            subs = (
                await session.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id))
            ).all()
        payload = json.dumps({"title": event.title, "body": event.body, "url": event.url})
        for sub in subs:
            gone = await asyncio.to_thread(self._push, sub, payload)
            if gone:
                async with self.sessions() as session:
                    await session.execute(delete(PushSubscription).where(PushSubscription.id == sub.id))
                    await session.commit()

    def _push(self, sub: PushSubscription, payload: str) -> bool:
        from pywebpush import WebPushException, webpush

        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": sub.keys},
                data=payload,
                vapid_private_key=self.settings.vapid_private_key,
                vapid_claims={"sub": self.settings.vapid_subject},
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                return True
            raise
        return False


class Notifier:
    def __init__(self, channels: list[Channel]) -> None:
        self.channels = channels

    async def notify(self, user: User, event: Event) -> None:
        for channel in self.channels:
            try:
                await channel.send(user, event)
            except Exception:
                log.warning(
                    "notification failed",
                    extra={"user_id": str(user.id), "event": event.kind},
                )


def build_notifier(sessions: SessionFactory, settings: Settings) -> Notifier:
    return Notifier([TelegramChannel(settings.telegram_bot_token), WebPushChannel(sessions, settings)])
