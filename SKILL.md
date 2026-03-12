---
name: conclave
description: "Conclave — Multi-LLM Council with anonymized debate. Orchestrates multiple AI models (Claude, Gemini, GPT, Grok, Llama, etc.) in a Karpathy-style council with 3 depth levels: quick (parallel answers), standard (parallel + synthesis), deep (parallel + anonymized cross-critique with ranking + debate synthesis). Inspired by Karpathy's LLM Council. Use this skill whenever the user types /conclave, asks to 'consult multiple models', 'get council opinion', 'multi-model debate', 'ask the conclave', 'cross-validate with other AIs', or wants multiple LLMs to debate and synthesize an answer. Also trigger for architecture decisions, security reviews, code reviews from multiple perspectives, or when the user wants high-confidence answers by cross-referencing models."
---

# Conclave: Multi-LLM Council with Anonymized Debate

## CRITICAL: Always Run the Script

**DO NOT check or read `.env` or `.env.template` files.** The script handles
its own configuration automatically. API keys and model settings are already
configured in the user's `.env` file, which the script finds on its own.

**ALWAYS run the script first**, then work with the JSON output.

## Quick Reference

```bash
# SKILL_DIR = directory containing this SKILL.md file
SKILL_DIR="$(dirname "$(realpath "$0")")"  # or use the skill's known path

# Determine depth from user intent:
#   "quick" / "fast"           → --depth quick
#   default / no modifier      → --depth standard
#   "deep" / "debate" / "critical" → --depth deep

python3 "${SKILL_DIR}/scripts/conclave.py" "<USER_PROMPT>" --depth <LEVEL> --raw

# Voting mode (point-based instead of ordinal ranking):
python3 "${SKILL_DIR}/scripts/conclave.py" "<USER_PROMPT>" --vote --raw

# Multi-round dialogue:
python3 "${SKILL_DIR}/scripts/conclave.py" "<USER_PROMPT>" --rounds 3 --raw

# Combined voting + dialogue:
python3 "${SKILL_DIR}/scripts/conclave.py" "<USER_PROMPT>" --vote --rounds 2 --raw

# Bias report:
python3 "${SKILL_DIR}/scripts/conclave.py" bias
```

The `--raw` flag outputs JSON. **Always use `--raw`.**

## Step-by-Step Flow

### Step 1: Run the script

Run `python3 <skill_dir>/scripts/conclave.py "<prompt>" --depth <level> --raw`

The script will:
- Load its own config (`.env` file next to the script — DO NOT manage this yourself)
- Call remote APIs (Gemini, GPT, etc.) in parallel
- Return JSON with results and placeholders for you (Claude)

### Step 2: Parse JSON, find your placeholders

The JSON `phase1_drafts` array contains one entry per council member.
Entries with `"needs_claude_code": true` are YOUR drafts to fill.

Example JSON structure:
```json
{
  "phase1_drafts": [
    {"key": "claude", "needs_claude_code": true, "prompt": "..."},
    {"key": "gemini", "content": "Gemini's response...", "elapsed": 3.2},
    {"key": "gpt", "content": "GPT's response...", "elapsed": 2.8}
  ]
}
```

### Step 3: Generate your independent draft

For each `needs_claude_code: true` entry in `phase1_drafts`:

**Write your OWN answer to the original prompt BEFORE reading the other models'
responses.** This preserves the independence of the council. Pretend you haven't
seen Gemini's or GPT's answers yet.

### Step 3b: (Deep mode only) Complete Phase 2 if pending

If the JSON has `"phase2_pending": true`:

1. Update the Phase 1 JSON: set your draft's `content` to your response from Step 3
2. Write the updated JSON to a temp file (e.g., `/tmp/conclave_p1.json`)
3. Run `python3 "${SKILL_DIR}/scripts/conclave.py" phase2 /tmp/conclave_p1.json --raw`
4. Parse the Phase 2 JSON — it now has `phase2_critiques` and `aggregate_rankings`

If `phase2_pending` is false or absent, skip this step.

### Step 4: (Deep mode only) Generate your critique

In deep mode, `phase2_critiques` will also have `needs_claude_code: true` entries.
Each includes a `prompt` field with anonymized responses ("Response A", "Response B").

Read them and provide your critique + ranking. End with:
```json
{"ranking": ["A", "B", "C"]}
```
Use only the single response letters, best first.

### Step 5: Synthesize the final answer

**Quick mode:** Present all drafts (including yours) side by side. Done.

**Standard mode:** Synthesize all Phase 1 drafts:
```
## 🏛️ Conclave Response

### Consensus
[Points where all models agree — high confidence]

### Key Insights
[Unique valuable contributions from individual models]

### Disagreements
[Where models diverged, and which position is stronger]

### Final Answer
[The best unified answer]
```

**Deep mode:** Synthesize Phase 1 drafts + Phase 2 critiques + aggregate rankings:
```
## 🔥 Conclave Deep Debate

### The Debate
[Summary of challenges and concessions]

### Post-Debate Consensus
[Points that survived adversarial critique — very high confidence]

### Resolved Disagreements
[Issues the debate clarified]

### Aggregate Rankings
[Show the rankings from the JSON]

### Open Questions
[Legitimate remaining disagreements]

### Final Answer
[The best unified answer, informed by the full debate]
```

