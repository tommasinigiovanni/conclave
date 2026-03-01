---
name: conclave
description: "Conclave — Multi-LLM Council with anonymized debate. Orchestrates multiple AI models (Claude, Gemini, GPT, Grok, Llama, etc.) in a Karpathy-style council with 3 depth levels: quick (parallel answers), standard (parallel + synthesis), deep (parallel + anonymized cross-critique with ranking + debate synthesis). Inspired by Karpathy's LLM Council. Use this skill whenever the user types /conclave, asks to 'consult multiple models', 'get council opinion', 'multi-model debate', 'ask the conclave', 'cross-validate with other AIs', or wants multiple LLMs to debate and synthesize an answer. Also trigger for architecture decisions, security reviews, code reviews from multiple perspectives, or when the user wants high-confidence answers by cross-referencing models."
---

# Conclave: Multi-LLM Council with Anonymized Debate

## What It Does

Sends the user's prompt to multiple LLMs in parallel, optionally makes them
**anonymously critique and rank each other's responses**, then synthesizes
everything into a single superior answer.

Claude is both a **council member** and the **synthesizer** — but it runs
locally in Claude Code (no API call), saving cost and latency.

Inspired by [Karpathy's LLM Council](https://github.com/karpathy/llm-council).

## Key Features

- **Local Claude** — Claude participates as a council member without an API call (runs in Claude Code)
- **Anonymized reviews** — in Phase 2, responses are labeled "Response A", "Response B" etc. so models can't play favorites
- **Aggregate ranking** — each model ranks the others; scores are averaged to find the crowd's best answer
- **Configurable** — models, providers, and API keys are in `.env.template`; prompts in `prompts/templates.yaml`
- **OpenRouter support** — use 1 API key for all models, or direct keys per provider
- **Graceful degradation** — if a model fails, the council continues with the rest

## Architecture

```
Phase 1: Independent Drafts (all modes)
  Script calls → [Gemini API] [GPT API] → responses in JSON
  Claude Code  → generates its own draft directly (no API)

Phase 2: Anonymized Cross-Critique (deep mode only)
  Script calls → each remote model critiques others as "Response A/B/C"
  Claude Code  → critiques the others' responses directly (no API)

Phase 3: Synthesis (standard + deep)
  Claude Code reads all drafts (+ critiques + rankings in deep)
  and synthesizes the final answer
```

## How Claude Code Should Use This Skill

### Step 1: Run the script
```bash
python3 scripts/conclave.py "<user_prompt>" --depth <level> --raw
```

### Step 2: Parse the JSON output
The JSON contains `phase1_drafts` (and `phase2_critiques` in deep mode).
Entries with `"needs_claude_code": true` are **placeholders** that YOU must fill.

### Step 3: Fill local member placeholders

**Phase 1 (all modes):** Find drafts where `needs_claude_code` is true.
Generate YOUR OWN independent answer to the original prompt.
Important: answer as if you haven't seen the other models' responses yet —
this preserves the independence of the council.

**Phase 2 (deep mode only):** Find critiques where `needs_claude_code` is true.
The critique entry includes a `prompt` field with the anonymized responses.
Read it and provide your critique + ranking, treating them as "Response A/B/C"
without knowing which model wrote which. End with:
```
FINAL RANKING:
1. Response [best]
2. Response [second]
3. Response [third]
```

### Step 4: Synthesize

**Quick mode:** Present all drafts (including yours) side by side. No synthesis needed.

**Standard mode:** Read all Phase 1 drafts and synthesize:
```
## 🏛️ Conclave Response
### Consensus · Key Insights · Disagreements · Final Answer
```

**Deep mode:** Read all Phase 1 drafts + Phase 2 critiques + aggregate rankings:
```
## 🔥 Conclave Deep Debate
### The Debate · Post-Debate Consensus · Resolved Disagreements
### Aggregate Rankings · Open Questions · Final Answer
```

## Depth Levels

| Command | Phases | API calls | Best for |
|---------|--------|-----------|----------|
| `/conclave quick ...` | 1 | remote models only | Factual questions, sanity checks |
| `/conclave ...` | 1 + 3 | remote models only | Analysis, code review, recommendations |
| `/conclave deep ...` | 1 + 2 + 3 | remote models × 2 | Architecture, security, critical decisions |

## Running

```bash
python3 scripts/conclave.py "<prompt>" --depth standard --raw
python3 scripts/conclave.py "<prompt>" --depth deep --raw
python3 scripts/conclave.py doctor   # health check
```

Flags: `--depth`, `--members`, `--system`, `--raw`

## Configuration

Edit `.env` (copied from `.env.template`) to:
- Switch between OpenRouter (1 key) and direct API keys
- Add/remove/swap council members
- Mark any member as `LOCAL=true` to skip API calls
- Adjust temperature, max_tokens, timeout

Edit `prompts/templates.yaml` to customize critique and synthesis prompts (optional, requires pyyaml).
