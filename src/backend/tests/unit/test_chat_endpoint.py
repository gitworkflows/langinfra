import asyncio
import uuid
from uuid import UUID

import pytest
from httpx import codes
from langinfra.memory import aget_messages
from langinfra.services.database.models.flow import FlowUpdate

from tests.unit.build_utils import build_flow, consume_and_assert_stream, create_flow, get_build_events


@pytest.mark.benchmark
async def test_build_flow(client, json_memory_chatbot_no_llm, logged_in_headers):
    """Test the build flow endpoint with the new two-step process."""
    # First create the flow
    flow_id = await create_flow(client, json_memory_chatbot_no_llm, logged_in_headers)

    # Start the build and get job_id
    build_response = await build_flow(client, flow_id, logged_in_headers)
    job_id = build_response["job_id"]
    assert job_id is not None

    # Get the events stream
    events_response = await get_build_events(client, job_id, logged_in_headers)
    assert events_response.status_code == codes.OK

    # Consume and verify the events
    await consume_and_assert_stream(events_response, job_id)


@pytest.mark.benchmark
async def test_build_flow_from_request_data(client, json_memory_chatbot_no_llm, logged_in_headers):
    """Test building a flow from request data."""
    flow_id = await create_flow(client, json_memory_chatbot_no_llm, logged_in_headers)
    response = await client.get(f"api/v1/flows/{flow_id}", headers=logged_in_headers)
    flow_data = response.json()

    # Start the build and get job_id
    build_response = await build_flow(client, flow_id, logged_in_headers, json={"data": flow_data["data"]})
    job_id = build_response["job_id"]

    # Get the events stream
    events_response = await get_build_events(client, job_id, logged_in_headers)
    assert events_response.status_code == codes.OK

    # Consume and verify the events
    await consume_and_assert_stream(events_response, job_id)
    await check_messages(flow_id)


async def test_build_flow_with_frozen_path(client, json_memory_chatbot_no_llm, logged_in_headers):
    """Test building a flow with a frozen path."""
    flow_id = await create_flow(client, json_memory_chatbot_no_llm, logged_in_headers)

    response = await client.get(f"api/v1/flows/{flow_id}", headers=logged_in_headers)
    flow_data = response.json()
    flow_data["data"]["nodes"][0]["data"]["node"]["frozen"] = True

    # Update the flow with frozen path
    response = await client.patch(
        f"api/v1/flows/{flow_id}",
        json=FlowUpdate(name="Flow", description="description", data=flow_data["data"]).model_dump(),
        headers=logged_in_headers,
    )
    response.raise_for_status()

    # Start the build and get job_id
    build_response = await build_flow(client, flow_id, logged_in_headers)
    job_id = build_response["job_id"]

    # Get the events stream
    events_response = await get_build_events(client, job_id, logged_in_headers)
    assert events_response.status_code == codes.OK

    # Consume and verify the events
    await consume_and_assert_stream(events_response, job_id)
    await check_messages(flow_id)


async def check_messages(flow_id):
    if isinstance(flow_id, str):
        flow_id = UUID(flow_id)
    messages = await aget_messages(flow_id=flow_id, order="ASC")
    flow_id_str = str(flow_id)
    assert len(messages) == 2
    assert messages[0].session_id == flow_id_str
    assert messages[0].sender == "User"
    assert messages[0].sender_name == "User"
    assert messages[0].text == ""
    assert messages[1].session_id == flow_id_str
    assert messages[1].sender == "Machine"
    assert messages[1].sender_name == "AI"


@pytest.mark.benchmark
async def test_build_flow_invalid_job_id(client, logged_in_headers):
    """Test getting events for an invalid job ID."""
    invalid_job_id = str(uuid.uuid4())
    response = await get_build_events(client, invalid_job_id, logged_in_headers)
    assert response.status_code == codes.NOT_FOUND
    assert "Job not found" in response.json()["detail"]


@pytest.mark.benchmark
async def test_build_flow_invalid_flow_id(client, logged_in_headers):
    """Test starting a build with an invalid flow ID."""
    invalid_flow_id = uuid.uuid4()
    response = await client.post(f"api/v1/build/{invalid_flow_id}/flow", json={}, headers=logged_in_headers)
    assert response.status_code == codes.NOT_FOUND


@pytest.mark.benchmark
async def test_build_flow_start_only(client, json_memory_chatbot_no_llm, logged_in_headers):
    """Test only the build flow start endpoint."""
    # First create the flow
    flow_id = await create_flow(client, json_memory_chatbot_no_llm, logged_in_headers)

    # Start the build and get job_id
    build_response = await build_flow(client, flow_id, logged_in_headers)

    # Assert response structure
    assert "job_id" in build_response
    assert isinstance(build_response["job_id"], str)
    # Verify it's a valid UUID
    assert uuid.UUID(build_response["job_id"])


