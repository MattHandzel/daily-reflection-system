"""Configuration — layered: env var > config file > default.

Config file (TOML) is looked for at ``$DAILY_REFLECT_CONFIG`` or
``~/.config/daily-reflect/config.toml``. Every value is also overridable by an
environment variable so the pipeline can run in CI/sandboxes without a file.

The timezone is *not* hardcoded: Matt's day boundary and all displayed times
follow ``timezone`` (env ``DAILY_REFLECT_TZ``). He is in Berkeley now (Pacific)
but home base is Chicago (Central) — set it per location.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - 3.10 fallback
    tomllib = None


# --- Life Scheduler calendar (template time-block plan lives here, not primary).
#     Id from the vault CLAUDE.md. ---
LIFE_SCHEDULER_CALENDAR_ID = (
    "d025c2d71036a3fd4ff6f5e7b44e7e785bf55169cc6b35fbe54b14de0666483d"
    "@group.calendar.google.com"
)


def _load_file() -> dict:
    path = os.environ.get("DAILY_REFLECT_CONFIG") or str(
        Path.home() / ".config" / "daily-reflect" / "config.toml"
    )
    p = Path(path)
    if tomllib is None or not p.exists():
        return {}
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


_FILE = _load_file()


def _get(key: str, env: str, default):
    """env var > config-file key > default."""
    if env in os.environ:
        return os.environ[env]
    if key in _FILE:
        return _FILE[key]
    return default


def _get_path(key: str, env: str, default: Path) -> Path:
    return Path(str(_get(key, env, str(default)))).expanduser()


def _get_int(key: str, env: str, default: int) -> int:
    return int(_get(key, env, default))


@dataclass(frozen=True)
class Config:
    # Timezone / day boundary
    timezone: str = "America/Los_Angeles"
    day_boundary_hour: int = 4

    # Lifelog data
    screen_dir: Path = field(default_factory=lambda: Path.home() / "lifelog" / "data" / "screen")
    db_path: Path = field(default_factory=lambda: Path.home() / "lifelog" / "data" / "index.db")

    # Obsidian vault
    dailies_dir: Path = field(default_factory=lambda: Path.home() / "Obsidian" / "Main" / "dailies")
    reflections_dir: Path = field(
        default_factory=lambda: Path.home()
        / "Obsidian" / "Main" / "projects" / "daily-reflection-system" / "reflections"
    )

    # Ollama
    ollama_url: str = "http://localhost:11434/api/generate"
    model: str = "gemma3:4b-it-qat"
    prompt_version: str = "v2"
    concurrency: int = 3
    request_timeout: int = 120
    # Free the shared GPU (STT + embeddings live on the same 12GB card) soon
    # after a burst instead of holding it for Ollama's 5-minute default.
    keep_alive: str = "30s"

    # Google Calendar
    gcal_credentials: Path = field(default_factory=lambda: Path.home() / "secrets" / "gcal_client_secret.json")
    gcal_token: Path = field(
        default_factory=lambda: Path(
            os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        )
        / "universal-calendar-capture" / "token.json"
    )
    gcal_calendar_ids: tuple = ("primary", LIFE_SCHEDULER_CALENDAR_ID)

    # State
    cache_dir: Path = field(default_factory=lambda: Path.home() / "Projects" / "daily-reflection-system" / "cache")

    # Segmentation / sampling
    min_segment_seconds: int = 20
    afk_gap_seconds: int = 300  # gap in window log > this => AFK/break
    prefer_png: bool = True

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def watermark_dir(self) -> Path:
        return self.cache_dir / "watermark"


def load_config() -> Config:
    """Build the effective config from env vars, then TOML file, then defaults."""
    cal_ids = _get("gcal_calendar_ids", "DAILY_REFLECT_GCAL_CALENDARS", None)
    if isinstance(cal_ids, str):
        cal_ids = tuple(c.strip() for c in cal_ids.split(",") if c.strip())
    elif isinstance(cal_ids, list):
        cal_ids = tuple(cal_ids)
    else:
        cal_ids = ("primary", LIFE_SCHEDULER_CALENDAR_ID)

    prefer_png = _get("prefer_png", "DAILY_REFLECT_PREFER_PNG", "1")
    prefer_png = str(prefer_png).lower() not in ("0", "false", "no")

    return Config(
        timezone=str(_get("timezone", "DAILY_REFLECT_TZ", "America/Los_Angeles")),
        day_boundary_hour=_get_int("day_boundary_hour", "DAILY_REFLECT_DAY_BOUNDARY_HOUR", 4),
        screen_dir=_get_path("screen_dir", "DAILY_REFLECT_SCREEN_DIR", Path.home() / "lifelog" / "data" / "screen"),
        db_path=_get_path("db_path", "DAILY_REFLECT_DB", Path.home() / "lifelog" / "data" / "index.db"),
        dailies_dir=_get_path("dailies_dir", "DAILY_REFLECT_DAILIES_DIR", Path.home() / "Obsidian" / "Main" / "dailies"),
        reflections_dir=_get_path(
            "reflections_dir", "DAILY_REFLECT_REFLECTIONS_DIR",
            Path.home() / "Obsidian" / "Main" / "projects" / "daily-reflection-system" / "reflections",
        ),
        ollama_url=str(_get("ollama_url", "DAILY_REFLECT_OLLAMA_URL", "http://localhost:11434/api/generate")),
        model=str(_get("model", "DAILY_REFLECT_MODEL", "gemma3:4b-it-qat")),
        prompt_version=str(_get("prompt_version", "DAILY_REFLECT_PROMPT_VERSION", "v2")),
        concurrency=_get_int("concurrency", "DAILY_REFLECT_CONCURRENCY", 3),
        request_timeout=_get_int("request_timeout", "DAILY_REFLECT_REQUEST_TIMEOUT", 120),
        keep_alive=str(_get("keep_alive", "DAILY_REFLECT_KEEP_ALIVE", "30s")),
        gcal_credentials=_get_path("gcal_credentials", "DAILY_REFLECT_GCAL_CREDENTIALS", Path.home() / "secrets" / "gcal_client_secret.json"),
        gcal_token=_get_path(
            "gcal_token", "DAILY_REFLECT_GCAL_TOKEN",
            Path(os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")) / "universal-calendar-capture" / "token.json",
        ),
        gcal_calendar_ids=cal_ids,
        cache_dir=_get_path("cache_dir", "DAILY_REFLECT_CACHE_DIR", Path.home() / "Projects" / "daily-reflection-system" / "cache"),
        min_segment_seconds=_get_int("min_segment_seconds", "DAILY_REFLECT_MIN_SEGMENT_SECONDS", 20),
        afk_gap_seconds=_get_int("afk_gap_seconds", "DAILY_REFLECT_AFK_GAP_SECONDS", 300),
        prefer_png=prefer_png,
    )
