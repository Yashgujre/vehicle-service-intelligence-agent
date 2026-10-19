# Open WebUI pipe: Vehicle Service Intelligence

`vsia_pipe.py` is an Open WebUI Pipe function. It adds one model, "Vehicle Service Intelligence", to the
model picker. Each question is sent to the n8n chat workflow (`workflows/n8n/04_rag_chat_webhook.json`),
which calls the VSIA API's `POST /chat`. The answer comes back with citation ids; the pipe renders a
"Sources" list and emits one `source` event per citation so Open WebUI shows citation chips.

```
Open WebUI  --POST {question, messages, user_id}-->  n8n /webhook/vsia-chat  -->  vsia-api /chat
            <--{answer, citations, refused}-------
```

## Install

1. Sign in to Open WebUI as an admin (the first account created on a fresh instance is the admin).
2. Admin Panel, Functions, then "+" (or Import), and paste or upload `openwebui/vsia_pipe.py`.
3. Save, then enable the function.
4. Open the function's Valves (gear icon) and set:

| Valve | Default | Set to |
|---|---|---|
| `N8N_WEBHOOK_URL` | `http://n8n:5678/webhook/vsia-chat` | Keep the default on the Compose stack (internal Docker DNS). Use `https://<N8N_FQDN>/webhook/vsia-chat` if Open WebUI runs elsewhere |
| `N8N_BEARER` | empty | The token stored in the n8n "n8n webhook bearer" Header Auth credential (without the `Bearer ` prefix) |
| `TIMEOUT_S` | `120` | Raise if hosted LLM answers time out |

5. Start a new chat and pick "Vehicle Service Intelligence".

The frontmatter line `requirements: httpx` tells Open WebUI to install `httpx` if it is missing (it is
normally already present).

## Behaviour

- Non-streaming: the pipe waits for one JSON body. n8n end-to-end streaming through Webhook and Respond to
  Webhook is unverified (ADR-0076).
- Status events: "Searching complaints and recalls", then "Done" (or "The assistant is unavailable").
- Citations: `recall:<campaign>` links to `https://www.nhtsa.gov/recalls?nhtsaId=<campaign>`.
  `complaint:<odi>` shows the ODI number only, because NHTSA has no stable public deep link per complaint.
- Refusals (out-of-scope questions) are shown as returned, with no sources.
- Failures (timeout, n8n down, API error) return a short message instead of raising, so the chat shows an
  answer bubble rather than a stack trace. If n8n returns its own 502 fallback answer, that text is shown.
- Only the latest user message is used as the question; the API's RAG router is single-turn. The full
  message list is still sent so a future multi-turn endpoint can use it.

## Test

```bash
pytest tests/test_openwebui_pipe.py
```

The test mocks `httpx` (no network) and checks the request payload and header, the Sources formatting,
source events, refusals, and error handling. The pipe has not been loaded into a running Open WebUI
instance yet (ADR-0008).