@pytest.mark.benchmark
async def test_build_flow_start_with_inputs(client, json_memory_chatbot_no_llm, logged_in_headers):
    """Test the build flow start endpoint with input data."""
    flow_id = await create_flow(client, json_memory_chatbot_no_llm, logged_in_headers)

    # Start build with some input data
    test_inputs = {"inputs": {"session": "test_session", "input_value": "test message"}}

    build_response = await build_flow(client, flow_id, logged_in_headers, json=test_inputs)

    assert "job_id" in build_response
    assert isinstance(build_response["job_id"], str)
    assert uuid.UUID(build_response["job_id"])


@pytest.mark.benchmark
async def test_build_flow_polling(client, json_memory_chatbot_no_llm, logged_in_headers):
    """Test the build flow endpoint with polling (non-streaming)."""
    # First create the flow
    flow_id = await create_flow(client, json_memory_chatbot_no_llm, logged_in_headers)

    # Start the build and get job_id
    build_response = await build_flow(client, flow_id, logged_in_headers)
    assert "job_id" in build_response, f"Expected job_id in build_response, got {build_response}"
    job_id = build_response["job_id"]
    assert job_id is not None

    # Create a response object that mimics a streaming response but uses polling
    class PollingResponse:
        def __init__(self, client, job_id, headers):
            self.client = client
            self.job_id = job_id
            self.headers = headers
            self.status_code = codes.OK

        async def aiter_lines(self):
            try:
                sleeps = 0
                max_sleeps = 100
                while True:
                    response = await self.client.get(
                        f"api/v1/build/{self.job_id}/events?event_delivery=polling", headers=self.headers
                    )
                    assert response.status_code == codes.OK
                    data = response.json()

                    if data["event"] is None:
                        # No event available, add delay to prevent tight polling
                        await asyncio.sleep(0.1)
                        sleeps += 1
                        continue

                    yield data["event"]

                    # If this was the end event, stop polling
                    if '"end"' in data["event"]:
                        break
                    if sleeps > max_sleeps:
                        msg = "Build event polling timed out."
                        raise TimeoutError(msg)
            except asyncio.TimeoutError as e:
                msg = "Build event polling timed out."
                raise TimeoutError(msg) from e

    polling_response = PollingResponse(client, job_id, logged_in_headers)

    # Use the same consume_and_assert_stream function to verify the events
    await consume_and_assert_stream(polling_response, job_id)


@pytest.mark.benchmark
async def test_cancel_build_unexpected_error(client, json_memory_chatbot_no_llm, logged_in_headers, monkeypatch):
    """Test handling of unexpected exceptions during flow build cancellation."""
    # First create the flow
    flow_id = await create_flow(client, json_memory_chatbot_no_llm, logged_in_headers)

    # Start the build and get job_id
    build_response = await build_flow(client, flow_id, logged_in_headers)
    job_id = build_response["job_id"]
    assert job_id is not None

    # Mock the cancel_flow_build function to raise an unexpected exception
    import langinfra.api.v1.chat

    original_cancel_flow_build = langinfra.api.v1.chat.cancel_flow_build

    async def mock_cancel_flow_build_with_error(*_args, **_kwargs):
        msg = "Unexpected error during cancellation"
        raise RuntimeError(msg)

    monkeypatch.setattr(langinfra.api.v1.chat, "cancel_flow_build", mock_cancel_flow_build_with_error)

    try:
        # Try to cancel the build - should return 500 Internal Server Error
        cancel_response = await client.post(f"api/v1/build/{job_id}/cancel", headers=logged_in_headers)
        assert cancel_response.status_code == codes.INTERNAL_SERVER_ERROR

        # Verify the error message
        response_data = cancel_response.json()
        assert "detail" in response_data
        assert "Unexpected error during cancellation" in response_data["detail"]
    finally:
        # Restore the original function to avoid affecting other tests
        monkeypatch.setattr(langinfra.api.v1.chat, "cancel_flow_build", original_cancel_flow_build)


