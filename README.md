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
| **Quorum voting** | ✅ `--vote` (100-point distribution) | ❌ | ❌ |
| **Multi-round dialogue** | ✅ `--rounds N` (convergence detection) | ❌ | ❌ |
| **Fallacy detection** | ✅ `--fallacies` (12 logical fallacies) | ❌ | ❌ |
| **Bias tracking** | ✅ `bias` command | ❌ | ❌ |
| **Scoring & leaderboard** | ✅ EMA-based | ❌ | ❌ |
| **Multi-turn sessions** | ✅ `--session` | ❌ | ❌ |
| **Cost estimation** | ✅ `--estimate` | ❌ | ❌ |
| **Real-time streaming** | ✅ SSE token streaming (parallel + sequential) | ❌ | ❌ |
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

# Quorum voting — models score each other with points:
/conclave vote Which caching strategy is best for this use case?

# Multi-round dialogue — models refine answers iteratively:
/conclave --rounds 3 Should we use microservices or a monolith?

# Combined voting + dialogue:
/conclave vote --rounds 2 Compare Kafka vs RabbitMQ for our workload

# Fallacy detection — spot logical errors in model responses:
/conclave --fallacies deep Is NoSQL always better for scalability?
```

### 4. Health check
```bash
python3 scripts/conclave.py doctor

🩺 Conclave Health Check

  🟣 Claude:  🏠 Local (Claude Code)
  🔵 Gemini:  ✅ 0.8s
  🟢 GPT:     ✅ 1.5s
```

## 5 Modes

| Command | What happens | Time | Cost | Best for |
|---------|-------------|------|------|----------|
| `/conclave quick` | 3 parallel answers → light merge | ~10s | 1x | Facts, sanity checks |
| `/conclave` | 3 parallel answers → Claude Code synthesis | ~15s | 1x | Analysis, code review |
| `/conclave deep` | 3 answers → anonymous critique → debate synthesis | ~30s | 2x | Architecture, security |
| `/conclave vote` | 3 answers → point-based voting → weighted synthesis | ~30s | 2x | Comparative evaluation |
| `/conclave --rounds 3` | 3 answers → critique → 2 refinement rounds | ~45s | 3x | Consensus building |

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

## How Voting Mode Works

Instead of ordinal ranking (1st, 2nd, 3rd), each model distributes **exactly 100 points** among the others' responses. Models **cannot vote for themselves** — responses are anonymized.

```bash
/conclave vote Which caching strategy is best for this use case?
```

```
Phase 1 — Independent answers (same as standard)

Phase 2 — Quorum voting:
  Gemini:  Claude 60pts, GPT 40pts
  GPT:     Claude 55pts, Gemini 45pts
  Claude:  GPT 50pts, Gemini 50pts

Weighted Scores: Claude 115pts, GPT 90pts, Gemini 95pts
Consensus Strength: 57.5% (moderate agreement)
```

This gives finer-grained signal than ordinal ranking — you can distinguish "slight preference" from "strong preference".

## How Multi-Round Dialogue Works

After Phase 1 + Phase 2, models enter additional rounds where they see the critiques they received and can **revise, defend, or converge**:

```bash
/conclave --rounds 3 Should we use microservices or a monolith?
```

```
Round 1 — Independent answers (Phase 1)
Round 2 — Each model sees critiques, responds with:
  CONVERGE: "I agree, the monolith-first approach is better"
  MAINTAIN: "I stand by microservices, here's why..."
  UPDATE:   "I partially agree — start monolith, split later"
Round 3 — Another iteration (or early termination if all converge)
```

**Early termination**: If all models start with `CONVERGE:` in the same round, the dialogue stops early.

Combine with voting: `--vote --rounds 2` runs voting first, then a dialogue round.

Config in `.env`:
```bash
CONCLAVE_MAX_ROUNDS=3              # Hard cap (default: 3)
CONCLAVE_CONVERGENCE_THRESHOLD=0.85 # For early termination
```

## Bias & Impartiality Tracking

Track how models vote across runs to detect systematic biases:

```bash
python3 scripts/conclave.py bias

═══════════════════════════════════════════════════════
  📊 CONCLAVE — Bias & Impartiality Report