**Vote mode:** Synthesize Phase 1 drafts + voting results:
```
## 🗳️ Conclave Quorum Vote

### Weighted Scores
[Points each model received from peers]

### Consensus Strength
[How strongly models agreed on the winner (0-100%)]

### Key Insights
[What the top-scored model got right]

### Disagreements
[Where voters diverged]

### Final Answer
[The best answer, informed by the quorum vote]
```

**Dialogue mode:** Synthesize across rounds:
```
## 💬 Conclave Dialogue (N rounds)

### Evolution
[How positions changed across rounds]

### Convergence
[Points where models converged, and in which round]

### Remaining Disagreements
[Issues that persisted through all rounds]

### Final Answer
[The best answer after multi-round refinement]
```

## Depth Levels

| Trigger | Depth | Phases | Best for |
|---------|-------|--------|----------|
| `/conclave quick ...` | quick | 1 | Factual questions, sanity checks |
| `/conclave ...` | standard | 1 + 3 | Analysis, code review, recommendations |
| `/conclave deep ...` | deep | 1 + 2 + 3 | Architecture, security, critical decisions |
| `/conclave vote ...` | vote | 1 + vote | Comparative evaluation, ranking alternatives |
| `/conclave ... --rounds N` | any + dialogue | 1 + 2 + dialogue | Iterative refinement, consensus building |

## CLI Commands

```bash
# Core modes
conclave.py "<prompt>" --depth quick|standard|deep  # Standard depth levels
conclave.py "<prompt>" --vote                        # Quorum voting mode
conclave.py "<prompt>" --rounds N                    # Multi-round dialogue
conclave.py "<prompt>" --vote --rounds N             # Combined vote + dialogue

# Utilities
conclave.py doctor                   # Health check all models
conclave.py leaderboard              # EMA-based model scores
conclave.py sessions                 # List saved sessions
conclave.py bias                     # Bias & impartiality report
conclave.py phase2 <file> --raw      # Run Phase 2 from saved Phase 1

# Options
--raw           JSON output only
--quiet / -q    Suppress stderr progress
--estimate      Cost estimate (supports --vote, --rounds)
--members k1,k2 Filter council members
--session ID    Multi-turn session (new/last/<id>)
--system "..."  System prompt for all models
```

## Environment Variables (.env)

```bash
# Provider keys
ANTHROPIC_API_KEY=...
GOOGLE_GEMINI_API_KEY=...
OPENAI_API_KEY=...
XAI_API_KEY=...
OPENROUTER_API_KEY=...

# Model configuration (per member)
CONCLAVE_MEMBER_<KEY>_MODEL=...
CONCLAVE_MEMBER_<KEY>_PROVIDER=...
CONCLAVE_MEMBER_<KEY>_LABEL=...
CONCLAVE_MEMBER_<KEY>_ICON=...
CONCLAVE_MEMBER_<KEY>_LOCAL=true|false
CONCLAVE_MEMBER_<KEY>_FALLBACK_MODEL=...

# Defaults
CONCLAVE_TEMPERATURE=0.7
CONCLAVE_MAX_TOKENS=2048
CONCLAVE_TIMEOUT=120
CONCLAVE_MAX_RETRIES=3
CONCLAVE_PROVIDER_MODE=direct|openrouter
CONCLAVE_ANONYMIZE=true
CONCLAVE_SCORING_EMA_ALPHA=0.3
CONCLAVE_SESSION_TOKEN_BUDGET=20000

# Dialogue settings
CONCLAVE_MAX_ROUNDS=3              # Hard cap for --rounds
CONCLAVE_CONVERGENCE_THRESHOLD=0.85 # Early termination threshold

# Bias tracking
CONCLAVE_BIAS_TRACKING=true|false  # Enable/disable bias data collection
```

## Project Structure

```
scripts/conclave/
├── __init__.py          # Public API exports
├── cli.py               # CLI entry point (argparse, pretty printing)
├── config.py            # .env loading, member discovery
├── cost.py              # Cost estimation (supports vote/rounds)
├── orchestrator.py      # Main run_conclave, phases, voting, dialogue integration
├── providers.py         # HTTP callers (Anthropic, Google, OpenAI, xAI, OpenRouter)
├── progress.py          # Real-time stderr progress
├── ranking.py           # Ranking extraction (JSON + regex), aggregation
├── scoring.py           # EMA-based model scoring, leaderboard
├── sessions.py          # Multi-turn session persistence
├── voting.py            # Quorum voting (point distribution, aggregation)
├── dialogue.py          # Multi-round dialogue (convergence detection)
└── bias.py              # Bias tracking & impartiality metrics
tests/
├── conftest.py
├── test_orchestrator.py
├── test_providers.py
├── test_ranking.py
├── test_scoring.py
├── test_sessions.py
├── test_voting.py
├── test_dialogue.py
└── test_bias.py
```

## Troubleshooting

- **Script not found?** The script is at `<this_skill_dir>/scripts/conclave.py`
- **API errors?** Run `python3 <skill_dir>/scripts/conclave.py doctor` to check
- **All failed?** You (Claude) are still available as LOCAL member — provide your answer solo with a note that remote models were unavailable

## Security Note

API keys are stored in `~/.config/conclave/.env` — **never** in the skill
directory. The script loads them automatically from there. This prevents
LLM agents from accidentally reading secrets when scanning skill files.
