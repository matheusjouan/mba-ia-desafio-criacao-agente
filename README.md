# Residencial Aurora: assistente virtual dos moradores

API em Python com um assistente construído com **Google ADK 2.12.0**. Pelo chat, o
morador reserva e cancela áreas comuns, autoriza visitantes e tira dúvidas sobre o
regulamento. O modelo conduz a conversa, mas **as regras críticas estão no código**:
nenhuma mensagem consegue furar uma regra do condomínio.

- Stack: Python 3.12 · uv · `google-adk==2.12.0` · FastAPI · SQLite
- API: `http://localhost:8000`, seguindo o contrato do desafio

---

## Arquitetura

```
                       ┌──────────────────────────── FastAPI (aurora/api.py) ───────────────────────────┐
  POST /sessoes ──────►│ cria a sessão com state {"apartamento": "101"}                                 │
  POST .../mensagens ─►│ Runner do ADK ─► porteiro (agente principal)                                   │
  POST .../confirmacoes│   valida o id pendente (409) e devolve FunctionResponse adk_request_confirmation│
  GET  .../eventos ───►│ eventos completos da sessão                                                    │
  GET  /apartamentos/..│ lê o banco direto, sem modelo                                                  │
                       └───────────────────────────────────────────────────────────────────────────────┘
        porteiro ──transferência──► reservas   (tools de reserva; confirmação quando há taxa)
                 ──transferência──► visitantes (tools de visitante; confirmação sempre)
                 ──AgentTool──────► regulamento (lê 1 capítulo por vez, numa sessão isolada)

  var/sessoes.db    → sessões e eventos do ADK (SqliteSessionService)
  var/condominio.db → apartamentos, áreas, reservas, visitantes (estado inicial vindo de dados/)
```

### Agentes

Todos estão em [`aurora/agents/agent.py`](aurora/agents/agent.py).

| Agente | Responsabilidade | Como é acionado | Por quê |
|---|---|---|---|
| `porteiro` (principal) | Conversa com o morador, identifica o assunto e encaminha. Não tem tools de dados e **não recebe o regulamento nas instruções**. | É o `root_agent` do Runner. | Mantém o contexto principal pequeno e só roteia. |
| `reservas` | Lista áreas, consulta disponibilidade (só livre/ocupada), lista, cria e cancela reservas do próprio apartamento. | **Sub-agente por transferência** (`sub_agents`). | As tools com confirmação ficam no agente que recebe a transferência. Assim o Runner devolve a resposta da confirmação ao autor do pedido, inclusive com a sessão persistida e depois de reiniciar a API (testado). A conversa pode continuar com o especialista, por exemplo quando ele pergunta uma data. |
| `visitantes` | Lista os visitantes do próprio apartamento e autoriza novas entradas. | **Sub-agente por transferência**. | Mesmo motivo do `reservas`: autorizar visitante sempre pede confirmação. |
| `regulamento` | Responde dúvidas lendo **um capítulo por vez** de `dados/regulamento.md`. Nas instruções, recebe só o índice de títulos. | **`AgentTool`** no porteiro. | O `AgentTool` roda o especialista num `Runner` próprio, com sessão em memória. A leitura do capítulo nunca entra nos eventos da sessão do morador, só a resposta final (Garantia 4). |

Callbacks usados pelos agentes:

- `traduzir_negacao` ([`aurora/tools.py`](aurora/tools.py)), um `after_tool_callback`. Troca o `{"error": "This tool call is rejected."}` do ADK por um resultado explícito, `negada_pelo_morador`. Sem isso, o modelo tratava a negação como falha técnica e repetia a chamada.
- `lembrar_mensagem_atual` ([`aurora/agents/agent.py`](aurora/agents/agent.py)), um `before_model_callback`. Depois de uma transferência, o ADK entrega o histórico ao especialista como mensagens "For context", e o pedido atual fica enterrado entre elas. O callback acrescenta à requisição um lembrete com a mensagem atual do morador. O lembrete não é gravado na sessão.

### Dados

- `dados/*.json` e `dados/regulamento.md` são só o **estado inicial** e nunca são alterados.
- [`aurora/db.py`](aurora/db.py) cria o SQLite `var/condominio.db`. O comando de restauração recarrega dele reservas e visitantes. Cancelar uma reserva só muda o `status` para `cancelada`.
- [`aurora/repositorio.py`](aurora/repositorio.py) concentra as consultas. Tudo que lê ou grava reservas e visitantes recebe o apartamento e filtra por ele no próprio SQL.
- [`aurora/runtime.py`](aurora/runtime.py) contém o `SqliteSessionService` (`var/sessoes.db`), o `Runner`, uma trava por sessão e o cálculo das confirmações pendentes.

### Modelo

[`aurora/modelo.py`](aurora/modelo.py) escolhe o modelo:

