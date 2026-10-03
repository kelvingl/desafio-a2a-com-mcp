"""Regras de negocio puras: janela de uso, duracao, conflitos e alternativas.

Fonte unica de verdade: dados/politica-de-uso.md (08:00-20:00 America/Sao_Paulo,
duracao maxima de 2h, sem sobreposicao na mesma sala).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from servidor_mcp.dados import Reserva, Sala

_SAO_PAULO = timezone(timedelta(hours=-3))
_ABRE = time(8, 0)
_FECHA = time(20, 0)
_DURACAO_MAXIMA = timedelta(hours=2)


def parse_instante(valor: str) -> datetime:
    return datetime.fromisoformat(valor)


def dentro_da_janela(inicio: str, fim: str) -> bool:
    i = parse_instante(inicio).astimezone(_SAO_PAULO).time()
    f = parse_instante(fim).astimezone(_SAO_PAULO).time()
    return _ABRE <= i <= _FECHA and _ABRE <= f <= _FECHA


def duracao_valida(inicio: str, fim: str) -> bool:
    return parse_instante(fim) - parse_instante(inicio) <= _DURACAO_MAXIMA


def intervalo_valido(inicio: str, fim: str) -> bool:
    return parse_instante(fim) > parse_instante(inicio)


def _sobrepoe(inicio_a: str, fim_a: str, inicio_b: str, fim_b: str) -> bool:
    return parse_instante(inicio_a) < parse_instante(fim_b) and parse_instante(inicio_b) < parse_instante(fim_a)


def conflitos(sala_id: str, inicio: str, fim: str, reservas: list[Reserva]) -> list[Reserva]:
    return [r for r in reservas if r.sala == sala_id and _sobrepoe(inicio, fim, r.inicio, r.fim)]


def alternativas(
    sala_pedida_id: str, inicio: str, fim: str, salas: list[Sala], reservas: list[Reserva], limite: int = 3
) -> list[str]:
    pedida = next(s for s in salas if s.id == sala_pedida_id)
    candidatas = [
        s
        for s in salas
        if s.capacidade >= pedida.capacidade and not conflitos(s.id, inicio, fim, reservas)
    ]
    candidatas.sort(key=lambda s: (s.capacidade, s.id))
    return [s.id for s in candidatas[:limite]]
