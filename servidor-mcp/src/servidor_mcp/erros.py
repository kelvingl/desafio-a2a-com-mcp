"""Mensagens exatas de erro de execucao, fonte unica de verdade no enunciado."""

from __future__ import annotations


def erro_sala(sala_id: str) -> str:
    return f"Sala inexistente: {sala_id}"


ERRO_JANELA = "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00"
ERRO_DURACAO = "Duracao acima do limite: a politica permite no maximo 2 horas"
ERRO_INTERVALO = "Intervalo invalido: fim deve ser posterior a inicio"
ERRO_SEM_ALTERNATIVA = "Sem alternativas disponiveis no intervalo"
