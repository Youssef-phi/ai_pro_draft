# VentureBoard

An open-source team of AI agents that co-founds a startup with a human founder. It takes a founder's brief toward a validated, sellable **digital** product, shows its work as a live boardroom (one animated face and voice per department), and says **"don't launch this"** when the evidence is weak. Licence: MIT.

## Quickstart

```bash
docker compose up
```

Then open <http://localhost:8000>. No API key is needed: the app uses a local open-weight model (`qwen3:8b`) served by Ollama, which is downloaded on the first start (about 5 GB; the page shows a notice until it is ready).

Without Docker: `pip install -r requirements.txt`, start Ollama, then `python -m uvicorn app:app --port 8000`. Command line: `python orchestrator.py run --brief briefs/good_idea.json`. Tests: `python -m pytest`.

## What works and what is mocked

| Step | Status | Notes |
|---|---|---|
| Rule pre-filter (excluded products, must-never requests) | **Working** | Code only, runs before any model call. `guardrails.py` |
| Phase 1 Discover: research, opportunities scored against alternatives, market definition | **Working** | Free web search (DuckDuckGo, Wikipedia, Hacker News). Claims are relabelled in code: a URL not retrieved in the run becomes `ASSUMPTION` |
| Phase 1: Mom Test customer interviews | **STUBBED** | The system writes the interview plan and questions. It does not run or simulate interviews; the founder pastes real notes |
| Phase 2 Validate: Lean Canvas, landing-page draft, demand-test plan | **Working** | The waitlist target is fixed in code before the test |
| Phase 2: publishing the landing page, waitlist form | **MOCKED** | "Publish" writes a local HTML file after founder approval. The form collects nothing |
| Phase 2: waitlist sign-up count | **Working** (founder input) | Only the founder types the real number. The system never generates sign-ups |
| Phase 3 Build: MVP, user docs, automated checks | **Working** (limited) | Builds content-type digital products (checklist, guide, template pack, planner) as a single HTML file. Custom software MVPs are **STUBBED** (not built) |
| Phase 4 Commercial setup: pricing, draft terms, privacy and refund policy | **Working** | Every policy is labelled "DRAFT, not legal advice; have a lawyer review." No payments are set up |
| Phase 5 Launch: store page and launch posts | **Working** (drafts) | Publishing them is **MOCKED** (local files, after founder approval) |
| Phase 5: checkout, payment events, delivery, refunds, payouts, reconciliation | **MOCKED** | No payment provider, real or sandbox. `payments.py`, `webhooks.py`, `delivery.py`, `refunds.py`, `reconcile.py` |
| Phase 5: sending the delivery message | **MOCKED** | Written to a local outbox file after founder approval |
| Phase 6 Operate and learn: support answers, metrics, persevere-or-pivot memo | **Working** | Based only on real evidence; there are no real sales |
| Gates: Advocate, Critic, Chair, hard thresholds in code, founder decision | **Working** | `panel.py`, `gates.py`. The Chair recommends, code can only make it stricter, the founder decides |
| Founder approval before anything is published, sent, delivered or refunded | **Working** | Enforced in code: the functions raise without a signed approval record. `approval.py` |
| Decision log and cost per run | **Working** | `decision_log.json`, one entry per agent action |
| Boardroom UI: faces, expressions, voices, captions, claim badges, mute | **Working** | Voices use the browser's built-in speech synthesis |

Model-backed steps are exercised in the test suite with a `STUBBED` test model (in `tests/` only). Files in `outputs/` come only from real runs of the pipeline.

## Architecture

A founder brief enters a code-level rule pre-filter, then a router (`orchestrator.py`) runs six phases, calling one specialist agent per department with only the context that agent needs. Every phase ends at a gate: an Advocate and a Critic argue on different model families, a neutral Chair scores a fixed rubric, thresholds fixed in code (`gates.py`) can turn a GO into repeat, pivot or stop, and the founder approves or overrides. Any outside effect (publish, send, deliver, refund) must pass `approval.py`, and all of them are mocked. Every agent action is appended to `decision_log.json` with its sources, model and cost. Full design with diagrams: [ARCHITECTURE.md](ARCHITECTURE.md).

## Models and free resources

- **Default, no key, no cost:** `qwen3:8b` (open weights) through Ollama, started by `docker compose up`. `gpt-oss:20b` also works on machines with 16 GB RAM or more (`OLLAMA_MODEL=gpt-oss:20b`).
- **Optional, free for eligible users:** your own Hack Club AI key in `.env` (`LLM_API_KEY`) runs the open-weight models `z-ai/glm-5.3` (orchestrator, Chair, Advocate), `z-ai/glm-5.3-flash` (department agents) and `deepseek/deepseek-v4.1-flash` (Critic, a different model family). A free NVIDIA Build key (`NVIDIA_API_KEY`) is used as a fallback.
- Only allow-listed open-weight models are called (`config.py`). The chain falls back Hack Club → NVIDIA → local Ollama, so the app always runs without paying.
- Each person uses their own key in their own untracked `.env`. Keys are never committed, logged or sent to the browser, and the app listens on `127.0.0.1` only.
- Research tools are free and key-less. Voices are the browser's own speech synthesis.

## Cost per run

About **$0.00 per run** on the default local model (Ollama on your machine; no metered API is called).

On hosted models the real cost is computed from the provider's token prices for every call, written to the `cost` field of `decision_log.json`, totalled in the `run_finished` entry (`run_total_cost_usd`) and shown at the end of each run. A daily budget cap (`DAILY_BUDGET_USD`, default $2.50) stops metered use before the provider's limit.

## Demo video

Link to be added (3 minutes at most).

## What our system will NOT do

- Promise income, earnings or success.
- Create fake reviews, testimonials, sign-ups, waitlist numbers, countdown timers or other false urgency.
- Impersonate the founder, a customer, a real person or another brand.
- Hold, move or refund money; create accounts; ask for or store passwords or card numbers. There are no payments of any kind: everything payment-related is mocked.
- Publish, send, spend or sign anything without the founder's explicit approval.
- Put core features behind a paywall.
- Work on excluded products: physical goods; financial, investment or crypto products; health or legal advice products. It recommends stopping or pivoting to an allowed digital product.
- Treat simulated or mocked results as evidence, or present an assumption as a fact.
- Call closed-weight or paid models.

These limits are enforced in code (`guardrails.py`, `approval.py`, `gates.py`) and covered by tests in `tests/` using the prompts in `evals/`.

## How the project stays alive after the hackathon

- **Maintainers:** the founding team keeps maintaining `main`; changes go through pull requests with the test suite as the bar.
- **Roadmap:** real (opt-in) publishing and payment adapters behind the same approval layer; custom software MVPs; founder-run interview capture; more research sources; multi-language voices. See the roadmap in [ARCHITECTURE.md](ARCHITECTURE.md).
- **Community:** MIT licence, one prompt file and one code file per agent so new departments are easy to add, `evals/` open to new trick prompts, issues labelled for first-time contributors.
- **Funding:** runs at zero cost on local models, so it needs no funding to stay usable. Hosted costs stay with each user's own key. Any future funding would come from grants or sponsorship for maintenance, never from paywalled core features.
