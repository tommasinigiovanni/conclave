<p align="center">
  <h1 align="center">🏛️ Conclave</h1>
  <p align="center"><strong>Don't ask one AI. Convene the council.</strong></p>
  <p align="center">
    A Claude Code skill that makes multiple LLMs debate, critique each other anonymously, and synthesize a single superior answer.
  </p>
  <p align="center">
    Inspired by <a href="https://github.com/karpathy/llm-council">Karpathy's LLM Council</a> · Built for <a href="https://docs.anthropic.com/en/docs/claude-code">Claude Code</a>
  </p>
</p>

<p align="center">
  <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License: Apache 2.0"></a>
  <a href="#quick-start"><img src="https://img.shields.io/badge/install-30%20seconds-brightgreen.svg" alt="Install in 30s"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://docs.anthropic.com/en/docs/claude-code"><img src="https://img.shields.io/badge/Claude%20Code-skill-6B4FBB.svg?logo=anthropic&logoColor=white" alt="Claude Code Skill"></a>
  <a href="https://openrouter.ai"><img src="https://img.shields.io/badge/OpenRouter-compatible-orange.svg" alt="OpenRouter Compatible"></a>
</p>
<p align="center">
  <img src="https://img.shields.io/badge/Claude-🟣-white.svg" alt="Claude">
  <img src="https://img.shields.io/badge/Gemini-🔵-white.svg" alt="Gemini">
  <img src="https://img.shields.io/badge/GPT-🟢-white.svg" alt="GPT">
  <img src="https://img.shields.io/badge/Grok-⚫-white.svg" alt="Grok">
  <img src="https://img.shields.io/badge/Llama-🟠-white.svg" alt="Llama">
  <img src="https://img.shields.io/badge/+200%20models-via%20OpenRouter-lightgrey.svg" alt="+200 models">
</p>

---

## The Problem

You ask Claude a question. You get a good answer. But was it the *best* answer? What if GPT would have caught an error? What if Gemini had a better approach?

## The Solution

```
You: /conclave deep Should I use PostgreSQL or MongoDB for my multi-tenant SaaS?

     ┌─────────┐  ┌─────────┐  ┌─────────┐
     │ Claude  │  │  Gemini │  │   GPT   │   Phase 1: Independent answers
     └────┬────┘  └────┬────┘  └────┬────┘
          │            │            │
          ▼            ▼            ▼
     ┌─────────────────────────────────────┐
     │  Anonymized Cross-Critique          │   Phase 2: Each model critiques
     │                                     │   "Response A" and "Response B"
     │  Claude → rates Gemini & GPT        │   (identities hidden to prevent
     │  Gemini → rates Claude & GPT        │    favoritism)
     │  GPT    → rates Claude & Gemini     │
     │                                     │
     │  FINAL RANKING: C > A > B           │
     └──────────────────┬──────────────────┘
                        ▼
     ┌─────────────────────────────────────┐
     │  Claude Code Synthesis              │   Phase 3: Best of all worlds
     │  (no extra API call — Claude Code   │   Claude Code reads everything
     │   synthesizes directly)             │   and produces the final answer
     │                                     │
     │  Consensus (high confidence)        │
     │  Unique insights per model          │
     │  Resolved disagreements             │
     │  Aggregate rankings                 │
     │  Final unified answer               │
     └─────────────────────────────────────┘
```

## Why Conclave?

| Feature | Conclave | Karpathy's LLM Council | the-llm-council |
|---------|----------|----------------------|-----------------|
| **Claude Code skill** | ✅ `/conclave` | ❌ Web app only | ✅ Plugin |
| **3 depth levels** | ✅ quick/standard/deep | ❌ Always full | ❌ Always full |
| **Anonymized review** | ✅ | ✅ | ❌ |
| **Aggregate ranking** | ✅ | ✅ | ❌ |
| **Multi-turn sessions** | ✅ `--session` | ❌ | ❌ |
| **Cost estimation** | ✅ `--estimate` | ❌ | ❌ |
| **Real-time progress** | ✅ stderr progress | ❌ | ❌ |
| **Retry + backoff** | ✅ Exponential | ❌ | ❌ |
| **`.env` config** | ✅ Swap models in 1 line | Python edit | ✅ |
| **OpenRouter support** | ✅ 1 key for all | ✅ | ✅ |
| **Direct API keys** | ✅ Also supported | ❌ | ✅ |
| **Minimal dependencies** | ✅ httpx only (`pip install .`) | React + FastAPI + uv | pip install |
| **Custom prompts** | ✅ templates.yaml | ❌ | ❌ |
| **Health check** | ✅ `doctor` command | ❌ | ✅ |

## Quick Start

