"""Settings, read from the environment (a local .env is loaded if present).

No secret lives in this file. Keys are read from the environment at call time,
used only by the backend, and never sent to the browser or written to logs.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError:
        return default


# --- Open-weight allow-list ---------------------------------------------------
# Prices are USD per 1M tokens (input, output). None = not known statically; the
# live catalog is used when reachable, otherwise FALLBACK_PRICE (a deliberate
# over-estimate, flagged as estimated in the log).
ALLOWED_MODELS: dict[str, dict[str, dict]] = {
    "hackclub": {
        "z-ai/glm-5.3": {"in": 0.07, "out": 1.40},
        "z-ai/glm-5.3-flash": {"in": 0.15, "out": 0.50},
        "deepseek/deepseek-v4.1-flash": {"in": None, "out": None},
        "qwen/qwen3.8-2.4t-a95b": {"in": 2.00, "out": 6.00},
        "moonshotai/kimi-k3.1-pro": {"in": None, "out": 8.40},
    },
    # NVIDIA Build free tier: no charge.
    "nvidia": {
        "glm-5-3-flash": {"in": 0.0, "out": 0.0},
        "deepseek-v4.1-flash": {"in": 0.0, "out": 0.0},
        "kimi-k3.1-pro": {"in": 0.0, "out": 0.0},
    },
    # Local models: no charge.
    "ollama": {
        "qwen3:8b": {"in": 0.0, "out": 0.0},
        "qwen3:4b": {"in": 0.0, "out": 0.0},
        "gpt-oss:20b": {"in": 0.0, "out": 0.0},
    },
}
FALLBACK_PRICE = 8.40

# Never used, whatever the settings say: closed-weight or expiring models.
BLOCKED_MODELS = {"qwen/qwen4-max", "qwen/qwen3.8-max-0902", "z-ai/glm-5.1"}
BLOCKED_PREFIXES = ("anthropic/", "google/", "openai/gpt-4", "openai/gpt-5", "openai/o")

ROLE_TIER = {"orchestrator": "master", "chair": "master", "advocate": "advocate", "critic": "critic"}
DEFAULT_MODELS = {
    "hackclub": {
        "master": "z-ai/glm-5.3",
        "advocate": "z-ai/glm-5.3",
        "critic": "deepseek/deepseek-v4.1-flash",  # different family from the advocate
        "worker": "z-ai/glm-5.3-flash",
    },
    "nvidia": {
        "master": "glm-5-3-flash",
        "advocate": "glm-5-3-flash",
        "critic": "deepseek-v4.1-flash",
        "worker": "glm-5-3-flash",
    },
}
TIER_ENV = {"master": "MASTER_MODEL", "advocate": "ADVOCATE_MODEL", "critic": "CRITIC_MODEL", "worker": "WORKER_MODEL"}


def allowed_models(provider: str) -> dict[str, dict]:
    models = dict(ALLOWED_MODELS.get(provider, {}))
    for extra in env("EXTRA_OPEN_WEIGHT_MODELS").split(","):
        if extra.strip():
            models.setdefault(extra.strip(), {"in": None if provider == "hackclub" else 0.0,
                                              "out": None if provider == "hackclub" else 0.0})
    return models


def is_blocked(model: str) -> bool:
    return model in BLOCKED_MODELS or model.startswith(BLOCKED_PREFIXES)


def llm_settings() -> dict:
    """Resolve the provider chain: primary first, then the free fallbacks, local Ollama last."""
    key = env("LLM_API_KEY")
    if "your-key-here" in key:
        key = ""
    nvidia_key = env("NVIDIA_API_KEY") or (key if key.startswith("nvapi-") else "")
    hackclub_key = key if key.startswith("sk-hc-") else ""
    primary = env("LLM_PROVIDER", "auto").lower()
    if primary not in ("hackclub", "nvidia", "ollama"):
        primary = "hackclub" if hackclub_key else "nvidia" if nvidia_key else "ollama"
    if primary == "hackclub" and not hackclub_key:
        hackclub_key = key
    providers = {
        "hackclub": {"base_url": "https://ai.hackclub.com/proxy/v1", "key": hackclub_key, "metered": True, "rpm": 240},
        "nvidia": {"base_url": "https://integrate.api.nvidia.com/v1", "key": nvidia_key, "metered": False, "rpm": 35},
        "ollama": {"base_url": env("OLLAMA_BASE_URL", "http://localhost:11434"), "key": "", "metered": False, "rpm": 0},
    }
    if env("LLM_BASE_URL"):
        providers[primary]["base_url"] = env("LLM_BASE_URL").rstrip("/")
    available = [p for p in ("hackclub", "nvidia") if providers[p]["key"]] + ["ollama"]
    chain = [primary] if primary in available else []
    chain += [p for p in available if p not in chain]
    return {
        "primary": chain[0],
        "chain": chain,
        "providers": providers,
        "ollama_model": env("OLLAMA_MODEL", "qwen3:8b"),
        "daily_budget": env_float("DAILY_BUDGET_USD", 2.50),
    }


def model_for(provider: str, role: str, primary: str) -> str:
    if provider == "ollama":
        return env("OLLAMA_MODEL", "qwen3:8b")
    tier = ROLE_TIER.get(role, "worker")
    if provider == primary:
        if role == "chair" and env("CHAIR_MODEL"):
            return env("CHAIR_MODEL")
        if env(TIER_ENV[tier]):
            return env(TIER_ENV[tier])
        if env("LLM_MODEL"):
            return env("LLM_MODEL")
    return DEFAULT_MODELS[provider][tier]
