"""Eval & gate runner for durable-research-fleet.

Runs the full ResearchWorkflow (with verify=True Critic loop) through Temporal's
local test server and production Worker builder, then checks structural,
citation-boundedness, and budget gates.

Usage:
  .venv/bin/python -m evals.run_evals              # uses CASSETTE_MODE=synthetic if no cassettes
  CASSETTE_MODE=record .venv/bin/python -m evals.run_evals
  CASSETTE_MODE=replay .venv/bin/python -m evals.run_evals
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from temporalio.api.workflowservice.v1 import (
    CreateWorkerDeploymentRequest,
    DescribeWorkerDeploymentRequest,
    SetWorkerDeploymentCurrentVersionRequest,
)
from temporalio.testing import WorkflowEnvironment

import llm
import runtime
from apps import ACTIVITIES, WORKFLOWS
from evals.cassettes import CASSETTE_DIR, use_cassettes
from research_types import ResearchRequest

QUESTIONS_PATH = Path(__file__).parent / "questions.json"
CITATION_RE = re.compile(r"\[(\d+)\]")


@dataclass
class EvalOutcome:
    id: str
    passed: bool
    sub_questions: int
    critique_rounds: int
    sources: int
    total_tokens: int
    web_searches: int
    errors: list[str]


@contextlib.contextmanager
def _synthetic_llm() -> Iterator[None]:
    """Deterministic in-process LLM responses that exercise the full Critic loop."""
    real_complete = llm.complete
    research_calls: dict[str, int] = {}

    async def fake_complete(
        *,
        provider: str = llm.DEFAULT_PROVIDER,
        system: str,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> llm.LLMResult:
        if json_schema and "sub_questions" in json_schema.get("properties", {}):
            return llm.LLMResult(
                text=json.dumps(
                    {
                        "sub_questions": [
                            "What is the current US market size and adoption rate?",
                            "Who are the primary incumbents and what is their technical moat?",
                            "What are the main unit-economics and reliability risks?",
                        ]
                    }
                ),
                usage=llm.Usage(input_tokens=120, output_tokens=60),
            )

        if json_schema and "items" in json_schema.get("properties", {}):
            # Flag index 1 on first critique round if it has not been revised yet.
            needs_revision = "Critic feedback to address:" not in prompt and research_calls.get("idx1", 0) < 2
            items = [
                {"index": 0, "passed": True, "feedback": ""},
                {
                    "index": 1,
                    "passed": not needs_revision,
                    "feedback": "Add primary benchmark figures and competitor pricing." if needs_revision else "",
                },
                {"index": 2, "passed": True, "feedback": ""},
            ]
            return llm.LLMResult(
                text=json.dumps({"items": items}),
                usage=llm.Usage(input_tokens=180, output_tokens=90),
            )

        if "Original question:" in prompt:
            return llm.LLMResult(
                text=(
                    "## Executive Summary\n"
                    "Durable multi-agent systems outperform single-prompt wrappers on reliability [1].\n\n"
                    "## Market & Moat\n"
                    "Verified citations and fault tolerance create defensible enterprise value [2][3]."
                ),
                usage=llm.Usage(input_tokens=300, output_tokens=150),
            )

        if "competitor" in prompt.lower() or "incumbent" in prompt.lower():
            research_calls["idx1"] = research_calls.get("idx1", 0) + 1
            url = "https://example.com/competitors"
            title = "Competitor Benchmark Report"
        elif "market size" in prompt.lower():
            url = "https://example.com/market"
            title = "Market Adoption Data"
        else:
            url = "https://example.com/risks"
            title = "Unit Economics & Reliability"

        return llm.LLMResult(
            text="Grounded finding with primary-source metrics and dates (2026).",
            sources=[llm.Source(url=url, title=title)],
            usage=llm.Usage(input_tokens=200, output_tokens=120, web_searches=2),
        )

    llm.complete = fake_complete
    try:
        yield
    finally:
        llm.complete = real_complete


async def _make_current(client: Any, deployment_name: str, build_id: str) -> None:
    svc = client.workflow_service
    try:
        await svc.create_worker_deployment(
            CreateWorkerDeploymentRequest(
                namespace=client.namespace, deployment_name=deployment_name, identity="evals"
            )
        )
    except Exception:
        pass
    described = await svc.describe_worker_deployment(
        DescribeWorkerDeploymentRequest(
            namespace=client.namespace, deployment_name=deployment_name
        )
    )
    await svc.set_worker_deployment_current_version(
        SetWorkerDeploymentCurrentVersionRequest(
            namespace=client.namespace,
            deployment_name=deployment_name,
            build_id=build_id,
            conflict_token=described.conflict_token,
            identity="evals",
            ignore_missing_task_queues=True,
        )
    )


def _check_citations(text: str, num_sources: int) -> list[int]:
    """Return any out-of-range citation numbers in Answer.text."""
    bad: list[int] = []
    for match in CITATION_RE.findall(text):
        n = int(match)
        if n < 1 or n > num_sources:
            bad.append(n)
    return bad


async def run_suite() -> list[EvalOutcome]:
    cases = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    mode = os.environ.get("CASSETTE_MODE", "").strip().lower()
    if not mode:
        has_cassettes = CASSETTE_DIR.exists() and any(CASSETTE_DIR.glob("*.json"))
        mode = "replay" if has_cassettes else "synthetic"

    os.environ.setdefault("TEMPORAL_TASK_QUEUE", "eval-queue")
    os.environ.setdefault("TEMPORAL_DEPLOYMENT_NAME", "eval-deployment")
    os.environ.setdefault("BUILD_ID", "eval-build")
    settings = runtime.Settings.from_env()

    ctx = _synthetic_llm() if mode == "synthetic" else use_cassettes(mode)
    outcomes: list[EvalOutcome] = []

    with ctx:
        async with await WorkflowEnvironment.start_local() as env:
            worker = runtime.build_worker(env.client, WORKFLOWS, ACTIVITIES, settings)
            async with worker:
                await _make_current(env.client, settings.deployment_name, settings.build_id)

                for case in cases:
                    wf_id = f"eval-{case['id']}-{uuid.uuid4().hex[:6]}"
                    handle = await env.client.start_workflow(
                        "ResearchWorkflow",
                        ResearchRequest(
                            question=case["question"],
                            provider=case["provider"],
                            verify=True,
                        ),
                        id=wf_id,
                        task_queue=settings.task_queue,
                    )

                    # Wait until workflow reaches awaiting_review, then accept.
                    for _ in range(120):
                        prog = await handle.query("progress")
                        if prog.get("awaiting_review") or prog.get("stage") in ("done", "failed"):
                            break
                        await asyncio.sleep(0.1)

                    await handle.signal("review", args=["accept", ""])
                    answer = await handle.result()
                    prog = await handle.query("progress")

                    answer_text = answer["text"] if isinstance(answer, dict) else answer.text
                    answer_sources = (
                        answer.get("sources", []) if isinstance(answer, dict) else answer.sources
                    )

                    errors: list[str] = []
                    subs = prog.get("sub_questions", [])
                    if len(subs) < 2:
                        errors.append(f"too few sub_questions ({len(subs)})")
                    if len(set(subs)) != len(subs):
                        errors.append("duplicate sub_questions")

                    bad_cites = _check_citations(answer_text, len(answer_sources))
                    if bad_cites:
                        errors.append(f"out-of-range citations: {bad_cites}")

                    if answer_text.strip() == "":
                        errors.append("empty answer")

                    usage = prog.get("usage", {})
                    total_tokens = int(usage.get("total_tokens", 0))
                    web_searches = int(usage.get("web_searches", 0))
                    if total_tokens > case["max_tokens"]:
                        errors.append(f"tokens {total_tokens} > {case['max_tokens']}")
                    if web_searches > case["max_searches"]:
                        errors.append(f"searches {web_searches} > {case['max_searches']}")

                    outcomes.append(
                        EvalOutcome(
                            id=case["id"],
                            passed=not errors,
                            sub_questions=len(subs),
                            critique_rounds=int(prog.get("critique_rounds", 0)),
                            sources=len(answer_sources),
                            total_tokens=total_tokens,
                            web_searches=web_searches,
                            errors=errors,
                        )
                    )

    return outcomes


def main() -> int:
    outcomes = asyncio.run(run_suite())
    print("\n=== Research Fleet Eval Gate ===")
    for o in outcomes:
        status = "PASS" if o.passed else "FAIL"
        print(
            f"[{status}] {o.id}: subs={o.sub_questions} "
            f"critique_rounds={o.critique_rounds} sources={o.sources} "
            f"tokens={o.total_tokens} searches={o.web_searches}"
        )
        for err in o.errors:
            print(f"       -> {err}")
    failed = [o for o in outcomes if not o.passed]
    print(f"Summary: {len(outcomes) - len(failed)}/{len(outcomes)} passed\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
