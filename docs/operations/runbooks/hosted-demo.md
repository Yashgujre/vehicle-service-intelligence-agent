# Runbook: deploy and run the free hosted demo

The public demo is the Streamlit app on Streamlit Community Cloud, running the agent in-process on a free
Gemini key, with the data downloaded from a GitHub release asset. Decisions: ADR-0088 to ADR-0092.

Cost: zero. Every piece runs on a free tier: Community Cloud, GitHub releases, the Gemini API free tier,
and optionally the Groq free tier.

## One-time setup

### 1. Free Gemini API key

1. Open [Google AI Studio](https://aistudio.google.com/apikey) and sign in with a Google account.
2. Create an API key in a project with no billing account linked. A project with billing becomes a paid
   tier and is charged per token; a project without billing stays on the free tier.
3. Put the key in the local `.env` as `GEMINI_API_KEY=...` (for the evaluation run), and keep it for the
   Streamlit secrets below. Never commit it.

### 2. Optional free Groq key (backup when the Gemini quota is used up)

Create a key at [GroqCloud](https://console.groq.com/keys). Add `GROQ_API_KEY=...` to `.env` and secrets.

### 3. Calibrate routing for Gemini (recommended before sharing)

```bash
python -m eval.run_eval all --provider gemini    # about 500 calls; within one day's free quota
python -m eval.run_eval compare                  # writes docs/evaluation/model-comparison.md
```

This writes `data/models/routing_gemini.json` and the Gemini calibrator. Without it, Gemini confidence uses
the fallback weights (ADR-0061) and the app says so.

### 4. Build and publish the data bundle

```bash
python scripts/build_demo_bundle.py              # prints sha256 and size
gh release create demo-data-v1 dist/vsia-demo-bundle.tar.gz \
  --title "Demo data v1" --notes "Redacted NHTSA demo database, vector index and models for the hosted app"
```

The download URL is
`https://github.com/<owner>/vehicle-service-intelligence-agent/releases/download/demo-data-v1/vsia-demo-bundle.tar.gz`.

### 5. Create the Streamlit app

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub and click **Create app**.
2. Repository `<owner>/vehicle-service-intelligence-agent`, branch `main`, main file
   `app/streamlit_app.py`. Pick a custom subdomain.
3. **Advanced settings:** Python 3.11. Secrets:

   ```toml
   GEMINI_API_KEY = "..."
   # GROQ_API_KEY = "..."          # optional backup
   VSIA_BUNDLE_URL = "https://github.com/<owner>/vehicle-service-intelligence-agent/releases/download/demo-data-v1/vsia-demo-bundle.tar.gz"
   VSIA_BUNDLE_SHA256 = "<sha256 printed by build_demo_bundle.py>"
   # VSIA_HOSTED_DAILY_LLM_CALLS = "400"
   ```

4. Deploy. The first start installs dependencies, then downloads the bundle (spinner on the page).

## Smoke test after every deploy

| Step | Expected |
|---|---|
| Open the app URL | "Try the agent" page loads; sidebar shows "Google Gemini, free (shared key)" |
| Pick a complaint, run the agent | Result in a few seconds; seven-step trace; NHTSA coding shown for comparison |
| "Prompt injection attempt" example | Route is human review with "possible prompt injection" as a reason |
| "Personal details" example | Trace shows redactions; the redacted text has no phone, email or VIN |
| "Ask the data", an example question | Cited answer with recall links; the weather question is refused |
| Human review page | The case from the first step is pending; a decision saves |
| Offline classifier option | Triage works with no AI call |

## Routine operations

- **Refresh data:** re-ingest and re-index locally, rebuild the bundle, publish a new release tag
  (`demo-data-v2`), update the two `VSIA_BUNDLE_*` secrets, then reboot the app from **Manage app**. The
  app downloads the new bundle because its checksum differs from the installed one.
- **Rotate the Gemini key:** create a new key, update the secret, reboot, then delete the old key.
- **App asleep:** Community Cloud sleeps apps after 12 hours without traffic. Any visitor can wake it with
  the button on the sleep page; it takes about a minute.

## Incidents

| Symptom | Likely cause | Action |
|---|---|---|
| "shared free key has reached today's limit" | Daily cap (ADR-0092) or Gemini daily quota | Expected under load; resets at midnight Pacific. The Google free tier allows 500 requests per day per project for this model, shared with any local use of the same key, so run evaluations with a separate key or project. Add `GROQ_API_KEY` as backup |
| Triage shows "free-tier rate limit was hit" | 15 requests per minute exceeded | Transient; wait a minute |
| "This app has gone over its resource limits" | Memory ceiling | Reboot from Manage app; see ADR-0089 revisit trigger |
| Warning "demo dataset could not be installed" and snapshot pages only | Bundle download failed, `VSIA_BUNDLE_SHA256` missing, or "bundle checksum mismatch" (secret and release asset disagree); the cause is in the warning | Fix the secret or re-copy the sha256 from the build output, then reboot (the install is tried once per process) |
| Ask page slow on first question | Embedding model download after a cold start (ADR-0090) | Expected once per start |
