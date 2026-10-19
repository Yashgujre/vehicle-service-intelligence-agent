"""Human review: pending low-confidence triage records; accept or correct each one (writes through
vsia.review.decide). Disabled in read-only or demo mode."""

import streamlit as st
import ui

import data
from vsia.schemas import ReviewDecision

src = ui.source()
st.title("Human review")
st.caption("Records below the confidence threshold, or flagged for possible prompt injection or LLM failure, "
           "wait here. Every decision becomes a label (source = review) that evaluation reuses.")

counts = data.cached(data.review_counts, src)
c = st.columns(4)
c[0].metric("Pending", f"{counts['pending']:,}")
c[1].metric("Accepted", f"{counts['accepted']:,}")
c[2].metric("Corrected", f"{counts['corrected']:,}")
done = counts["accepted"] + counts["corrected"]
c[3].metric("Correction rate", f"{counts['corrected'] / done * 100:.1f}%" if done else "n/a",
            help="Corrected divided by all resolved reviews")

if src.readonly:
    st.warning("Read-only mode: this deployment cannot write review decisions. Run the dashboard against a "
               "writable database (VSIA_READONLY unset) to accept or correct items.")

if "review_flash" in st.session_state:
    st.success(st.session_state.pop("review_flash"))

limit = st.select_slider("Items to show (lowest confidence first)", options=[5, 10, 20, 50], value=10)
items = data.cached(data.pending_reviews, src, limit)
if items.empty:
    if sum(counts.values()) == 0:
        ui.no_data("review_queue", "the review queue")
    else:
        st.info("No pending reviews. The queue is clear.")
    st.stop()

taxonomy = data.taxonomy()
levels = data.severity_levels()
sev_opts = list(levels)

for row in items.itertuples():
    odi = int(row.odi_number)
    title = (f"ODI {odi}: {int(row.model_year)} {row.make} {row.model} | {row.component} | {row.severity} | "
             f"confidence {row.confidence:.2f}")
    with st.expander(title, expanded=False):
        a, b = st.columns([3, 2])
        with a:
            st.markdown("**Complaint text** (PII redacted)")
            with st.container(border=True):
                st.markdown(ui.escape_md(row.summary) if row.summary else "_Not available in this data source._")
        with b:
            st.markdown(f"**Agent output:** {ui.escape_md(str(row.component))}, {row.severity}, provider "
                        f"{row.provider}")
            st.markdown("**Linked recalls:** " + (", ".join(f"[{x}]({data.recall_url(x)})"
                                                          for x in row.recall_campaigns) or "none"))
            reasons = row.review_reasons or ([row.reason] if row.reason else [])
            st.markdown("**Why it is here:** " + ("; ".join(ui.escape_md(r) for r in reasons) or "n/a"))

        with st.form(key=f"review_{row.queue_id}", border=True):
            decision = st.radio("Decision", ["Accept agent output", "Correct"], horizontal=True,
                                key=f"dec_{row.queue_id}", disabled=src.readonly)
            f1, f2 = st.columns(2)
            comp = f1.selectbox("Component", taxonomy,
                                index=taxonomy.index(row.component) if row.component in taxonomy else 0,
                                key=f"comp_{row.queue_id}", disabled=src.readonly)
            sev = f2.selectbox("Severity", sev_opts,
                               index=sev_opts.index(row.severity) if row.severity in sev_opts else 0,
                               format_func=lambda s: f"{s}: {levels[s].split(':')[0]}",
                               key=f"sev_{row.queue_id}", disabled=src.readonly)
            cands = list(row.candidates) or list(row.recall_campaigns)
            camps = st.multiselect("Recall campaigns (from the agent's candidate list)", cands,
                                   default=[x for x in row.recall_campaigns if x in cands],
                                   key=f"camps_{row.queue_id}", disabled=src.readonly)
            g1, g2 = st.columns([1, 3])
            reviewer = g1.text_input("Reviewer", value="analyst", key=f"who_{row.queue_id}",
                                     disabled=src.readonly)
            note = g2.text_input("Note (optional)", key=f"note_{row.queue_id}", disabled=src.readonly)
            submitted = st.form_submit_button("Save decision", type="primary", disabled=src.readonly)
        if submitted:
            accepted = decision.startswith("Accept")
            d = ReviewDecision(odi_number=odi, queue_id=int(row.queue_id), reviewer=reviewer or "analyst", accepted=accepted,
                               component=None if accepted else comp, severity=None if accepted else sev,
                               recall_campaigns=[] if accepted else camps, note=note or None)
            try:
                res = data.submit_review(src, d)
            except (data.ReadOnlyError, KeyError) as e:
                st.error(str(e))
            else:
                st.session_state["review_flash"] = (f"Saved: ODI {odi} {res['status']} as {res['component']}, "
                                                    f"{res['severity']}.")
                st.rerun()
