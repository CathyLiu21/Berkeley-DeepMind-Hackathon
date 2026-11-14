"""Replay / determinism tests.

Worth having on this project specifically: `HelloWorkflow` is PINNED, so an
in-flight execution finishes on the Version it started on. The moment anyone
switches to AUTO_UPGRADE, or edits the Workflow while executions are open, replay
safety stops being theoretical. This catches non-determinism before deploy.
"""

import pytest
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from workflows import HelloWorkflow

from .conftest import TASK_QUEUE


async def test_history_replays_deterministically(env, worker, wf_id):
    await env.client.execute_workflow(
        HelloWorkflow.run, "world", id=wf_id, task_queue=TASK_QUEUE
    )
    history = await env.client.get_workflow_handle(wf_id).fetch_history()

    # Raises on any non-determinism between the recorded history and current code.
    await Replayer(workflows=[HelloWorkflow]).replay_workflow(history)


async def test_replayer_rejects_a_mismatched_history(env, worker, wf_id):
    """Prove the replay check has teeth — a history from a different Workflow
    shape must fail rather than pass silently.
    """
    await env.client.execute_workflow(
        HelloWorkflow.run, "world", id=wf_id, task_queue=TASK_QUEUE
    )
    history = await env.client.get_workflow_handle(wf_id).fetch_history()

    # Rewrite the recorded Activity name so replay cannot line up.
    as_dict = history.to_json_dict()
    for event in as_dict["events"]:
        attrs = event.get("activityTaskScheduledEventAttributes")
        if attrs:
            attrs["activityType"]["name"] = "some_other_activity"

    with pytest.raises(Exception):
        await Replayer(workflows=[HelloWorkflow]).replay_workflow(
            WorkflowHistory.from_json(wf_id, as_dict)
        )


async def test_research_workflow_verify_history_replays_deterministically(
    env, settings, wf_id
):
    """`ResearchWorkflow` with `verify=True` (including the Critic revision loop)
    must replay cleanly under Temporal's `Replayer` with zero non-determinism.
    """
    import asyncio
    import time

    from temporalio import activity

    import runtime
    from llm import Usage
    from research_types import (
        Answer,
        CritiqueItem,
        CritiqueReport,
        Finding,
        ResearchPlan,
        ResearchRequest,
        SubQuestion,
    )
    from research_workflow import ResearchWorkflow

    from .conftest import make_current

    @activity.defn(name="plan_research")
    async def plan(question: str, provider: str) -> ResearchPlan:
        return ResearchPlan(
            sub_questions=[SubQuestion(index=i, text=f"sub {i}") for i in range(2)],
            usage=Usage(input_tokens=10, output_tokens=10),
        )

    @activity.defn(name="research_subquestion")
    async def research(sub: SubQuestion, provider: str) -> Finding:
        revised = "Critic feedback to address:" in sub.text
        return Finding(
            index=sub.index,
            question=sub.text,
            summary=f"{'revised' if revised else 'initial'} {sub.index}",
            usage=Usage(input_tokens=50, output_tokens=50),
        )

    @activity.defn(name="critique_findings")
    async def critique(
        question: str, findings: list[Finding], provider: str
    ) -> CritiqueReport:
        return CritiqueReport(
            items=[
                CritiqueItem(index=0, passed=True, feedback=""),
                CritiqueItem(
                    index=1, passed=False, feedback="Verify revenue figures."
                ),
            ],
            usage=Usage(input_tokens=20, output_tokens=20),
        )

    @activity.defn(name="synthesize")
    async def synth(question: str, findings: list[Finding], provider: str) -> Answer:
        return Answer(
            text=f"synthesized {len(findings)} findings",
            usage=Usage(input_tokens=30, output_tokens=30),
        )

    w = runtime.build_worker(
        env.client,
        [ResearchWorkflow],
        [plan, research, critique, synth],
        settings,
    )
    async with w:
        await make_current(env.client, settings.deployment_name, settings.build_id)
        handle = await env.client.start_workflow(
            ResearchWorkflow.run,
            ResearchRequest(question="verify replay", verify=True),
            id=wf_id,
            task_queue=TASK_QUEUE,
        )
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            state = await handle.query("progress")
            if state["stage"] == "awaiting_review":
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError(f"never reached awaiting_review; last was {state}")

        assert state["critique_rounds"] == 1
        await handle.signal("review", args=["accept", ""])
        await handle.result()

    history = await env.client.get_workflow_handle(wf_id).fetch_history()
    await Replayer(workflows=[ResearchWorkflow]).replay_workflow(history)