═══════════════════════════════════════════════════════
  Total runs tracked: 15

  Per-Model Statistics
  gemini        avg given: 50.0  avg received: 48.3
  gpt           avg given: 50.0  avg received: 51.7
  claude        avg given: 50.0  avg received: 55.2

  Consensus by Mode
  vote          avg consensus: 0.620
  dialogue      avg consensus: 0.750

  Most Contested Run
  Topic:     Compare microservices vs monolith for...
  Consensus: 0.340
```

Data is stored in `~/.config/conclave/bias.json` and updated automatically after every `--vote` or `--rounds` run. Disable with:

```bash
CONCLAVE_BIAS_TRACKING=false
```

## Fallacy Detection

An optional layer that analyzes each model's response for **logical fallacies** before Phase 2. This is a unique differentiator — no other multi-LLM framework does this.

```bash
# Enable via CLI flag:
/conclave --fallacies deep Is NoSQL always better for scalability?

# Or enable permanently in .env:
CONCLAVE_FALLACY_DETECTION=true
```

When enabled, after Phase 1 an analyzer model scans each response for 12 types of logical fallacies (ad hominem, straw man, false dichotomy, appeal to authority, slippery slope, circular reasoning, hasty generalization, appeal to emotion, false equivalence, post hoc, bandwagon, appeal to ignorance).

```
─── LOGICAL ANALYSIS ───

  🔵 Gemini — 1 fallacy detected
    [MEDIUM] False Dichotomy
      Quote: "either we use PostgreSQL or we accept chaos"
      -> Ignores many valid alternatives like MySQL, SQLite, etc.

  🟢 GPT — no fallacies detected
  🟣 Claude — no fallacies detected
```

If a **local member** (Claude Code) is available, it's used as the analyzer — **zero extra API cost**. Otherwise, the first available model is used (~500 input + ~200 output tokens per member).

Default: **off** (`CONCLAVE_FALLACY_DETECTION=false`). Enable with `--fallacies` / `-f` or set the env var to `true`.

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

Supports `--vote` and `--rounds` for accurate estimates:
```bash
python3 scripts/conclave.py "Compare approaches" --vote --estimate
python3 scripts/conclave.py "Deep debate" --rounds 3 --estimate
```

## Real-Time Streaming

Phase 1 responses are **streamed in real time** via SSE (Server-Sent Events) — you see tokens as they arrive from each provider instead of waiting for the full response.

Two modes are available:

**Parallel mode** (default) — all models stream simultaneously, results displayed as each finishes:
```
🏛️ Conclave — standard · 3 members
  Phase 1 — Independent drafts (streaming)...
    🏠 🟣 Claude — local (Claude Code)
    ✅ 🔵 Gemini — 3.2s — "PostgreSQL is better because of ACID tr..."
    ✅ 🟢 GPT — 4.1s — "Consider a hybrid approach with PostgreS..."
  Done in 4.2s
```

**Sequential mode** — one model at a time with live token display:
```
🏛️ Conclave — standard · 3 members
  Phase 1 — Independent drafts (streaming sequential)...
    🏠 🟣 Claude — local (Claude Code)
    ⟳ 🔵 Gemini — streaming...
      PostgreSQL is better because of ACID transactions and...
    ✅ 🔵 Gemini — 3.2s
    ⟳ 🟢 GPT — streaming...
      Consider a hybrid approach with PostgreSQL as your...
    ✅ 🟢 GPT — 4.1s
  Done in 7.3s
