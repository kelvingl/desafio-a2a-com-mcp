"""Parse e propagacao do W3C traceparent recebido do cliente A2A."""

from __future__ import annotations

import re
import secrets

_TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")


def trace_id_de(traceparent: str | None) -> str | None:
    """Extrai o trace-id de um header traceparent recebido, ou None se ausente/invalido."""
    if not traceparent:
        return None
    m = _TRACEPARENT_RE.match(traceparent)
    return m.group(1) if m else None


def novo_traceparent(trace_id: str) -> str:
    """Um traceparent novo com o mesmo trace-id e um span-id novo."""
    return f"00-{trace_id}-{secrets.token_hex(8)}-01"
