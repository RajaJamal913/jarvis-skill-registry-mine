"""
Validation for the `requested_tools` field on a skill version.

Two independent checks, both must pass:

1. Allowlist - the tool name must be a known, registered tool. Unknown
   tool names are rejected outright (typos, made-up tools, attempts to
   reference internal/system tools that were never registered).

2. Destructive-pattern block - even an allowlisted-looking name is
   rejected if it matches a pattern associated with destructive/system
   level operations (delete, drop, format, shell exec, etc). This guards
   against tool names that a caller invents to *sound* like a real tool.

Importantly: passing validation only means the tool may be *requested*.
Requesting a tool never grants it - `granted_tools` is a separate field
that this module never touches.
"""
import re
from typing import Iterable

ALLOWED_TOOLS = {
    "send_email",
    "read_calendar",
    "generate_report",
    "update_crm_record",
    "fetch_document",
    "schedule_meeting",
    "summarize_thread",
    "create_invoice_draft",
}

_DESTRUCTIVE_PATTERNS = [
    re.compile(r"delete", re.I),
    re.compile(r"drop", re.I),
    re.compile(r"rm[_\-\s]", re.I),
    re.compile(r"format", re.I),
    re.compile(r"wipe", re.I),
    re.compile(r"shell", re.I),
    re.compile(r"exec", re.I),
    re.compile(r"sudo", re.I),
    re.compile(r"truncate", re.I),
    re.compile(r"admin[_\-]?override", re.I),
]


class InvalidToolError(ValueError):
    def __init__(self, tool: str, reason: str):
        self.tool = tool
        self.reason = reason
        super().__init__(f"Requested tool '{tool}' rejected: {reason}")


def validate_requested_tools(tools: Iterable[str]) -> list[str]:
    if tools is None:
        return []
    cleaned = []
    for raw in tools:
        if not isinstance(raw, str) or not raw.strip():
            raise InvalidToolError(str(raw), "tool name must be a non-empty string")
        name = raw.strip().lower()

        for pattern in _DESTRUCTIVE_PATTERNS:
            if pattern.search(name):
                raise InvalidToolError(name, "matches a destructive/system-level pattern")

        if name not in ALLOWED_TOOLS:
            raise InvalidToolError(name, "not a recognized/registered tool")

        cleaned.append(name)
    return cleaned
