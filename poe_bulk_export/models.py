from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Attachment:
    url: str
    name: str = "attachment"
    kind: str = "file"  # image | media | file
    local_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Message:
    # Role: human | bot | chat_break | system | unknown
    author: str
    text: str
    message_id: int | str | None = None
    content_type: str | None = None
    creation_time_us: int | None = None
    attachments: list[Attachment] = field(default_factory=list)
    source: str = "unknown"  # store | next_data | network | graphql | dom
    # Display name for the speaker (bot display name / group-chat user name)
    author_name: str | None = None
    # Poe's raw `author` field (e.g. "human", "claude_fable_5", "chat_break")
    author_raw: str | None = None
    state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.author,
            "author": self.author_raw or self.author,
            "authorName": self.author_name,
            "text": self.text,
            "messageId": self.message_id,
            "contentType": self.content_type,
            "state": self.state,
            "time_epoch_us": self.creation_time_us,
            "attachments": [a.to_dict() for a in self.attachments],
            "source": self.source,
        }


@dataclass
class Chat:
    chat_id: int | str | None
    chat_code: str
    node_id: str = ""
    title: str = "Untitled"
    bot: str = ""
    bot_handle: str = ""
    messages: list[Message] = field(default_factory=list)
    # Last-activity time from the chat list, when Poe provides one
    activity_time_us: int | None = None
    created_time_us: int | None = None
    # Opaque "has this chat changed?" marker from the chat list (for --incremental)
    activity_signature: str | None = None
    # Filled in after harvesting
    complete: bool | None = None
    source: str | None = None

    @property
    def url(self) -> str:
        return f"https://poe.com/chat/{self.chat_code}" if self.chat_code else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chatId": self.chat_id,
            "chatCode": self.chat_code,
            "id": self.node_id,
            "title": self.title,
            "bot": self.bot,
            "botHandle": self.bot_handle,
            "url": self.url,
            "complete": self.complete,
            "source": self.source,
            "activity_time_us": self.activity_time_us,
            "messages": [m.to_dict() for m in self.messages],
        }
