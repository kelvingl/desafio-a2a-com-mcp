# A Ponte: um agente A2A com MCP por dentro

Entrega do desafio: um servidor MCP (Streamable HTTP, porta `7301`) com as três
tools, o resource de política e o ciclo completo de MRTR na reserva, e um agente
(porta `7300`) que é host MCP por dentro e servidor A2A por fora, com a Task
pausando em `TASK_STATE_INPUT_REQUIRED` quando o servidor MCP pede uma escolha.

Stack: Python 3.10+, SDK oficial `mcp==2.3.0` (v2, revisão `2026-07-28`) nos dois
processos, mais `starlette`/`uvicorn` no agente para o binding JSON-RPC do A2A.

## Como rodar

Os dois processos são projetos Python independentes (`servidor-mcp/` e `agente/`),
cada um com seu próprio `pyproject.toml` e seu próprio ambiente virtual.

### 1. Gere e exporte o segredo do `requestState`

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Isso imprime uma string hexadecimal de 64 caracteres (32 bytes de aleatoriedade).
Exporte o valor gerado como `REQUEST_STATE_SECRET` **no terminal do servidor MCP**
antes de subir o processo (não há valor nenhum fixado no repositório):

```bash
# Linux/macOS
export REQUEST_STATE_SECRET="<cole aqui o valor gerado>"

# Windows (PowerShell)
$env:REQUEST_STATE_SECRET = "<cole aqui o valor gerado>"
```

### 2. Suba o servidor MCP (terminal 1)

```bash
cd servidor-mcp
python3 -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
python -m servidor_mcp.main
```

Fica escutando em `http://127.0.0.1:7301/mcp`. Deixe o stderr visível: é nele que
aparecem o `tools/list` anterior ao primeiro `tools/call` e o `traceparent`
propagado pelo agente.

Portas e caminhos são parametrizáveis por variável de ambiente (`MCP_HOST`,
`MCP_PORT`), com os valores padrão já sendo os exigidos (`127.0.0.1:7301`,
endpoint `/mcp`).

### 3. Suba o agente (terminal 2)

```bash
cd agente
python3 -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
python -m agente.main
```

Fica escutando em `http://127.0.0.1:7300`, com o card em
`/.well-known/agent-card.json` e o endpoint JSON-RPC em `/a2a`. No startup ele
conecta no servidor MCP (`MCP_URL`, padrão `http://127.0.0.1:7301/mcp`), roda um
`tools/list` e lê o resource `politica://uso` antes de aceitar qualquer
`SendMessage` — por isso o servidor MCP precisa subir primeiro.

Portas parametrizáveis por `AGENTE_HOST`/`AGENTE_PORT` (padrão `127.0.0.1:7300`).

### 4. Rode o validador

Com os dois processos recém-iniciados (o validador cria reservas reais; rodá-lo
duas vezes seguidas sem reiniciar os processos produz falsos negativos):

```bash
python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
```

## Onde a ponte acontece

O `input_required` do servidor MCP vira `TASK_STATE_INPUT_REQUIRED` em
[`agente/src/agente/bridge.py`](agente/src/agente/bridge.py), no método
`Ponte._tratar_resultado`: quando o resultado do `tools/call` é uma instância de
`InputRequiredResult`, o código lê a única entrada de `inputRequests`, extrai o
`enum` de alternativas do `requestedSchema`, guarda `chave` + `requestState` +
o pedido original em `task.pending` (ligado àquela Task, nunca global) e muda
`task.state` para `TASK_STATE_INPUT_REQUIRED`, escrevendo a linha
`alternativas: <...>` como mensagem da Task.

O `requestState` volta para o servidor em `Ponte._continuar`, mais abaixo no
mesmo arquivo: ao receber a continuação (`escolha=<id>` ou `escolha=recusar`),
o método monta a resposta da elicitation (`action: accept/decline`) e chama
`self.mcp.retomar(...)`, que em
[`agente/src/agente/mcp_client.py`](agente/src/agente/mcp_client.py)
(`ClienteMCP.retomar`) refaz o `tools/call` original via
`session.call_tool(..., request_state=request_state, allow_input_required=True)`.
O SDK do cliente MCP gera sozinho um id de JSON-RPC novo para esse request — é
por isso que o par inicial/retry nunca repete id. O agente nunca abre, assina
nem reconstrói o conteúdo do `requestState`: ele só guarda a string opaca que
recebeu e a ecoa de volta sem tocar nela.

Do lado do servidor, a tradução inversa (o que fazer quando o `requestState`
volta) está em
[`servidor-mcp/src/servidor_mcp/app.py`](servidor-mcp/src/servidor_mcp/app.py),
na tool `reservar_sala`: se `ctx.request_state` não é `None`, o fluxo cai em
`_retomar`, que lê `ctx.input_responses` para decidir `accept`/`decline`.

## Decisões técnicas

- **Proteção do `requestState`**: em vez de montar HMAC/AEAD na mão, usei o
  utilitário de primeira classe que o próprio SDK `mcp` v2 já oferece para isso —
  `mcp.server.request_state.RequestStateBoundary` /`RequestStateSecurity`,
  conectado via `request_state_security=` no construtor do `MCPServer`
  (ver `servidor_mcp/app.py`). Na prática ele:
  - cifra e autentica o estado com **AES-256-GCM** (chave derivada da variável
    `REQUEST_STATE_SECRET` via HKDF-SHA256 — portanto o conteúdo não é só
    assinado, é opaco mesmo para quem interceptar o token);
  - **vincula o token ao pedido**: a sela carrega um digest do nome da tool e dos
    `arguments` originais, e rejeita o retry se o cliente reenviar argumentos
    diferentes dos que geraram o token (é o que faz o teste de "argumentos
    adulterados no retry" passar sem nenhum código extra meu: o framework
    recusa com `-32602` antes mesmo de `reservar_sala` rodar);
  - verifica expiração em tempo constante e rejeita qualquer token adulterado
    com `-32602` (`Invalid or expired requestState`), nunca com um erro 500.
  - A `REQUEST_STATE_SECRET` é lida exclusivamente de variável de ambiente
    (`servidor_mcp/app.py:_segredo_request_state`), nunca do código-fonte.