### 1. Install (30 seconds)

```bash
git clone https://github.com/tommasinigiovanni/conclave.git ~/.claude/skills/conclave
pip install ~/.claude/skills/conclave   # installs httpx automatically
```

Or install in editable/dev mode for development:
```bash
pip install -e "~/.claude/skills/conclave[dev]"
```

### 2. Configure

```bash
mkdir -p ~/.config/conclave
cp ~/.claude/skills/conclave/.env.template ~/.config/conclave/.env
```

Edit `~/.config/conclave/.env` with your API keys and preferred models:

```bash
# ── API Keys ──────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...         # https://console.anthropic.com/
GOOGLE_GEMINI_API_KEY=AIza...        # https://aistudio.google.com/apikey
OPENAI_API_KEY=sk-...                # https://platform.openai.com/api-keys

# ── Models (swap freely) ─────────────────
CONCLAVE_MEMBER_CLAUDE_MODEL=claude-opus-4.6
CONCLAVE_MEMBER_CLAUDE_LOCAL=true              # ← runs in Claude Code, no API call
CONCLAVE_MEMBER_GEMINI_MODEL=gemini-3.1-pro-preview
CONCLAVE_MEMBER_GPT_MODEL=gpt-5.2
```

Or use **OpenRouter** (1 key for all models):
```bash
CONCLAVE_PROVIDER_MODE=openrouter
OPENROUTER_API_KEY=sk-or-...         # https://openrouter.ai/keys
```

> **Tip:** You can also `export` the variables in your shell instead of using `.env`.
> Environment variables always override `.env` file values.

### 3. Use it

```bash
# In Claude Code:
/conclave What are the trade-offs between REST and GraphQL?

# Deep debate for critical decisions:
/conclave deep Is this database schema correct for 10M users?

# Quick sanity check:
/conclave quick What's the time complexity of quicksort?
```

### 4. Health check
```bash
python3 scripts/conclave.py doctor

🩺 Conclave Health Check

  🟣 Claude:  🏠 Local (Claude Code)
  🔵 Gemini:  ✅ 0.8s
  🟢 GPT:     ✅ 1.5s
```

## 3 Depth Levels

| Command | What happens | Time | Cost | Best for |
|---------|-------------|------|------|----------|
| `/conclave quick` | 3 parallel answers → light merge | ~10s | 1x | Facts, sanity checks |
| `/conclave` | 3 parallel answers → Claude Code synthesis | ~15s | 1x | Analysis, code review |
| `/conclave deep` | 3 answers → anonymous critique → debate synthesis | ~30s | 2x | Architecture, security |

## How Deep Mode Works

This is where it gets interesting. The models **literally talk to each other**:

**Phase 1** — All models answer independently (no one sees others)
```
Claude:  "PostgreSQL is better because of ACID transactions..."
Gemini:  "MongoDB's flexible schema is ideal for multi-tenant..."
GPT:     "Consider a hybrid approach with PostgreSQL + Redis..."
```

**Phase 2** — Each model sees the others' answers **anonymized** and critiques them
```
Claude sees:
  Response A: "MongoDB's flexible schema..." (actually Gemini)
  Response B: "Consider a hybrid approach..." (actually GPT)
  → Critique: "Response A ignores data consistency. Response B is pragmatic but..."
  → FINAL RANKING: B > A

Gemini sees:
  Response A: "PostgreSQL is better because..." (actually Claude)
  Response B: "Consider a hybrid approach..." (actually GPT)
  → Critique: "Response A is too rigid. Response B balances both..."
  → FINAL RANKING: B > A
```

**Phase 3** — Claude Code reads ALL of it and synthesizes directly (no API call)
```
Aggregate Rankings: GPT #1 (avg 1.3), Claude #2 (avg 1.7), Gemini #3 (avg 2.0)

Final Answer: "Use PostgreSQL as primary with a caching layer (Redis)..."
```

The anonymization is key — without it, models tend to agree with "famous" models.

## Configuration

Everything is in **`.env`** — no code changes needed:

```bash
# ── Swap models by editing one line ──────
CONCLAVE_MEMBER_CLAUDE_MODEL=claude-opus-4.6
CONCLAVE_MEMBER_CLAUDE_LOCAL=true              # ← no API call, runs in Claude Code
CONCLAVE_MEMBER_GEMINI_MODEL=gemini-3.1-pro-preview
CONCLAVE_MEMBER_GPT_MODEL=gpt-5.2

# ── Add a new member (just add 5 lines) ──
CONCLAVE_MEMBER_GROK_MODEL=grok-4
CONCLAVE_MEMBER_GROK_LABEL=Grok
CONCLAVE_MEMBER_GROK_ICON=⚫
CONCLAVE_MEMBER_GROK_PROVIDER=xai
CONCLAVE_MEMBER_GROK_OPENROUTER=x-ai/grok-4

# ── Chairman = Claude Code itself ─────────
# No config needed — Phase 3 synthesis runs
# directly in Claude Code, zero extra API calls

# ── Prevent favoritism in reviews ────────
CONCLAVE_ANONYMIZE=true
```

