import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CursorPosition:
    created_at: datetime
    job_id: uuid.UUID


class InvalidCursorError(ValueError):
    pass


def encode_cursor(position: CursorPosition) -> str:
    raw = f"{position.created_at.isoformat()}|{position.job_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> CursorPosition:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_raw, id_raw = raw.split("|", 1)
        return CursorPosition(
            created_at=datetime.fromisoformat(created_raw),
            job_id=uuid.UUID(id_raw),
        )
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise InvalidCursorError("invalid cursor") from error
