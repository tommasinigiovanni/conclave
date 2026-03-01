#!/usr/bin/env python3
"""
Conclave — Multi-LLM Council with anonymized debate.

Inspired by Karpathy's LLM Council pattern. Features:
  - 3 depth levels: quick / standard / deep
  - Anonymized cross-critique (Phase 2) to prevent favoritism
  - Aggregate ranking across all peer reviews
  - Configurable via .env file (models, keys, settings)
  - Supports OpenRouter (1 key) or direct API keys
  - Graceful degradation when models fail
"""

from conclave.cli import main

if __name__ == "__main__":
    main()
