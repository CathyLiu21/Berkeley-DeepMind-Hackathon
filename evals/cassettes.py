"""VCR-style record/replay cassette wrapper around `llm.complete`.

Modes (via CASSETTE_MODE env var or context manager):
  - replay (default): load recorded LLMResult from evals/cassettes/<key>.json
  - record: call real llm.complete and write the result to disk
  - off: pass straight through to llm.complete
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

import llm

CASSETTE_DIR = Path(__file__).parent / "cassettes"


def cassette_key(
    *,
    provider: str,
    model: str | None,
    system: str,
    prompt: str,
) -> str:
    """Stable SHA-256 key for a model request."""
    payload = json.dumps(
        {
            "provider": llm.normalize_provider(provider),
            "model": model or "",
            "system": system,
            "prompt": prompt,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _serialize_result(res: llm.LLMResult) -> dict[str, Any]:
    return {
        "text": res.text,
        "sources": [asdict(s) for s in res.sources],
        "usage": asdict(res.usage),
        "rounds": res.rounds,
    }


def _deserialize_result(data: dict[str, Any]) -> llm.LLMResult:
    return llm.LLMResult(
        text=data["text"],
        sources=[llm.Source(**s) for s in data.get("sources", [])],
        usage=llm.Usage(**data.get("usage", {})),
        rounds=int(data.get("rounds", 1)),
    )


@contextlib.contextmanager
def use_cassettes(
    mode: str | None = None,
    cassette_dir: Path = CASSETTE_DIR,
) -> Iterator[None]:
    """Patch `llm.complete` with record/replay cassette handling."""
    active_mode = (mode or os.environ.get("CASSETTE_MODE", "replay")).strip().lower()
    if active_mode == "off":
        yield
        return

    real_complete = llm.complete

    async def wrapped_complete(
        *,
        provider: str = llm.DEFAULT_PROVIDER,
        system: str,
        prompt: str,
        model: str | None = None,
        **kwargs: Any,
    ) -> llm.LLMResult:
        key = cassette_key(
            provider=provider,
            model=model,
            system=system,
            prompt=prompt,
        )
        path = cassette_dir / f"{key}.json"

        if active_mode == "replay":
            if not path.exists():
                raise FileNotFoundError(
                    f"Missing cassette {path} for provider={provider!r}. "
                    "Run with CASSETTE_MODE=record to capture it."
                )
            return _deserialize_result(json.loads(path.read_text(encoding="utf-8")))

        if active_mode == "record":
            res = await real_complete(
                provider=provider,
                system=system,
                prompt=prompt,
                model=model,
                **kwargs,
            )
            cassette_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(_serialize_result(res), indent=2),
                encoding="utf-8",
            )
            return res

        raise ValueError(f"Unsupported CASSETTE_MODE={active_mode!r}")

    llm.complete = wrapped_complete
    try:
        yield
    finally:
        llm.complete = real_complete

