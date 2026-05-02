"""Configuration — all paths configurable via environment variables."""

import os
from pathlib import Path

# Lifelog data
LIFELOG_SCREEN_DIR = Path(os.environ.get(
    "DAILY_REFLECT_SCREEN_DIR",
    str(Path.home() / "lifelog" / "data" / "screen"),
))
LIFELOG_DB = Path(os.environ.get(
    "DAILY_REFLECT_DB",
    str(Path.home() / "lifelog" / "data" / "index.db"),
))

# Obsidian vault
VAULT_DAILIES = Path(os.environ.get(
    "DAILY_REFLECT_DAILIES_DIR",
    str(Path.home() / "Obsidian" / "Main" / "dailies"),
))
REFLECTIONS_DIR = Path(os.environ.get(
    "DAILY_REFLECT_REFLECTIONS_DIR",
    str(Path.home() / "Obsidian" / "Main" / "projects" / "daily-reflection-system" / "reflections"),
))

# Ollama
OLLAMA_URL = os.environ.get(
    "DAILY_REFLECT_OLLAMA_URL",
    "http://localhost:11434/api/generate",
)
DEFAULT_MODEL = os.environ.get(
    "DAILY_REFLECT_MODEL",
    "gemma4:e2b",
)

# Google Calendar
GCAL_CREDENTIALS_PATH = Path(os.environ.get(
    "DAILY_REFLECT_GCAL_CREDENTIALS",
    str(Path.home() / "secrets" / "gcal_client_secret.json"),
))
GCAL_TOKEN_PATH = Path(os.environ.get(
    "DAILY_REFLECT_GCAL_TOKEN",
    str(Path.home() / "Projects" / "universal-calendar-capture" / "token.json"),
))

# Cache
CACHE_DIR = Path(os.environ.get(
    "DAILY_REFLECT_CACHE_DIR",
    str(Path.home() / "Projects" / "daily-reflection-system" / "cache"),
))
