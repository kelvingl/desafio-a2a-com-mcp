"""Carga dos dados do dominio (salas, reservas, politica) a partir de dados/."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[3]
DIR_DADOS = RAIZ_REPO / "dados"


@dataclass
class Sala:
    id: str
    nome: str
    capacidade: int
    recursos: list[str]


@dataclass
class Reserva:
    id: str
    sala: str
    inicio: str
    fim: str
    responsavel: str


@dataclass
class Store:
    """Estado em memoria do processo: salas (fixas) e reservas (mutaveis)."""

    salas: list[Sala] = field(default_factory=list)
    reservas: list[Reserva] = field(default_factory=list)
    politica_texto: str = ""
    politica_versao: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _proximo_numero: int = 1

    def sala_por_id(self, sala_id: str) -> Sala | None:
        return next((s for s in self.salas if s.id == sala_id), None)

    def criar_reserva(self, sala: str, inicio: str, fim: str, responsavel: str) -> Reserva:
        with self._lock:
            novo_id = f"res-{self._proximo_numero:04d}"
            self._proximo_numero += 1
            reserva = Reserva(id=novo_id, sala=sala, inicio=inicio, fim=fim, responsavel=responsavel)
            self.reservas.append(reserva)
            return reserva


_VERSAO_RE = re.compile(r"^versao:\s*(\S+)", re.MULTILINE)


def _extrair_versao(texto: str) -> str:
    m = _VERSAO_RE.search(texto)
    if not m:
        raise ValueError("dados/politica-de-uso.md sem linha 'versao: <data>'")
    return m.group(1)


def _proximo_numero_inicial(reservas: list[Reserva]) -> int:
    maior = 0
    for r in reservas:
        try:
            n = int(r.id.removeprefix("res-"))
        except ValueError:
            continue
        maior = max(maior, n)
    return maior + 1


def carregar_store() -> Store:
    salas_json = json.loads((DIR_DADOS / "salas.json").read_text(encoding="utf-8"))
    reservas_json = json.loads((DIR_DADOS / "reservas.json").read_text(encoding="utf-8"))
    politica_texto = (DIR_DADOS / "politica-de-uso.md").read_text(encoding="utf-8")

    salas = [Sala(id=s["id"], nome=s["nome"], capacidade=s["capacidade"], recursos=list(s["recursos"])) for s in salas_json]
    reservas = [
        Reserva(id=r["id"], sala=r["sala"], inicio=r["inicio"], fim=r["fim"], responsavel=r["responsavel"])
        for r in reservas_json
    ]
    versao = _extrair_versao(politica_texto)

    store = Store(salas=salas, reservas=reservas, politica_texto=politica_texto, politica_versao=versao)
    store._proximo_numero = _proximo_numero_inicial(reservas)
    return store