The script **auto-discovers** all members by scanning for `CONCLAVE_MEMBER_*_MODEL` variables. No registry, no list to maintain.

Custom prompts in **`prompts/templates.yaml`** (optional, requires `pyyaml`).

## Cost Estimation

Preview estimated costs **before** running any API calls:

```bash
python3 scripts/conclave.py "Explain CRDT" --depth deep --estimate

────────────────────────────────────────────────────
  Cost estimate  (depth=deep)
────────────────────────────────────────────────────
  💰 🔵 Gemini      gemini-3.1-pro-preview            P1 $0.0205  P2 $0.0256
  💰 🟢 GPT         gpt-5.2                           P1 $0.0164  P2 $0.0246
  🏠 🟣 Claude      claude-opus-4.6                   free (local)
────────────────────────────────────────────────────
  Phase 1 $0.0369 · Phase 2 $0.0502 · Total $0.0871
  Estimates assume max output tokens; actual cost is usually lower.
────────────────────────────────────────────────────
```

Combine with `--raw` for machine-readable JSON output. Local members (Claude Code) are always free.

## Real-Time Progress

During execution the council reports progress to **stderr** as each model completes, so you see activity immediately instead of waiting in silence:

```
🏛️ Conclave — standard · 3 members
  Phase 1 — Independent drafts...
    🏠 🟣 Claude — local (Claude Code)
    ✅ 🔵 Gemini — 3.2s
    ✅ 🟢 GPT — 4.1s
  Done in 4.2s
```

JSON output on stdout remains clean. Suppress with `--quiet` / `-q`.

## Multi-Turn Sessions

Continue a conversation across multiple conclave invocations. Each turn's responses are summarized and prepended as context to the next prompt:

```bash
# Start a new session
python3 scripts/conclave.py "What is the CAP theorem?" --session new --raw

# Continue the same session (models see prior context)
python3 scripts/conclave.py "How does PACELC extend it?" --session last --raw

# Continue a specific session by ID
python3 scripts/conclave.py "And what about Raft consensus?" --session 20260301-143022-abcd --raw

# List all saved sessions
python3 scripts/conclave.py sessions
```

