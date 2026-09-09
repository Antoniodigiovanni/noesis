import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from test_vertical_slice import meditations_payload


async def with_client(db_path, operation):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "noesis.mcp"],
        cwd=os.getcwd(),
        env={"NOESIS_DB_PATH": str(db_path), "PATH": os.environ.get("PATH", "")},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await operation(session)


def data(result):
    assert not result.is_error, result.content
    assert result.structured_content["success"] is True, result.structured_content
    return result.structured_content["data"]


def test_all_eight_tools_and_restart_persistence(tmp_path):
    db_path = tmp_path / "mcp.db"

    async def first_process(session):
        listed = await session.list_tools()
        assert {tool.name for tool in listed.tools} == {
            "propose_capture", "commit_capture", "start_review", "submit_attempt",
            "resolve_learning_issue", "update_learning_state", "recall_context", "get_progress",
        }
        proposed = data(await session.call_tool("propose_capture", {"proposal": meditations_payload(), "idempotency_key": "mcp-propose"}))
        retry = data(await session.call_tool("propose_capture", {"proposal": meditations_payload(), "idempotency_key": "mcp-propose"}))
        assert retry["proposal_id"] == proposed["proposal_id"]
        decisions = [{"item_id": item["item_id"], "action": "approve"} for item in proposed["items"]]
        committed = data(await session.call_tool("commit_capture", {"proposal_id": proposed["proposal_id"], "decisions": decisions, "idempotency_key": "mcp-commit"}))
        review = data(await session.call_tool("start_review", {"idempotency_key": "mcp-start"}))
        question = data(await session.call_tool("start_review", {"review_session_id": review["review_session_id"], "question_text": "What is outside your control, and what remains yours?", "model_id": "test:model", "prompt_version": "question-v1", "idempotency_key": "mcp-question"}))
        submitted = data(await session.call_tool("submit_attempt", {
            "review_session_id": review["review_session_id"], "exact_response": "Other people's choices are outside my control; I can choose my deliberate response.",
            "assessment": {"recall_outcome": "successful", "evidence": ["distinguished choices from response"], "missing_elements": [], "possible_misconception": None, "assessor_confidence": 0.95, "user_confidence": 0.8, "model_id": "test:model", "rubric_version": "rubric-v1"},
            "idempotency_key": "mcp-attempt",
        }))
        disputed = data(await session.call_tool("resolve_learning_issue", {"action": "dispute_assessment", "assessment_id": submitted["assessment_id"], "idempotency_key": "mcp-dispute"}))
        assert disputed["status"] == "disputed"
        resolved = data(await session.call_tool("resolve_learning_issue", {"action": "accept_self_grade", "assessment_id": submitted["assessment_id"], "self_grade": "difficult", "idempotency_key": "mcp-resolve"}))
        assert resolved["status"] == "accepted"
        changed = data(await session.call_tool("update_learning_state", {"knowledge_unit_id": committed["created"]["knowledge_units"][0], "importance": 0.95, "idempotency_key": "mcp-update"}))
        assert changed["mastery_unchanged"] is True
        recalled = data(await session.call_tool("recall_context", {"query": "control deliberate response"}))
        assert recalled["results"]
        progress = data(await session.call_tool("get_progress", {}))
        assert progress["lifecycle_counts"]["active"] == 2
        return review["review_session_id"]

    review_id = asyncio.run(with_client(db_path, first_process))

    async def second_process(session):
        progress = data(await session.call_tool("get_progress", {}))
        assert progress["lifecycle_counts"]["active"] == 2
        resumed = data(await session.call_tool("start_review", {"review_session_id": review_id, "idempotency_key": "mcp-resume-after-restart"}))
        assert resumed["review_session_id"] == review_id
        recalled = data(await session.call_tool("recall_context", {"query": "other choices"}))
        assert recalled["results"]
        return True

    assert asyncio.run(with_client(db_path, second_process))


def test_mcp_validation_error(tmp_path):
    async def operation(session):
        result = await session.call_tool("propose_capture", {"proposal": {"learner_id": "default", "sources": [], "concepts": [], "knowledge_units": [], "unexpected": True}, "idempotency_key": "bad"})
        assert not result.is_error
        assert result.structured_content["success"] is False
        assert result.structured_content["error"]["code"] == "validation_error"
        return True
    assert asyncio.run(with_client(tmp_path / "bad.db", operation))