```

Configure in `.env`:
```bash
CONCLAVE_STREAM=true              # Enable streaming (default: true)
CONCLAVE_STREAM_SEQUENTIAL=false  # Sequential mode (default: false)
```

Set `CONCLAVE_STREAM=false` to disable streaming entirely and use the standard request/response flow. JSON output on stdout remains clean in all modes. Suppress stderr with `--quiet` / `-q`.

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

Long sessions are automatically truncated: when prior turns exceed the token budget, the oldest turns are dropped (most recent kept). Configure via `.env`:

```bash
CONCLAVE_SESSION_TOKEN_BUDGET=20000  # max tokens for session context (default: 20000)
```

## Retry and Resilience

API calls automatically retry with **exponential backoff** on transient failures (429, 5xx, timeouts, connection errors). Configurable via `.env`:

```bash
CONCLAVE_MAX_RETRIES=3          # max retry attempts (default: 3)
CONCLAVE_RETRY_BASE_DELAY=1.0   # base delay in seconds (default: 1.0)
CONCLAVE_TIMEOUT=120            # per-request timeout in seconds (default: 120)
```

Delay formula: `base_delay * 2^attempt + random(0, 0.5)s` jitter to avoid thundering herd.

## Testing

268 tests with zero API calls (all external calls mocked):

```bash
pip install -e ".[dev]"    # one-time setup (installs pytest + httpx)
python3 -m pytest tests/ -v
```

| File | Tests | Covers |
|------|-------|--------|
| `test_ranking.py` | 62 | `parse_ranking` (numbered, arrows, comma, standalone, headers, edge cases), `extract_json_ranking`, `validate_ranking`, `parse_ranking_json`, `aggregate_rankings`, `build_critique_prompt`, `build_repair_prompt` |
| `test_providers.py` | 25 | `_post` retry logic (429/5xx, timeout, connect errors, non-retryable 4xx), `call_model` routing (local placeholder, missing keys, provider dispatch), null content handling (OpenAI/OpenRouter/Anthropic/Gemini) |
| `test_orchestrator.py` | 23 | `phase1`, `phase2` (critiques, re-prompting, regex fallback, skip failed, <2 ok drafts), `run_conclave` (quick/standard/deep, member filtering, output structure, summary counts), `doctor`, two-pass flow (`phase2_pending` deferral, `run_phase2_only`) |
| `test_scoring.py` | ~35 | `_ema`, `record_round` (participations, errors, latency EMA, rank EMA, immutability), `get_weights` (floor, normalization, unranked), `get_leaderboard` (sorting, ranked vs unranked), file I/O (roundtrip, corrupt, missing, wrong version), `print_leaderboard` |
| `test_sessions.py` | 14 | `_format_turn`, `_build_context_prompt` (basic, token budget truncation, preserves recent turns), `_record_turn` (append, summarize, error/local drafts) |
| `test_voting.py` | 16 | `parse_vote_response` (clean/fenced/bare JSON, invalid, missing letters, normalization, floats), `aggregate_votes` (basic, errors, consensus strength, 3 voters), `build_vote_prompt`, `votes_to_ranking_fallback` |
| `test_dialogue.py` | 16 | `detect_stance` (converge/maintain/update/unknown), `build_round_prompt`, `check_convergence`, `extract_critiques_for_model`, `run_dialogue_rounds` (correct rounds, early termination, mid-round failure, max cap, vote combo), `get_max_rounds` |
| `test_bias.py` | 14 | `load_bias_data` (missing/valid/corrupt), `save_bias_data`, `record_vote_run` (append, tracking disabled), `is_tracking_enabled`, `compute_metrics` (empty, single run, most contested, multi-mode, per-model stats) |
| `test_streaming.py` | 21 | SSE line parsing, Anthropic/OpenAI/Gemini stream parsing, `stream_model` routing, progress streaming display, orchestrator integration (stream=false fallback, sequential, parallel, local members) |
| `test_fallacies.py` | 24 | JSON parsing (1/2/0 fallacies, fenced, bare), type/severity filtering, graceful degradation (malformed JSON, API error, empty content), quote truncation, parallel detection, analyzer selection, orchestrator integration (enabled/disabled), CLI flag override, cost estimation |

## CLI Reference

```
conclave.py <prompt> [options]
conclave.py phase2 <file> [--raw]   Run Phase 2 from completed Phase 1 JSON
conclave.py doctor                  Health check all models
conclave.py sessions                List saved sessions
conclave.py leaderboard             Show model scoring leaderboard
conclave.py bias                    Bias & impartiality report

