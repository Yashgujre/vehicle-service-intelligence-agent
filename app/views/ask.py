"""Ask the data: the RAG chat (router plan, hybrid retrieval over complaints and recalls, SQL counts for
aggregate questions, answers that cite only retrieved IDs). Without an AI model it shows the retrieved
sources only."""

import re

import streamlit as st

import data
import hosted
import ui
from vsia import llm, rag, retrieval

src = ui.source()
choice = hosted.model_picker()

st.title("Ask the data")
st.markdown("Ask about defects, complaints and recalls for electric and hybrid SUVs and pickups (model years "
            "2021-2026). Answers cite the complaints and recalls they use; citations the sources do not support "
            "are removed. Questions outside this data are refused.")
st.caption(f"AI model: {choice.label}. Change it in the sidebar.")

if src.mode != "live":
    st.warning(f"Chat needs the project database, which is not available in this deployment ({src.reason}).")
    st.stop()

EXAMPLES = ["Which recalls cover phantom braking on the Tesla Model Y?",
            "What are the most common complaint components for the Hyundai Ioniq 5?",
            "Are there recalls for the Ford Mustang Mach-E 12 volt battery?",
            "What is the weather in Detroit tomorrow?"]
_CITE = re.compile(r"\[(recall|complaint):([A-Z0-9]+)\]")


def _linkify(text: str) -> str:
    def sub(m: re.Match) -> str:
        kind, ident = m.group(1), m.group(2)
        if kind == "recall":
            return f"[[recall {ident}]]({data.recall_url(ident)})"
        return f"[complaint {ident}]"
    return _CITE.sub(sub, text)


def _sources_only(question: str) -> dict:
    hits = retrieval.search_sources(question, namespaces=("recalls", "recall_docs", "complaints"), top_k=6)
    lines = []
    for h in hits:
        if h.namespace == "complaints":
            ref = f"complaint {h.metadata.get('odi_number', h.id)}"
        else:
            camp = h.metadata.get("campaign_number", h.id)
            ref = f"[recall {camp}]({data.recall_url(camp)})"
        lines.append(f"- **{ref}**: {ui.escape_md(h.text[:220])}...")
    return {"answer": "Offline mode shows the most relevant sources without an AI-written answer. Choose an AI "
                      "model in the sidebar for a cited answer.\n\n" + "\n".join(lines), "citations": [],
            "refused": False, "plan": None, "latency_ms": None}


if "chat" not in st.session_state:
    st.session_state["chat"] = []

cols = st.columns(len(EXAMPLES))
clicked = None
for col, q in zip(cols, EXAMPLES):
    if col.button(q, key=f"ask_ex_{q}", width="stretch"):
        clicked = q

for turn in st.session_state["chat"]:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])
        if turn.get("caption"):
            st.caption(turn["caption"])

question = st.chat_input("Ask a question about vehicle defects and recalls", max_chars=500) or clicked
if question:
    st.session_state["chat"].append({"role": "user", "content": ui.escape_md(question)})
    with st.chat_message("user"):
        st.markdown(ui.escape_md(question))
    with st.chat_message("assistant"):
        caption = None
        if not choice.uses_ai:
            with st.spinner("Searching..."):
                res = _sources_only(question)
            content = res["answer"]
        else:
            chain, block = hosted.candidates(choice, calls_needed=2)
            content = block or ""
            for n, used in enumerate(chain, 1):
                try:
                    with st.spinner(f"Planning, retrieving and answering with {used.label}..."):
                        with llm.use_keys(used.keys), llm.fail_fast(n < len(chain)):
                            res = rag.answer(question, provider=used.provider, model=used.model)
                except llm.LLMError as e:
                    if hosted.unavailable(e.status, str(e)):
                        hosted.mark_unavailable(used, e.status)
                        content = ("The free-tier rate limit was hit. A per-minute limit clears within a minute; the "
                                   "daily limit resets at midnight Pacific time. Your own free key in the sidebar "
                                   "works right away." if e.status == 429 else
                                   "The free AI models are overloaded right now. Try again in a minute, or paste "
                                   "your own free key in the sidebar.")
                        continue
                    hosted.count_ai_calls(used, 1)
                    content = f"The AI call failed: {str(e)[:200]}"
                    break
                hosted.count_ai_calls(used, 2)
                content = _linkify(res["answer"])
                if res.get("refused"):
                    content += "\n\n_Refused: the question is outside this dataset or the sources do not answer it._"
                plan = res.get("plan") or {}
                filters = ", ".join(f"{k}={v}" for k, v in plan.items() if k in ("make", "model_year", "component") and v)
                caption = (f"Intent: {plan.get('intent', 'n/a')}"
                           + (f"; filters: {filters}" if filters else "")
                           + f"; {len(res.get('citations', []))} verified citation(s); "
                           f"{res.get('latency_ms', 0):,} ms; {used.label}"
                           + (" (backup model; the main model is rate limited or overloaded right now)."
                              if used.model != choice.model else "."))
                break
        st.markdown(content)
        if caption:
            st.caption(caption)
    st.session_state["chat"].append({"role": "assistant", "content": content, "caption": caption})

if st.session_state["chat"] and st.button("Clear conversation"):
    st.session_state["chat"] = []
    st.rerun()