- **Validade do `requestState`**: 900 segundos (15 minutos) — dentro da janela
  de 5 a 30 minutos pedida no enunciado (`TTL_REQUEST_STATE_SEGUNDOS` em
  `app.py`). Sobrevive a um restart do processo porque a chave vem de fora
  (env var) e o payload inteiro (sala/alternativas/chave do resolver) viaja
  dentro do próprio token — o servidor não guarda nada em memória entre o
  `input_required` e o retry.
- **Estado das Tasks**: 100% em memória do processo do agente, num dicionário
  `task_id -> Task` dentro de `agente/src/agente/tasks.py` (`TaskStore`,
  protegido por um lock simples). Cada `Task` carrega seu próprio `pending`
  (chave + `requestState` + pedido original), então duas Tasks pausadas ao
  mesmo tempo nunca compartilham ou trocam `requestState` entre si. Nada disso
  sobrevive a um restart do agente — e o enunciado não pede que sobreviva.

## Saída do validador

Execução com os dois processos recém-iniciados (branch `main`, 36/36):

```
trace-id desta execucao: 654c31cb9e86ddb338d3dafca1597c61
procure esse valor no stderr do servidor MCP para conferir a propagacao do traceparent.

PASS 01 tools/list traz as tres tools
PASS 02 toda tool tem inputSchema de objeto
PASS 03 listar_salas devolve structuredContent e o mesmo JSON em texto
PASS 04 _meta sem protocolVersion devolve -32602 e HTTP 400
PASS 05 _meta sem clientCapabilities devolve -32602 e HTTP 400
PASS 06 tool inexistente e recusada, por -32602 ou por isError
PASS 07 resources/read de politica://uso devolve a politica
PASS 08 resources/read de URI inexistente devolve -32602
PASS 09 sala inexistente devolve isError com a mensagem exata
PASS 10 fora da janela devolve isError com a mensagem exata
PASS 11 duracao acima de 2h devolve isError com a mensagem exata
PASS 12 intervalo invertido devolve isError com a mensagem exata
PASS 13 conflito devolve input_required com inputRequests e requestState
PASS 14 a elicitation e form mode e oferece as alternativas na ordem certa
PASS 15 conflito sem a capability elicitation devolve -32021 e HTTP 400
PASS 16 retry com inputResponses e requestState conclui a reserva
PASS 17 requestState adulterado e rejeitado com -32602
PASS 18 argumentos adulterados no retry nao tomam efeito
PASS 19 recusa conclui sem reservar e sem isError
PASS 20 conflito sem alternativa possivel devolve isError com a mensagem exata

PASS 21 agent card responde 200 no well-known com JSON
PASS 22 o card declara a interface JSON-RPC com url e versao 1.0
PASS 23 o card declara a skill reservar-sala
PASS 24 SendMessage com sala livre conclui a Task
PASS 25 o artifact chama reserva e traz a versao da politica
PASS 26 GetTask devolve id, contextId e estado corrente
PASS 27 SendMessage com sala ocupada pausa a Task
PASS 28 a Task pausada lista as alternativas na ordem certa
PASS 29 escolha fora do enum mantem a Task pausada
PASS 30 a continuacao conclui a Task na sala escolhida
PASS 31 SendMessage em Task terminal e recusado
PASS 32 a recusa termina a Task em CANCELED
PASS 33 duas Tasks pausadas ao mesmo tempo concluem cada uma com a sua reserva
PASS 34 nenhuma resposta A2A carrega o requestState
PASS 35 sala inexistente termina a Task em FAILED com a mensagem da tool
PASS 36 o agente e deterministico: o mesmo pedido produz a mesma pausa

resumo: 36 passaram, 0 falharam, de 36 verificacoes
```

## Estrutura

```
.
├── README.md
├── dados/                 (do starter, nao alterado)
├── validador/              (do starter, nao alterado)
├── exemplos/               (do starter, nao alterado)
├── servidor-mcp/
│   ├── pyproject.toml
│   └── src/servidor_mcp/
│       ├── app.py          # MCPServer: tools, resource, MRTR, requestState, logging
│       ├── main.py         # entrypoint (Streamable HTTP, porta 7301)
│       ├── dados.py        # carga de dados/ em memoria
│       ├── politica.py     # janela de uso, duracao, conflitos, alternativas
│       └── erros.py        # mensagens exatas de erro de execucao
└── agente/
    ├── pyproject.toml
    └── src/agente/
        ├── mcp_client.py   # host MCP: Client unico, tools/list, resource, reservar/retomar
        ├── bridge.py       # a ponte: input_required <-> TASK_STATE_INPUT_REQUIRED
        ├── tasks.py        # Task, TaskStore (estado em memoria, por processo)
        ├── a2a_rpc.py      # endpoint /a2a (SendMessage, GetTask) e o agent card
        ├── card.py         # Agent Card v1.0
        ├── parsing.py      # parse do formato fixo de pedido/escolha
        ├── trace.py        # extracao/propagacao do traceparent
        └── main.py         # entrypoint (porta 7300)
```