Options:
  --depth {quick,standard,deep}     Depth level (default: standard)
  --vote                            Quorum voting (100-point distribution)
  --rounds N                        Multi-round dialogue (2-3 rounds typical)
  --fallacies, -f                   Detect logical fallacies in responses
  --members claude,gemini           Comma-separated member keys
  --system "..."                    System prompt for all models
  --raw                             JSON-only output on stdout
  --quiet, -q                       Suppress stderr progress
  --estimate                        Estimate cost (supports --vote, --rounds)
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
│       ├── __init__.py     ← Public API: run_conclave, load_config, doctor, estimate_cost, scoring, voting, dialogue, bias
│       ├── config.py       ← .env loading, member discovery, templates
│       ├── providers.py    ← HTTP retry, Anthropic/Gemini/OpenAI/OpenRouter callers + SSE streaming
│       ├── ranking.py      ← Ranking extraction, aggregation, critique prompts
│       ├── voting.py       ← Quorum voting (point distribution, aggregation)
│       ├── dialogue.py     ← Multi-round dialogue (convergence detection)
│       ├── fallacies.py    ← Logical fallacy detection (12 types, JSON parsing)
│       ├── bias.py         ← Bias tracking & impartiality metrics
│       ├── sessions.py     ← Multi-turn session store and context building
│       ├── progress.py     ← Real-time stderr progress reporting + streaming display
│       ├── scoring.py      ← EMA-based model scoring, weights, and leaderboard
│       ├── cost.py         ← Pricing data and cost estimation (supports --vote, --rounds)
│       ├── orchestrator.py ← Phase 1/2 orchestration, voting, dialogue, streaming dispatch, run_conclave, doctor
│       └── cli.py          ← argparse, pretty printing, main()
├── tests/
│   ├── conftest.py         ← sys.path setup for imports
│   ├── test_ranking.py     ← Ranking parser, JSON extraction, aggregation, critique prompts (62 tests)
│   ├── test_providers.py   ← HTTP retry logic, call_model routing, null content (25 tests)
│   ├── test_scoring.py     ← EMA, record_round, weights, leaderboard, file I/O (~35 tests)
│   ├── test_sessions.py    ← Context building, token budget truncation (14 tests)
│   ├── test_orchestrator.py← Phase 1/2 orchestration, run_conclave, doctor, two-pass flow (23 tests)
│   ├── test_voting.py      ← Vote parsing, aggregation, consensus strength (16 tests)
│   ├── test_dialogue.py    ← Stance detection, rounds, convergence, max cap (16 tests)
│   ├── test_bias.py        ← Bias data I/O, metrics computation, tracking toggle (14 tests)
│   ├── test_streaming.py   ← SSE parsing, stream routing, progress display, orchestrator integration (21 tests)
│   └── test_fallacies.py   ← Fallacy parsing, filtering, graceful degradation, integration (24 tests)
└── README.md

~/.config/conclave/
├── .env                    ← API keys and model config
├── scores.json             ← Model scoring data (auto-created)
├── bias.json               ← Voting bias tracking data (auto-created)
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

**Q: What's the difference between `--vote` and `deep`?**
A: `deep` uses ordinal ranking (1st, 2nd, 3rd). `--vote` uses point distribution (60/40, 55/45...) which gives finer-grained signal about how much one response is preferred over another.

**Q: Can I combine modes?**
A: Yes. `--vote --rounds 2` runs voting first, then a dialogue round. `--session` works with all modes.

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
- [x] Model scoring — EMA-based performance tracking, weights, and leaderboard (`leaderboard` command)
- [x] Quorum voting — point-based voting with consensus strength (`--vote`)
- [x] Multi-round dialogue — iterative refinement with convergence detection (`--rounds N`)
- [x] Bias tracking — per-model voting patterns and impartiality metrics (`bias` command)
- [x] Real-time streaming — SSE token streaming for all providers, parallel + sequential modes
- [x] Fallacy detection — logical fallacy analysis with 12 types, free with local analyzer (`--fallacies`)
- [x] Test suite — ranking, retry, orchestration, sessions, scoring, voting, dialogue, bias, streaming, fallacies (268 tests, pytest)
- [x] `pyproject.toml` — installable package with `pip install`, CLI entry point, optional deps
- [x] HTTP connection pooling — shared `httpx.AsyncClient` across all API calls in a session
- [x] Null content handling — safe extraction when APIs return `content: null` (reasoning models)
- [ ] Web UI for visualizing debates
- [ ] Export debate transcripts to Markdown
- [x] Token budget management (auto-truncate long sessions)

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
