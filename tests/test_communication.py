import re

from iris.agent.tools.communication import CreateEventTool, SendChatMessageTool, SendEmailTool


class FakeMailbox:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, reply_to_id):
        self.sent.append((to, subject, body, reply_to_id))
        return "Sent"


class FakeMessenger:
    def __init__(self):
        self.sent = []

    def send(self, chat, text):
        self.sent.append((chat, text))
        return f"Sent to {chat}"


class FakeCalendar:
    def create(self, title, start, end, location):
        return f"Created {title}"


def code_of(answer: str) -> str:
    return re.search(r"Confirmation code: (\w+)", answer).group(1)


def test_email_is_only_sent_after_the_user_answers():
    turn = [1]
    mailbox = FakeMailbox()
    tool = SendEmailTool(mailbox, lambda: turn[0])
    fields = {"to": ["ana@example.com"], "subject": "Reunião", "body": "Pode ser amanhã?"}

    first = tool.run(fields)
    assert "Nothing done yet" in first and not mailbox.sent

    same_turn = tool.run({**fields, "confirmation": code_of(first)})
    assert "has not answered" in same_turn and not mailbox.sent

    turn[0] = 2
    assert tool.run({**fields, "confirmation": code_of(first)}) == "Sent"
    assert mailbox.sent == [(["ana@example.com"], "Reunião", "Pode ser amanhã?", None)]


def test_changed_message_needs_a_new_confirmation():
    turn = [1]
    messenger = FakeMessenger()
    tool = SendChatMessageTool(messenger, lambda: turn[0])
    first = tool.run({"chat": "Mãe", "text": "Chego às 8"})
    turn[0] = 2
    answer = tool.run({"chat": "Mãe", "text": "Chego às 9", "confirmation": code_of(first)})
    assert "Invalid confirmation code" in answer and not messenger.sent


def test_event_is_created_after_confirmation():
    turn = [1]
    tool = CreateEventTool(FakeCalendar(), lambda: turn[0])
    fields = {"title": "Dentista", "start": "2026-10-20T14:00", "end": "2026-10-20T15:00"}
    first = tool.run(fields)
    turn[0] = 2
    assert tool.run({**fields, "confirmation": code_of(first)}) == "Created Dentista"
