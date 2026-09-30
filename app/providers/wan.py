"""Native Wan 2.1 text-to-video integration.

The official Wan runtime is intentionally launched in a subprocess. This keeps
the API worker responsive and prevents a large CUDA model from being imported
when Wan is disabled or its checkpoint is incomplete.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .. import config


class WanUnavailableError(RuntimeError):
    """Raised when Wan cannot be used by the current environment."""


def _python() -> str:
    return config.WAN_PYTHON or sys.executable


def readiness() -> tuple[bool, str]:
    if not config.WAN_ENABLED:
        return False, "disabled by WAN_ENABLED=0"
    runtime = config.WAN_RUNTIME_DIR / "generate.py"
    if not runtime.exists():
        return False, f"runtime missing: {runtime}"
    required = {
        "diffusion_pytorch_model.safetensors": 5_000_000_000,
        "models_t5_umt5-xxl-enc-bf16.pth": 10_000_000_000,
        "Wan2.1_VAE.pth": 400_000_000,
    }
    for name, minimum_size in required.items():
        path = config.WAN_MODEL_DIR / name
        if not path.exists():
            return False, f"checkpoint missing: {name}"
        if path.stat().st_size < minimum_size:
            return False, f"checkpoint incomplete: {name}"
    return True, "ready"


def is_available() -> bool:
    return readiness()[0]


def generate(prompt: str, output: Path, seed: int) -> dict:
    ready, reason = readiness()
    if not ready:
        raise WanUnavailableError(reason)
    if not prompt.strip():
        raise ValueError("Wan requires a non-empty prompt")

    output.parent.mkdir(parents=True, exist_ok=True)
    args = [
        _python(),
        str(config.WAN_RUNTIME_DIR / "generate.py"),
        "--task",
        "t2v-1.3B",
        "--size",
        config.WAN_SIZE,
        "--frame_num",
        str(config.WAN_FRAME_NUM),
        "--ckpt_dir",
        str(config.WAN_MODEL_DIR),
        "--offload_model",
        str(config.WAN_OFFLOAD_MODEL),
        "--sample_steps",
        str(config.WAN_SAMPLE_STEPS),
        "--sample_shift",
        str(config.WAN_SAMPLE_SHIFT),
        "--sample_guide_scale",
        str(config.WAN_GUIDE_SCALE),
        "--base_seed",
        str(seed),
        "--prompt",
        prompt,
        "--save_file",
        str(output),
    ]
    if config.WAN_T5_CPU:
        args.insert(args.index("--sample_steps"), "--t5_cpu")
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        process = subprocess.run(
            args,
            cwd=config.WAN_RUNTIME_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=config.WAN_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Wan generation timed out after {config.WAN_TIMEOUT}s") from exc
    if process.returncode != 0:
        detail = (process.stderr or process.stdout).strip()[-3000:]
        raise RuntimeError(f"Wan generation failed ({process.returncode}): {detail}")
    if not output.exists() or output.stat().st_size < 100_000:
        raise RuntimeError("Wan exited successfully but did not produce a valid video")
    return {"path": str(output), "kind": "video", "source": "Wan 2.1 T2V-1.3B"}
