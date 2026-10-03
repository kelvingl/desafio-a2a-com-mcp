"""Parse do formato fixo de pedido, sem linguagem natural nenhuma."""

from __future__ import annotations

import re
from typing import NamedTuple

_RE_RESERVAR = re.compile(
    r"^reservar sala=(?P<sala>\S+) inicio=(?P<inicio>\S+) fim=(?P<fim>\S+) responsavel=(?P<responsavel>.+)$"
)
_RE_ESCOLHA = re.compile(r"^escolha=(?P<valor>\S+)$")


class PedidoReserva(NamedTuple):
    sala: str
    inicio: str
    fim: str
    responsavel: str


def parse_pedido_reserva(texto: str) -> PedidoReserva | None:
    m = _RE_RESERVAR.match(texto.strip())
    if not m:
        return None
    return PedidoReserva(
        sala=m.group("sala"), inicio=m.group("inicio"), fim=m.group("fim"), responsavel=m.group("responsavel")
    )


def parse_escolha(texto: str) -> str | None:
    m = _RE_ESCOLHA.match(texto.strip())
    return m.group("valor") if m else None