- **Gemini** (padrão do desafio): usado quando `GOOGLE_API_KEY` está preenchida. O modelo vem de `AURORA_MODELO`; se ela estiver vazia, usa `gemini-3.8-flash`. Consulte os modelos e limites do seu projeto no Google AI Studio.
- **Claude** (opcional, para desenvolvimento): usado quando `GOOGLE_API_KEY` está vazia e `ANTHROPIC_API_KEY` está preenchida, pela classe `AnthropicLlm` do próprio ADK. O modelo padrão é `claude-haiku-5-5`. Nesse caso o raciocínio estendido fica desligado, porque a API da Anthropic recusa blocos de raciocínio reenviados com um histórico diferente do original, e o lembrete do `before_model_callback` muda a requisição a cada turno.

---

## Garantias

Em todas as garantias, o modelo só escolhe **qual** tool chamar. O que é permitido
fica decidido no código das tools, no banco e na API.

### Garantia 1: cobrança ou acesso só com confirmação

| Onde | Trecho |
|---|---|
| [`aurora/tools.py`](aurora/tools.py), registro das tools | `FunctionTool(reservar_area, require_confirmation=_reserva_requer_confirmacao)` e `FunctionTool(autorizar_visitante, require_confirmation=True)` |
| [`aurora/tools.py`](aurora/tools.py), `_reserva_requer_confirmacao` | Pede confirmação quando a área tem `taxa > 0` (lida do banco) e a data está livre. A quadra (taxa 0) não pede. |
| [`aurora/tools.py`](aurora/tools.py), `reservar_area` / `autorizar_visitante` | **Segunda trava**: `if cobranca and not _confirmado(tool_context)` e `if not _confirmado(tool_context)` recusam gravar sem `tool_context.tool_confirmation.confirmed`. |
| [`aurora/runtime.py`](aurora/runtime.py), `confirmacoes_pendentes` | As pendências saem do **histórico de eventos** do ADK: chamadas `adk_request_confirmation` sem `FunctionResponse` com o mesmo id. `detalhes` são os argumentos da chamada original (área e data, ou nome e data). |
| [`aurora/runtime.py`](aurora/runtime.py), `responder_confirmacao` | Sob a trava da sessão: se o id não está pendente **nesta sessão**, devolve `None` sem executar nada. Senão, envia `FunctionResponse(name="adk_request_confirmation", response={"confirmed": ...})` ao Runner. |
| [`aurora/api.py`](aurora/api.py), `post_confirmacao` | `None` vira **409**. Um id já respondido deixa de estar pendente, então o reenvio também recebe 409, e a ação executa uma única vez. |

**Por que não depende do modelo:** escrever "já estou confirmando aqui" na conversa
não cria um `FunctionResponse` de `adk_request_confirmation`. Só a rota de
confirmações cria esse evento. E mesmo que o fluxo do ADK fosse contornado, a
própria tool se recusa a gravar sem a aprovação registrada.

### Garantia 2: cada sessão pertence a um apartamento

| Onde | Trecho |
|---|---|
| [`aurora/runtime.py`](aurora/runtime.py), `criar_sessao` | `state={CHAVE_APARTAMENTO: apartamento}`: o apartamento é gravado uma única vez, na criação. Nenhuma tool nem a API alteram essa chave depois. |
| [`aurora/tools.py`](aurora/tools.py), `_apartamento` | `tool_context.state.get(CHAVE_APARTAMENTO)`. **Nenhuma tool tem parâmetro `apartamento`**, então o modelo não tem como escolher outro. |
| [`aurora/repositorio.py`](aurora/repositorio.py), `reservas_do_apartamento`, `cancelar_reservas`, `visitantes_do_apartamento` | `WHERE apartamento = ?` no SQL. Cancelar a reserva de outro apartamento simplesmente não encontra nada. |
| [`aurora/repositorio.py`](aurora/repositorio.py), `data_ocupada` / [`aurora/tools.py`](aurora/tools.py), `verificar_disponibilidade` | A conferência de agenda devolve só `livre`/`ocupada`. Uma reserva recusada devolve só `indisponivel`, sem código nem apartamento do dono. |

**Por que não depende do modelo:** os dados de outros apartamentos nunca chegam ao
modelo, porque nenhuma tool os devolve. Então não há o que ele repita, mesmo
convencido. Os prompts só evitam que o modelo recuse pedidos legítimos do próprio
morador.

### Garantia 3: nada se perde no reinício

| Onde | Trecho |
|---|---|
| [`aurora/runtime.py`](aurora/runtime.py) | `session_service = SqliteSessionService(str(DB_SESSOES))`: sessões e eventos ficam em `var/sessoes.db`. |
| [`aurora/db.py`](aurora/db.py) | Reservas e visitantes ficam em `var/condominio.db`. A API só recarrega `dados/` quando o banco está vazio (`lifespan` em [`aurora/api.py`](aurora/api.py)). |

