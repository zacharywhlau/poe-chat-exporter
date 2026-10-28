from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Attachment:
    url: str
    name: str = "attachment"
    kind: str = "file"  # image | file | unknown
    local_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Message:
    author: str
    text: str
    message_id: int | str | None = None
    content_type: str | None = None
    creation_time_us: int | None = None
    attachments: list[Attachment] = field(default_factory=list)
    source: str = "unknown"  # network | dom | unknown

    def to_dict(self) -> dict[str, Any]:
        return {
            "author": self.author,
            "text": self.text,
            "messageId": self.message_id,
            "contentType": self.content_type,
            "time_epoch_us": self.creation_time_us,
            "attachments": [a.to_dict() for a in self.attachments],
            "source": self.source,
        }


@dataclass
class Chat:
    chat_id: int | str
    chat_code: str
    node_id: str
    title: str
    bot: str
    bot_handle: str = ""
    messages: list[Message] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chatId": self.chat_id,
            "chatCode": self.chat_code,
            "id": self.node_id,
            "title": self.title,
            "bot": self.bot,
            "botHandle": self.bot_handle,
            "messages": [m.to_dict() for m in self.messages],
        }
