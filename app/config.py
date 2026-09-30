"""Central configuration. Every value can be overridden with an environment variable.

Qreate runs with zero API keys (offline mode: template script, generated title
cards, espeak voice). Each key you add upgrades one stage of the pipeline.
"""
import os
from pathlib import Path

try:  # optional: load a local .env file during development
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(_env("DATA_DIR", str(ROOT / "data")))
JOBS_DIR = DATA_DIR / "jobs"
CACHE_DIR = DATA_DIR / "cache"
ASSETS_DIR = ROOT / "assets"
MUSIC_DIR = ASSETS_DIR / "music"
WEB_DIR = ROOT / "web"

for _d in (JOBS_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---- LLM providers (tried in LLM_ORDER; any that have a key are used) ----
GEMINI_API_KEY = _env("GEMINI_API_KEY")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_API_KEY = _env("GROQ_API_KEY")
GROQ_MODEL = _env("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-sonnet-4-6")
LLM_ORDER = [p.strip() for p in _env("LLM_ORDER", "gemini,groq,openai,anthropic").split(",") if p.strip()]

# ---- Research ----
TAVILY_API_KEY = _env("TAVILY_API_KEY")  # optional; Wikipedia is always tried

# ---- Visuals ----
PEXELS_API_KEY = _env("PEXELS_API_KEY")
USE_POLLINATIONS = _env("USE_POLLINATIONS", "1") == "1"  # free AI image generation, no key
POLLINATIONS_MODEL = _env("POLLINATIONS_MODEL", "flux")
WAN_ENABLED = _env("WAN_ENABLED", "1") == "1"
WAN_RUNTIME_DIR = Path(_env("WAN_RUNTIME_DIR", str(ROOT / ".venv" / "wan2.1-runtime")))
WAN_MODEL_DIR = Path(
    _env("WAN_MODEL_DIR", str(ROOT / ".venv" / "models" / "wan2.1-t2v-1.3b"))
)
WAN_PYTHON = _env("WAN_PYTHON", "")
WAN_SIZE = _env("WAN_SIZE", "832*480")
WAN_FRAME_NUM = int(_env("WAN_FRAME_NUM", "49"))
WAN_SAMPLE_STEPS = int(_env("WAN_SAMPLE_STEPS", "30"))
WAN_SAMPLE_SHIFT = float(_env("WAN_SAMPLE_SHIFT", "8"))
WAN_GUIDE_SCALE = float(_env("WAN_GUIDE_SCALE", "6"))
WAN_OFFLOAD_MODEL = _env("WAN_OFFLOAD_MODEL", "1") == "1"
WAN_T5_CPU = _env("WAN_T5_CPU", "1") == "1"
WAN_TIMEOUT = int(_env("WAN_TIMEOUT", "600"))

# ---- Voice ----
TTS_PROVIDER = _env("TTS_PROVIDER", "edge")  # "sarvam" or "edge"; espeak-ng / silence are fallbacks
SARVAM_API_KEY = _env("SARVAM_API_KEY")
SARVAM_TTS_MODEL = _env("SARVAM_TTS_MODEL", "bulbul:v3")  # bulbul:v4-flash is beta (needs access)
SARVAM_TTS_SPEAKER = _env("SARVAM_TTS_SPEAKER", "priya")  # must be valid for the model
SARVAM_TTS_PACE = float(_env("SARVAM_TTS_PACE", "1.0"))
SARVAM_LANGUAGES = {"english": "en-IN", "hinglish": "hi-IN", "hindi": "hi-IN"}
USE_EDGE_TTS = _env("USE_EDGE_TTS", "1") == "1"  # free Microsoft neural voices, no key
VOICES = {
    "english": _env("VOICE_ENGLISH", "en-IN-NeerjaNeural"),
    "hinglish": _env("VOICE_HINGLISH", "en-IN-PrabhatNeural"),
    "hindi": _env("VOICE_HINDI", "hi-IN-SwaraNeural"),
}

# ---- Pipeline behaviour ----
OFFLINE_MODE = _env("OFFLINE_MODE", "0") == "1"  # force offline for demos without internet
MAX_WORKERS = int(_env("MAX_WORKERS", "2"))
CRITIC_THRESHOLD = float(_env("CRITIC_THRESHOLD", "7.5"))
CRITIC_MAX_ROUNDS = int(_env("CRITIC_MAX_ROUNDS", "2"))
CRITIC_USE_LLM = _env("CRITIC_USE_LLM", "1") == "1"  # 0 = heuristic critic, LLM only writes the script
HTTP_TIMEOUT = float(_env("HTTP_TIMEOUT", "45"))

# ---- Video format (Qoneqt Global Feed: vertical) ----
WIDTH, HEIGHT, FPS = 1080, 1920, 30

FONT_BOLD = _env("FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_DEVANAGARI = _env(
    "FONT_DEVANAGARI", "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf"
)


def llm_providers_available() -> list[str]:
    keys = {
        "gemini": GEMINI_API_KEY,
        "groq": GROQ_API_KEY,
        "openai": OPENAI_API_KEY,
        "anthropic": ANTHROPIC_API_KEY,
    }
    if OFFLINE_MODE:
        return []
    return [p for p in LLM_ORDER if keys.get(p)]