Testado: parar e subir a API mantém a mesma quantidade de eventos, aceita novas
mensagens e **aprova uma confirmação criada antes do reinício**.

### Garantia 4: o regulamento é consultado, não carregado

| Onde | Trecho |
|---|---|
| [`aurora/regulamento.py`](aurora/regulamento.py), `capitulos` / `indice` | Divide `regulamento.md` pelos cabeçalhos `## Capítulo`. `indice()` devolve só os títulos. |
| [`aurora/tools.py`](aurora/tools.py), `ler_capitulo` | Devolve **um** capítulo pelo número. |
| [`aurora/agents/agent.py`](aurora/agents/agent.py), `INSTRUCAO_REGULAMENTO` e `tools=[AgentTool(regulamento)]` | O especialista recebe só o índice. O porteiro o aciona como `AgentTool`, que roda numa sessão própria em memória: a chamada a `ler_capitulo` e o texto do capítulo não entram nos eventos da sessão do morador, só a resposta final. |
| [`aurora/agents/agent.py`](aurora/agents/agent.py), `INSTRUCAO_PORTEIRO` | Não contém o regulamento. |

**Por que não depende do modelo:** não existe tool que devolva o regulamento
inteiro, e o texto lido fica fora da sessão principal por construção do `AgentTool`.

### Garantia 5: dois moradores, uma reserva

| Onde | Trecho |
|---|---|
| [`aurora/db.py`](aurora/db.py), `SCHEMA` | `CREATE UNIQUE INDEX ux_reserva_ativa_area_data ON reservas (area, data) WHERE status = 'ativa'` |
| [`aurora/repositorio.py`](aurora/repositorio.py), `criar_reserva` | Faz o `INSERT` direto, sem conferir antes. Se o índice recusar (`sqlite3.IntegrityError`), devolve `ResultadoReserva(criada=False)`, e a tool responde `indisponivel`: uma resposta normal, sem erro 500. |
| [`aurora/db.py`](aurora/db.py), `codigos_emitidos` | Todo código emitido fica registrado (PK). Códigos nunca se repetem, nem os de reservas canceladas, nem depois de uma restauração. |

**Por que não depende do modelo:** a exclusividade é decidida pelo SQLite **no
instante da gravação**, não numa conferência anterior. Testado com 2 e com 3
sessões aprovando a mesma área e data ao mesmo tempo: todas responderam 200 e
ficou exatamente uma reserva.

---

## Como rodar

### Pré-requisitos

- [uv](https://docs.astral.sh/uv/). Ele instala o Python 3.12 se necessário.
- Uma chave do [Google AI Studio](https://aistudio.google.com/apikey).
- Nenhum serviço externo: o armazenamento é SQLite, em `var/`.

### Variáveis do `.env`

```bash
cp .env.example .env
```

| Variável | Uso |
|---|---|
| `GOOGLE_API_KEY` | Chave do Google AI Studio (obrigatória para usar Gemini). |
| `GOOGLE_GENAI_USE_VERTEXAI` | `FALSE`: usa a API do AI Studio, não a Vertex AI. |
| `AURORA_MODELO` | Modelo Gemini dos agentes. Vazio = `gemini-3.8-flash`. |
| `ANTHROPIC_API_KEY` | Opcional. Usada só se `GOOGLE_API_KEY` estiver vazia. |
| `AURORA_MODELO_ANTHROPIC` | Opcional. Vazio = `claude-haiku-5-5`. |

### Comandos

```bash
uv sync                        # instala as dependências (google-adk==2.12.0)
uv run aurora-restaurar        # restaura reservas e visitantes ao estado de dados/
uv run aurora-api              # sobe a API em http://localhost:8000
```

- `uv run aurora-restaurar --sessoes` também apaga as conversas (`var/sessoes.db`). Sem a flag, as sessões são mantidas.
- Para ver transferências, chamadas de tool e confirmações durante o desenvolvimento: `uv run adk web aurora` (escolha o app `agents`).

### Exemplo rápido

```bash
curl -s -X POST localhost:8000/sessoes -H "Content-Type: application/json" -d '{"apartamento":"101"}'
# {"session_id":"..."}

curl -s -X POST localhost:8000/sessoes/<id>/mensagens -H "Content-Type: application/json" \
  -d '{"texto":"Reserve o salão de festas para 2030-04-20"}'
# {"resposta":"","confirmacoes_pendentes":[{"id":"adk-...","acao":"reservar_area",
#   "detalhes":{"area":"salao-de-festas","data":"2030-04-20","taxa":150.0}}]}

curl -s -X POST localhost:8000/sessoes/<id>/confirmacoes -H "Content-Type: application/json" \
  -d '{"id":"adk-...","confirmado":true}'
```
