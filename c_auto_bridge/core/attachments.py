from dataclasses import dataclass
from typing import Literal


AttachmentKind = Literal["image", "file"]


@dataclass(frozen=True)
class Attachment:
    kind: AttachmentKind
    path: str
    name: str
