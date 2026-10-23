import re

from pydantic import BaseModel, Field, field_validator

from aos.db.models import OutboxMessage
from aos.db.session import session_scope
from aos.tools.base import ToolContext

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SendEmailInput(BaseModel):
    to: list[str] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)

    @field_validator("to")
    @classmethod
    def _valid_addresses(cls, value: list[str]) -> list[str]:
        bad = [address for address in value if not EMAIL.match(address)]
        if bad:
            raise ValueError(f"invalid email address: {', '.join(bad)}")
        return value


def send_email(args: SendEmailInput, ctx: ToolContext) -> dict:
    with session_scope() as session:
        message = OutboxMessage(
            run_id=ctx.run_id,
            channel="email",
            recipient=", ".join(args.to),
            subject=args.subject,
            body=args.body,
        )
        session.add(message)
        session.flush()
        outbox_id = message.id
    return {"outbox_id": outbox_id, "status": "queued", "recipients": args.to}
