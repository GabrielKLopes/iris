from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from typing import Any, Protocol

from iris.agent.ports import Tool
from iris.domain.models import AccessLevel


class Mailbox(Protocol):
    def search(self, query: str, unread_only: bool, limit: int) -> str: ...

    def read(self, message_id: str) -> str: ...

    def send(self, to: list[str], subject: str, body: str, reply_to_id: str | None) -> str: ...


class Messenger(Protocol):
    def chats(self, unread_only: bool) -> str: ...

    def read(self, chat: str, limit: int) -> str: ...

    def send(self, chat: str, text: str) -> str: ...


class Calendar(Protocol):
    def events(self, date_from: str, date_to: str) -> str: ...

    def create(self, title: str, start: str, end: str, location: str) -> str: ...


def _safe(action: Callable[[], str]) -> str:
    try:
        return action()
    except Exception as exc:
        return f"Failed: {exc}"


class ConfirmedAction(Tool):
    access = AccessLevel.LOCAL

    def __init__(self, current_turn: Callable[[], int]):
        self.current_turn = current_turn
        self.pending: dict[str, tuple[str, int]] = {}

    def prepare_or_run(self, payload: dict[str, Any], code: str | None, summary: str, action: Callable[[], str]) -> str:
        key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if not code:
            code = secrets.token_hex(3)
            self.pending[code] = (key, self.current_turn())
            return f"Nothing done yet. Tell the user briefly: {summary}. Ask if you may go ahead. Confirmation code: {code}"
        pending = self.pending.get(code)
        if pending is None or pending[0] != key:
            return "Invalid confirmation code. Start again without a code and ask the user."
        if self.current_turn() <= pending[1]:
            return "The user has not answered yet. Ask first and wait for the reply."
        del self.pending[code]
        return _safe(action)


CONFIRMATION = {"type": "string", "description": "Code from the previous call, only after the user agreed"}


class ListEmailsTool(Tool):
    name = "list_emails"
    description = "Lists the user's emails, newest first, with id, sender, subject, date and a short preview. Use query to search."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words, sender or subject to search for; empty for the inbox"},
            "unread_only": {"type": "boolean"},
            "limit": {"type": "integer", "description": "Default 10"},
        },
    }

    def __init__(self, mailbox: Mailbox):
        self.mailbox = mailbox

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.mailbox.search(tool_input.get("query", ""), bool(tool_input.get("unread_only")), tool_input.get("limit", 10)))


class ReadEmailTool(Tool):
    name = "read_email"
    description = "Reads one email in full by its id from list_emails."
    input_schema = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}

    def __init__(self, mailbox: Mailbox):
        self.mailbox = mailbox

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.mailbox.read(tool_input["id"]))


class SendEmailTool(ConfirmedAction):
    name = "send_email"
    description = (
        "Sends an email or a reply, in two steps. First call it without a code: nothing is sent and you get a confirmation "
        "code; tell the user who it goes to and the gist of the text and ask. Only after they say yes in their next message, "
        "call again with exactly the same fields and the code."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "array", "items": {"type": "string"}, "description": "Email addresses"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "reply_to_id": {"type": "string", "description": "Id of the email being answered, when replying"},
            "confirmation": CONFIRMATION,
        },
        "required": ["to", "subject", "body"],
    }

    def __init__(self, mailbox: Mailbox, current_turn: Callable[[], int]):
        super().__init__(current_turn)
        self.mailbox = mailbox

    def run(self, tool_input: dict[str, Any]) -> str:
        payload = {k: tool_input.get(k) for k in ("to", "subject", "body", "reply_to_id")}
        summary = f"email to {', '.join(payload['to'])} with subject '{payload['subject']}'"
        return self.prepare_or_run(
            payload, tool_input.get("confirmation"), summary,
            lambda: self.mailbox.send(payload["to"], payload["subject"], payload["body"], payload["reply_to_id"]),
        )


class ListChatsTool(Tool):
    name = "list_whatsapp_chats"
    description = "Lists the user's recent WhatsApp chats with the last message and how many are unread."
    input_schema = {"type": "object", "properties": {"unread_only": {"type": "boolean"}}}

    def __init__(self, messenger: Messenger):
        self.messenger = messenger

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.messenger.chats(bool(tool_input.get("unread_only"))))


class ReadChatTool(Tool):
    name = "read_whatsapp_chat"
    description = "Reads the latest messages of one WhatsApp chat, by contact or group name."
    input_schema = {
        "type": "object",
        "properties": {"chat": {"type": "string", "description": "Contact or group name"}, "limit": {"type": "integer", "description": "Default 20"}},
        "required": ["chat"],
    }

    def __init__(self, messenger: Messenger):
        self.messenger = messenger

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.messenger.read(tool_input["chat"], tool_input.get("limit", 20)))


class SendChatMessageTool(ConfirmedAction):
    name = "send_whatsapp_message"
    description = (
        "Sends a WhatsApp message, in two steps. First call it without a code: nothing is sent; tell the user the contact "
        "and the message and ask. Only after they say yes in their next message, call again with the same fields and the code."
    )
    input_schema = {
        "type": "object",
        "properties": {"chat": {"type": "string", "description": "Contact or group name"}, "text": {"type": "string"}, "confirmation": CONFIRMATION},
        "required": ["chat", "text"],
    }

    def __init__(self, messenger: Messenger, current_turn: Callable[[], int]):
        super().__init__(current_turn)
        self.messenger = messenger

    def run(self, tool_input: dict[str, Any]) -> str:
        payload = {"chat": tool_input["chat"], "text": tool_input["text"]}
        summary = f"message to {payload['chat']}: \"{payload['text']}\""
        return self.prepare_or_run(payload, tool_input.get("confirmation"), summary, lambda: self.messenger.send(payload["chat"], payload["text"]))


class ListEventsTool(Tool):
    name = "list_events"
    description = "Lists the user's calendar events between two dates (YYYY-MM-DD)."
    input_schema = {
        "type": "object",
        "properties": {"date_from": {"type": "string"}, "date_to": {"type": "string"}},
        "required": ["date_from", "date_to"],
    }

    def __init__(self, calendar: Calendar):
        self.calendar = calendar

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.calendar.events(tool_input["date_from"], tool_input["date_to"]))


class CreateEventTool(ConfirmedAction):
    name = "create_event"
    description = (
        "Creates a calendar event, in two steps. First call it without a code; tell the user the title, day and time and ask. "
        "Only after they say yes in their next message, call again with the same fields and the code."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start": {"type": "string", "description": "YYYY-MM-DDTHH:MM"},
            "end": {"type": "string", "description": "YYYY-MM-DDTHH:MM"},
            "location": {"type": "string"},
            "confirmation": CONFIRMATION,
        },
        "required": ["title", "start", "end"],
    }

    def __init__(self, calendar: Calendar, current_turn: Callable[[], int]):
        super().__init__(current_turn)
        self.calendar = calendar

    def run(self, tool_input: dict[str, Any]) -> str:
        payload = {k: tool_input.get(k, "") for k in ("title", "start", "end", "location")}
        summary = f"event '{payload['title']}' from {payload['start']} to {payload['end']}"
        return self.prepare_or_run(
            payload, tool_input.get("confirmation"), summary,
            lambda: self.calendar.create(payload["title"], payload["start"], payload["end"], payload["location"]),
        )
