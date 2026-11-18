"""
config.py - Configuration and Design Defaults

WHY THIS FILE EXISTS:
Centralizes model API configuration and organizer design policies in one place.
Separates operational defaults (like buffer times or timeout limits) from pack data.

HARD RULE R1:
Never place pack facts, numbers, dates, or vendor names here.
Only organizer design defaults are allowed.
"""

import os
from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent
STATE_FILE = PROJECT_ROOT / "state.json"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_PLAN_FILE = OUTPUT_DIR / "plan.json"
OUTPUT_TRACE_FILE = OUTPUT_DIR / "trace.txt"
OUTPUT_REPORT_FILE = OUTPUT_DIR / "final_report.md"

# Simple .env loader (avoids strict dependency on python-dotenv if not installed)
def load_env_file(filepath: Path = None):
    """Loads key-value pairs from .env into os.environ if present."""
    if filepath is None:
        filepath = PROJECT_ROOT / ".env"
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k not in os.environ:
                    os.environ[k] = v

load_env_file()

# ==============================================================================
# MODEL SETTINGS (Loaded from .env, works with Groq, OpenRouter, or Ollama)
# ==============================================================================
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")

# ==============================================================================
# TIME SAFETY & LIMITS (Rules R6, R7, and Section 13)
# ==============================================================================
TIMEOUT_SECONDS = 25              # Per-model-call network timeout (seconds)
FULL_RUN_TIMEOUT_SECONDS = 110    # Hard limit for full run (target < 100s)
UPDATE_TIMEOUT_SECONDS = 55       # Hard limit for update run (target < 50s)
MAX_UPDATE_MODEL_CALLS = 5        # Hard limit on model calls during an update (R7)

# ==============================================================================
# DESIGN DEFAULTS (ORGANIZER POLICY ONLY - NEVER PACK FACTS)
# These represent organizer standard procedures when pack does not specify.
# ==============================================================================
DESIGN_DEFAULT_OPENING_MINUTES = 30       # Welcome, rules, keynote
DESIGN_DEFAULT_CLOSING_MINUTES = 30       # Results announcement, wrap-up
DESIGN_DEFAULT_BUFFER_MINUTES = 15        # Buffer before judging to absorb delays (e.g. late judge)
DESIGN_DEFAULT_LUNCH_MINUTES = 30         # Standard lunch break block
DESIGN_DEFAULT_MINUTES_PER_TEAM = 10      # Standard pitch + Q&A per team
DESIGN_DEFAULT_MAX_TEAMS_PER_JUDGE = 4    # Default judge workload limit
DESIGN_DEFAULT_TEAM_SIZE = 4              # Standard hackathon team size
DESIGN_DEFAULT_STAFF_COUNT = 5            # Fallback staff count if omitted
DESIGN_DEFAULT_JUDGE_FEE = 0              # Default judge honorarium if not specified