Sessions are stored as JSON files in `~/.config/conclave/sessions/`. Each model receives the full conversation history (all models' prior answers, summarized) as context. Without `--session`, behavior is single-turn as before.

## Retry and Resilience

API calls automatically retry with **exponential backoff** on transient failures (429, 5xx, timeouts, connection errors). Configurable via `.env`:

```bash
CONCLAVE_MAX_RETRIES=3          # max retry attempts (default: 3)
CONCLAVE_RETRY_BASE_DELAY=1.0   # base delay in seconds (default: 1.0)
CONCLAVE_TIMEOUT=120            # per-request timeout in seconds (default: 120)
```

Delay formula: `base_delay * 2^attempt + random(0, 0.5)s` jitter to avoid thundering herd.

## Testing

97 tests with zero API calls (all external calls mocked):

```bash
pip install -e ".[dev]"    # one-time setup (installs pytest + httpx)
python3 -m pytest tests/ -v
```

| File | Tests | Covers |
|------|-------|--------|
| `test_ranking.py` | 62 | `parse_ranking` (numbered, arrows, comma, standalone, headers, edge cases), `extract_json_ranking`, `validate_ranking`, `parse_ranking_json`, `aggregate_rankings`, `build_critique_prompt`, `build_repair_prompt` |
| `test_providers.py` | 19 | `_post` retry logic (429/5xx, timeout, connect errors, non-retryable 4xx), `call_model` routing (local placeholder, missing keys, provider dispatch) |
| `test_orchestrator.py` | 16 | `phase1`, `phase2` (critiques, re-prompting, regex fallback, skip failed, <2 ok drafts), `run_conclave` (quick/standard/deep, member filtering, output structure, summary counts), `doctor` |

## CLI Reference

```
conclave.py <prompt> [options]
conclave.py doctor                  Health check all models
conclave.py sessions                List saved sessions

Options:
  --depth {quick,standard,deep}     Depth level (default: standard)
  --members claude,gemini           Comma-separated member keys
  --system "..."                    System prompt for all models
  --raw                             JSON-only output on stdout
  --quiet, -q                       Suppress stderr progress
  --estimate                        Estimate cost and exit
  --session {new,last,<id>}         Multi-turn conversation session
```

## Project Structure

```
conclave/
├── .env.template           ← Copy to ~/.config/conclave/.env
├── pyproject.toml          ← Package metadata, dependencies, CLI entry point
├── SKILL.md                ← Claude Code skill definition
├── LICENSE                 ← Apache 2.0
├── prompts/
│   └── templates.yaml      ← Custom critique/synthesis prompts (optional)
├── scripts/
│   ├── conclave.py         ← Slim CLI entry point (imports from package)
│   └── conclave/           ← Core package (1 dependency: httpx)
│       ├── __init__.py     ← Public API: run_conclave, load_config, doctor, estimate_cost
│       ├── config.py       ← .env loading, member discovery, templates
│       ├── providers.py    ← HTTP retry, Anthropic/Gemini/OpenAI/OpenRouter callers
│       ├── ranking.py      ← Ranking extraction, aggregation, critique prompts
│       ├── sessions.py     ← Multi-turn session store and context building
│       ├── progress.py     ← Real-time stderr progress reporting
│       ├── cost.py         ← Pricing data and cost estimation
│       ├── orchestrator.py ← Phase 1/2 orchestration, run_conclave, doctor
│       └── cli.py          ← argparse, pretty printing, main()
├── tests/
│   ├── conftest.py         ← sys.path setup for imports
│   ├── test_ranking.py     ← Ranking parser, JSON extraction, aggregation, critique prompts (62 tests)
│   ├── test_providers.py   ← HTTP retry logic, call_model routing (19 tests)
│   └── test_orchestrator.py← Phase 1/2 orchestration, run_conclave, doctor (16 tests)
└── README.md

~/.config/conclave/
├── .env                    ← API keys and model config
└── sessions/               ← Multi-turn session files (auto-created)
    └── 20260301-143022-abcd.json
```

**Only required dependency: `httpx`.** The `pyyaml` package is optional (only for custom prompt templates).

## FAQ

**Q: How is this different from just asking Claude?**
A: One model has blind spots. Three models debating catches errors, surfaces alternative approaches, and the anonymous ranking reveals which answer the *crowd* thinks is best — often different from what any single model would produce.

**Q: Does it cost 3x more?**
A: `quick` and `standard` modes cost the same as 3 individual API calls (they run in parallel). `deep` mode costs ~2x (two rounds of calls). Use `--estimate` to preview costs before running. Local members (Claude Code) are free.

**Q: Can I add Grok, Llama, Mistral...?**
A: Yes. Add 5 lines to your `.env` file. With OpenRouter, you get access to 200+ models with 1 API key.

**Q: Can I have a multi-turn debate?**
A: Yes. Use `--session new` on the first turn, then `--session last` for follow-ups. Each model sees a summary of all prior turns as context.

**Q: What happens if an API call fails?**
A: The script retries automatically with exponential backoff (configurable). If all retries fail, the member is marked as failed and the council continues without it.

**Q: Why "Conclave"?**
A: From Latin *con-clavis* ("locked with a key") — the secret meeting where cardinals debate behind closed doors to reach a final decision. That's exactly what the models do: deliberate in private, then announce a verdict.

## Contributing

PRs welcome! Ideas:
- [x] Retry with exponential backoff for API calls
- [x] Real-time progress reporting (stderr)
- [x] Cost estimation per query (`--estimate`)
- [x] Robust ranking parser (regex + structured prompts)
- [x] Multi-turn conversation memory (`--session`)
- [x] Modular package architecture (config, providers, ranking, sessions, cost, orchestrator, cli)
- [x] Test suite — ranking parser, retry logic, phase orchestration (97 tests, pytest)
- [x] `pyproject.toml` — installable package with `pip install`, CLI entry point, optional deps
- [x] HTTP connection pooling — shared `httpx.AsyncClient` across all API calls in a session
- [ ] Web UI for visualizing debates
- [ ] Export debate transcripts to Markdown
- [ ] Token budget management (auto-truncate long sessions)

## Acknowledgments

- [Giovanni Tommasini](https://giovannitommasini.it) — project creator and architect
- [Andrej Karpathy](https://github.com/karpathy/llm-council) — for the LLM Council pattern
- [sherifkozman/the-llm-council](https://github.com/sherifkozman/the-llm-council) — for the adversarial debate architecture
- [OpenRouter](https://openrouter.ai) — for making multi-model access simple

## License

Apache 2.0 — use it, modify it, distribute it. See [LICENSE](LICENSE) for details.

---

<p align="center">
  <em>When one model isn't enough, convene the conclave.</em>
</p>
