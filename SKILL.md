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

## Depth Levels

| Trigger | Depth | Phases | Best for |
|---------|-------|--------|----------|
| `/conclave quick ...` | quick | 1 | Factual questions, sanity checks |
| `/conclave ...` | standard | 1 + 3 | Analysis, code review, recommendations |
| `/conclave deep ...` | deep | 1 + 2 + 3 | Architecture, security, critical decisions |

## Troubleshooting

- **Script not found?** The script is at `<this_skill_dir>/scripts/conclave.py`
- **API errors?** Run `python3 <skill_dir>/scripts/conclave.py doctor` to check
- **All failed?** You (Claude) are still available as LOCAL member — provide your answer solo with a note that remote models were unavailable

## Security Note

API keys are stored in `~/.config/conclave/.env` — **never** in the skill
directory. The script loads them automatically from there. This prevents
LLM agents from accidentally reading secrets when scanning skill files.