@pytest.mark.benchmark
async def test_cancel_build_success(client, json_memory_chatbot_no_llm, logged_in_headers, monkeypatch):
    """Test successful cancellation of a flow build."""
    # First create the flow
    flow_id = await create_flow(client, json_memory_chatbot_no_llm, logged_in_headers)

    # Start the build and get job_id
    build_response = await build_flow(client, flow_id, logged_in_headers)
    job_id = build_response["job_id"]
    assert job_id is not None

    # Mock the cancel_flow_build function to simulate a successful cancellation
    import langinfra.api.v1.chat

    original_cancel_flow_build = langinfra.api.v1.chat.cancel_flow_build

    async def mock_successful_cancel_flow_build(*_args, **_kwargs):
        return True  # Return True to indicate successful cancellation

    monkeypatch.setattr(langinfra.api.v1.chat, "cancel_flow_build", mock_successful_cancel_flow_build)

    try:
        # Try to cancel the build (should return success)
        cancel_response = await client.post(f"api/v1/build/{job_id}/cancel", headers=logged_in_headers)
        assert cancel_response.status_code == codes.OK

        # Verify the response structure indicates success
        response_data = cancel_response.json()
        assert "success" in response_data
        assert "message" in response_data
        assert response_data["success"] is True
        assert "cancelled successfully" in response_data["message"].lower()
    finally:
        # Restore the original function to avoid affecting other tests
        monkeypatch.setattr(langinfra.api.v1.chat, "cancel_flow_build", original_cancel_flow_build)


@pytest.mark.benchmark
async def test_cancel_nonexistent_build(client, logged_in_headers):
    """Test cancelling a non-existent flow build."""
    # Generate a random job_id that doesn't exist
    invalid_job_id = str(uuid.uuid4())

    # Try to cancel a non-existent build
    response = await client.post(f"api/v1/build/{invalid_job_id}/cancel", headers=logged_in_headers)
    assert response.status_code == codes.NOT_FOUND
    assert "Job not found" in response.json()["detail"]


@pytest.mark.benchmark
async def test_cancel_build_failure(client, json_memory_chatbot_no_llm, logged_in_headers, monkeypatch):
    """Test handling of cancellation failure."""
    # First create the flow
    flow_id = await create_flow(client, json_memory_chatbot_no_llm, logged_in_headers)

    # Start the build and get job_id
    build_response = await build_flow(client, flow_id, logged_in_headers)
    job_id = build_response["job_id"]
    assert job_id is not None

    # Mock the cancel_flow_build function to simulate a failure
    # The import path in monkeypatch should match exactly how it's imported in the application
    import langinfra.api.v1.chat

    original_cancel_flow_build = langinfra.api.v1.chat.cancel_flow_build

    async def mock_cancel_flow_build(*_args, **_kwargs):
        return False  # Return False to indicate cancellation failure

    monkeypatch.setattr(langinfra.api.v1.chat, "cancel_flow_build", mock_cancel_flow_build)

    try:
        # Try to cancel the build (should return failure but success=False)
        cancel_response = await client.post(f"api/v1/build/{job_id}/cancel", headers=logged_in_headers)
        assert cancel_response.status_code == codes.OK

        # Verify the response structure indicates failure
        response_data = cancel_response.json()
        assert "success" in response_data
        assert "message" in response_data
        assert response_data["success"] is False
        assert "Failed to cancel" in response_data["message"]
    finally:
        # Restore the original function to avoid affecting other tests
        monkeypatch.setattr(langinfra.api.v1.chat, "cancel_flow_build", original_cancel_flow_build)


@pytest.mark.benchmark
async def test_cancel_build_with_cancelled_error(client, json_memory_chatbot_no_llm, logged_in_headers, monkeypatch):
    """Test handling of CancelledError during cancellation (should be treated as failure)."""
    # First create the flow
    flow_id = await create_flow(client, json_memory_chatbot_no_llm, logged_in_headers)

    # Start the build and get job_id
    build_response = await build_flow(client, flow_id, logged_in_headers)
    job_id = build_response["job_id"]
    assert job_id is not None

    # Mock the cancel_flow_build function to raise CancelledError
    import asyncio

    import langinfra.api.v1.chat

    original_cancel_flow_build = langinfra.api.v1.chat.cancel_flow_build

    async def mock_cancel_flow_build_with_cancelled_error(*_args, **_kwargs):
        msg = "Task cancellation failed"
        raise asyncio.CancelledError(msg)

    monkeypatch.setattr(langinfra.api.v1.chat, "cancel_flow_build", mock_cancel_flow_build_with_cancelled_error)

    try:
        # Try to cancel the build - should return failure when CancelledError is raised
        # since our implementation treats CancelledError as a failed cancellation
        cancel_response = await client.post(f"api/v1/build/{job_id}/cancel", headers=logged_in_headers)
        assert cancel_response.status_code == codes.OK

        # Verify the response structure indicates failure
        response_data = cancel_response.json()
        assert "success" in response_data
        assert "message" in response_data
        assert response_data["success"] is False
        assert "failed to cancel" in response_data["message"].lower()
    finally:
        # Restore the original function to avoid affecting other tests
        monkeypatch.setattr(langinfra.api.v1.chat, "cancel_flow_build", original_cancel_flow_build)
