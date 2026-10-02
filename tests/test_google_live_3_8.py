"""Model-specific Gemini 3.8 Live protocol and lifecycle regressions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config import GoogleProviderConfig
from src.providers.google_live import GoogleLiveProvider
from src.tools.context import ToolExecutionContext
from src.tools.base import (
    ToolCategory, ToolDefinition, ToolExecutionBehavior, ToolResponseScheduling,
)
from src.tools.telephony.check_extension_status import CheckExtensionStatusTool


@pytest.mark.parametrize("model,enabled,expected", [
    ("gemini-3.8-live", True, True),
    ("models/gemini-3.8-live", True, True),
    ("gemini-3.8-live", False, False),
    ("gemini-live-2.5-flash-native-audio", True, False),
])
def test_full_duplex_barge_in_is_3_8_only_and_can_be_rolled_back(model, enabled, expected):
    provider = GoogleLiveProvider(
        config=GoogleProviderConfig(llm_model=model, full_duplex_barge_in_3_8=enabled),
        on_event=lambda event: None,
    )
    assert provider.uses_full_duplex_barge_in() is expected


def test_tool_policy_defaults_blocking_and_status_check_is_explicitly_non_blocking():
    assert ToolDefinition(name="write_record", description="", category=ToolCategory.BUSINESS).execution_behavior == ToolExecutionBehavior.BLOCKING
    assert CheckExtensionStatusTool().definition.execution_behavior == ToolExecutionBehavior.NON_BLOCKING


@pytest.mark.asyncio
@pytest.mark.parametrize("model,use_vertex,audio_active,expect_prompt", [
    ("gemini-3.8-live", True, True, False),
    ("gemini-3.8-live", False, True, False),
    ("gemini-3.8-live", True, False, True),
    ("gemini-live-2.5-flash-native-audio", True, True, True),
])
async def test_hangup_tool_preserves_active_3_8_farewell_without_changing_legacy_prompt(
    monkeypatch, model, use_vertex, audio_active, expect_prompt,
):
    events = AsyncMock()
    provider = GoogleLiveProvider(
        config=GoogleProviderConfig(llm_model=model, use_vertex_ai=use_vertex),
        on_event=events,
    )
    provider._call_id = "call-farewell"
    provider._allowed_tools = ["hangup_call"]
    provider._in_audio_burst = audio_active
    provider._turn_has_assistant_output = audio_active
    provider._output_transcription_buffer = "Thanks for calling! Have a great day!" if audio_active else ""
    sent = []

    async def capture(payload):
        sent.append(payload)
        if model == "gemini-3.8-live" and audio_active and "toolResponse" in payload:
            # The provider can begin its post-tool continuation before the
            # send await returns; it must already be caller-muted.
            await provider._handle_audio_output("AA==")
        return True

    monkeypatch.setattr(provider, "_send_message", capture)
    monkeypatch.setattr(provider, "_ensure_hangup_fallback_watchdog", AsyncMock())
    monkeypatch.setattr(provider._tool_adapter, "execute_tool", AsyncMock(return_value={
        "status": "success", "will_hangup": True, "message": "Have a great day!",
    }))
    monkeypatch.setattr(provider, "_track_conversation_message", AsyncMock())
    monkeypatch.setattr(ToolExecutionContext, "get_tool_block_response", AsyncMock(return_value=None))
    monkeypatch.setattr("src.providers.google_live.record_in_call_tool_result", AsyncMock())

    await provider._handle_tool_call({"toolCall": {"functionCalls": [
        {"id": "fc-hangup", "name": "hangup_call", "args": {"farewell_message": "Have a great day!"}}
    ]}})

    assert len(sent) == (2 if expect_prompt else 1)
    assert "toolResponse" in sent[0]
    if expect_prompt:
        assert "clientContent" in sent[1]
    else:
        assert provider._terminal_audio_cutoff_after_tool is True
        assert provider._force_farewell_sent is False
        response = sent[0]["toolResponse"]["functionResponses"][0]["response"]
        assert "do not speak again" in response["message"]
        assert "instruction" not in response
        assert [call.args[0]["type"] for call in events.await_args_list] == [
            "AgentAudioDone", "HangupReady",
        ]
        assert provider._hangup_after_response is False
        assert provider._last_final_assistant_text == "Thanks for calling! Have a great day!"
        await provider._handle_server_content({"serverContent": {
            "outputTranscription": {"text": "The call has been disconnected."},
            "modelTurn": {"parts": [{"inlineData": {
                "mimeType": "audio/pcm;rate=24000", "data": "AA==",
            }}]},
        }})
        assert provider._output_transcription_buffer == ""
        assert len(events.await_args_list) == 2


@pytest.mark.asyncio
async def test_3_8_uses_shared_tool_policy_for_declaration_and_result(monkeypatch):
    provider = GoogleLiveProvider(
        config=GoogleProviderConfig(llm_model="gemini-3.8-live"),
        on_event=lambda event: None,
    )
    provider._call_id = "call-policy"
    definition = ToolDefinition(
        name="readonly_lookup", description="", category=ToolCategory.BUSINESS,
        execution_behavior=ToolExecutionBehavior.NON_BLOCKING,
        response_scheduling=ToolResponseScheduling.SILENT,
    )
    monkeypatch.setattr(provider._tool_adapter.registry, "get", lambda name: SimpleNamespace(definition=definition) if name == "readonly_lookup" else None)
    monkeypatch.setattr(provider._tool_adapter, "format_tools", lambda names: [{"functionDeclarations": [{"name": "readonly_lookup"}]}])
    sent = []

    async def capture(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(provider, "_send_message", capture)
    await provider._send_setup({"tools": ["readonly_lookup"]})
    assert sent[0]["setup"]["tools"][0]["functionDeclarations"][0]["behavior"] == "NON_BLOCKING"

    monkeypatch.setattr(ToolExecutionContext, "get_tool_block_response", AsyncMock(return_value={"status": "success"}))
    await provider._handle_tool_call({"toolCall": {"functionCalls": [
        {"id": "fc-policy", "name": "readonly_lookup", "args": {}}
    ]}})
    assert sent[-1]["toolResponse"]["functionResponses"][0]["response"]["scheduling"] == "SILENT"


@pytest.mark.asyncio
@pytest.mark.parametrize("use_vertex", [False, True])
async def test_3_8_setup_is_audio_only_and_tools_are_blocking(monkeypatch, use_vertex):
    config = GoogleProviderConfig(
        llm_model="gemini-3.8-live", use_vertex_ai=use_vertex,
        vertex_project="test-project", response_modalities="audio_text",
    )
    provider = GoogleLiveProvider(config=config, on_event=lambda event: None)
    provider._call_id = "call-1"
    sent = []

    async def capture(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(provider, "_send_message", capture)
    monkeypatch.setattr(provider._tool_adapter, "format_tools", lambda names: [
        {"functionDeclarations": [{"name": "hangup_call"}, {"name": "check_extension_status"}]}
    ])
    await provider._send_setup({"tools": ["hangup_call", "check_extension_status"]})

    setup = sent[0]["setup"]
    prefix = "projects/test-project/locations/us-central1/publishers/google/models/" if use_vertex else "models/"
    assert setup["model"] == prefix + "gemini-3.8-live"
    assert setup["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert setup["tools"][0]["functionDeclarations"][0]["behavior"] == "BLOCKING"
    assert setup["tools"][0]["functionDeclarations"][1]["behavior"] == "NON_BLOCKING"


@pytest.mark.asyncio
@pytest.mark.parametrize("model,use_vertex,expects_id", [
    ("gemini-3.8-live", False, True),
    ("gemini-3.8-live", True, True),
    ("gemini-live-2.5-flash-native-audio", True, False),
])
async def test_tool_response_id_matches_model_protocol(monkeypatch, model, use_vertex, expects_id):
    provider = GoogleLiveProvider(
        config=GoogleProviderConfig(llm_model=model, use_vertex_ai=use_vertex),
        on_event=lambda event: None,
    )
    provider._call_id = "call-1"
    sent = []

    async def capture(payload):
        sent.append(payload)
        return True

    async def blocked(self, tool_name):
        return {"status": "error", "message": "Not allowed in this test"}

    monkeypatch.setattr(provider, "_send_message", capture)
    monkeypatch.setattr(ToolExecutionContext, "get_tool_block_response", blocked)
    await provider._handle_tool_call({"toolCall": {"functionCalls": [
        {"id": "fc-1", "name": "check_extension_status", "args": {"extension": "100"}}
    ]}})

    response = sent[0]["toolResponse"]["functionResponses"][0]
    assert response.get("id") == ("fc-1" if expects_id else None)
    assert response["name"] == "check_extension_status"
    if model == "gemini-3.8-live":
        assert response["response"]["scheduling"] == "WHEN_IDLE"
        assert response["response"]["retryable"] is False
    else:
        assert "scheduling" not in response["response"]


@pytest.mark.asyncio
async def test_3_8_cancellation_reaches_in_flight_tool_without_blocking_receive(monkeypatch):
    provider = GoogleLiveProvider(
        config=GoogleProviderConfig(llm_model="gemini-3.8-live"),
        on_event=lambda event: None,
    )
    provider._call_id = "call-1"
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def running_tool(data):
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(provider, "_handle_tool_call", running_tool)
    await provider._handle_server_message({"toolCall": {"functionCalls": [
        {"id": "fc-1", "name": "check_extension_status", "args": {}}
    ]}})
    await asyncio.wait_for(started.wait(), 1)
    await provider._handle_server_message({"toolCallCancellation": {"ids": ["fc-1"]}})
    await asyncio.wait_for(cancelled.wait(), 1)
    await asyncio.sleep(0)
    assert provider._tool_call_tasks == {}


@pytest.mark.asyncio
async def test_3_8_does_not_cancel_active_call_state_tool_mid_action(monkeypatch):
    provider = GoogleLiveProvider(
        config=GoogleProviderConfig(llm_model="gemini-3.8-live"),
        on_event=lambda event: None,
    )
    provider._call_id = "call-1"
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def running_tool(data):
        provider._active_tool_call_ids.add("fc-1")
        started.set()
        await release.wait()
        completed.set()

    monkeypatch.setattr(provider, "_handle_tool_call", running_tool)
    await provider._handle_server_message({"toolCall": {"functionCalls": [
        {"id": "fc-1", "name": "attended_transfer", "args": {}}
    ]}})
    await asyncio.wait_for(started.wait(), 1)
    await provider._handle_server_message({"toolCallCancellation": {"ids": ["fc-1"]}})
    assert not completed.is_set()
    assert not provider._tool_call_tasks["fc-1"].cancelled()
    release.set()
    await asyncio.wait_for(completed.wait(), 1)
    await asyncio.sleep(0)
    assert provider._tool_call_tasks == {}


@pytest.mark.asyncio
async def test_3_8_cancellation_skips_queued_blocking_tool_and_duplicate_id(monkeypatch):
    provider = GoogleLiveProvider(
        config=GoogleProviderConfig(llm_model="gemini-3.8-live"),
        on_event=lambda event: None,
    )
    provider._call_id = "call-queued"
    started = asyncio.Event()
    release = asyncio.Event()
    executed = []

    async def run_tool(data):
        call_id = data["toolCall"]["functionCalls"][0]["id"]
        executed.append(call_id)
        if call_id == "fc-first":
            started.set()
            await release.wait()

    monkeypatch.setattr(provider, "_handle_tool_call", run_tool)
    await provider._handle_server_message({"toolCall": {"functionCalls": [
        {"id": "fc-first", "name": "attended_transfer", "args": {}},
        {"id": "fc-second", "name": "hangup_call", "args": {}},
    ]}})
    await asyncio.wait_for(started.wait(), 1)
    await provider._handle_server_message({"toolCallCancellation": {"ids": ["fc-second"]}})
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert executed == ["fc-first"]
    await provider._handle_server_message({"toolCall": {"functionCalls": [
        {"id": "fc-first", "name": "attended_transfer", "args": {}}
    ]}})
    await asyncio.sleep(0)
    assert executed == ["fc-first"]


@pytest.mark.asyncio
async def test_3_8_teardown_preserves_active_mutation_and_suppresses_late_reply(monkeypatch):
    provider = GoogleLiveProvider(
        config=GoogleProviderConfig(llm_model="gemini-3.8-live"),
        on_event=lambda event: None,
    )
    provider._call_id = "call-state"
    provider._allowed_tools = ["attended_transfer"]
    provider.TOOL_DRAIN_GRACE_SEC = 0.01
    started = asyncio.Event()
    release = asyncio.Event()
    cancelled = asyncio.Event()
    sent = AsyncMock(return_value=True)
    recorded = AsyncMock()

    async def execute(_name, _args, _context):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {"status": "success"}

    monkeypatch.setattr(provider._tool_adapter, "execute_tool", execute)
    monkeypatch.setattr(ToolExecutionContext, "get_tool_block_response", AsyncMock(return_value=None))
    monkeypatch.setattr(provider, "_send_message", sent)
    monkeypatch.setattr("src.providers.google_live.record_in_call_tool_result", recorded)
    await provider._handle_server_message({"toolCall": {"functionCalls": [
        {"id": "fc-transfer", "name": "attended_transfer", "args": {}}
    ]}})
    await asyncio.wait_for(started.wait(), 1)
    await provider.stop_session()
    assert not cancelled.is_set()
    assert provider._call_id is None
    assert len(provider._detached_tool_tasks) == 1
    release.set()
    await asyncio.wait_for(next(iter(provider._detached_tool_tasks)), 1)
    await asyncio.sleep(0)
    assert recorded.await_args.kwargs["call_id"] == "call-state"
    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_3_8_teardown_cancels_tool_before_mutation_starts(monkeypatch):
    provider = GoogleLiveProvider(
        config=GoogleProviderConfig(llm_model="gemini-3.8-live"),
        on_event=lambda event: None,
    )
    provider._call_id = "call-before-execution"
    provider._allowed_tools = ["attended_transfer"]
    checking = asyncio.Event()
    cancelled = asyncio.Event()
    execute = AsyncMock(return_value={"status": "success"})

    async def slow_guard(_self, _name):
        checking.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(ToolExecutionContext, "get_tool_block_response", slow_guard)
    monkeypatch.setattr(provider._tool_adapter, "execute_tool", execute)
    await provider._handle_server_message({"toolCall": {"functionCalls": [
        {"id": "fc-transfer", "name": "attended_transfer", "args": {}}
    ]}})
    await asyncio.wait_for(checking.wait(), 1)
    await provider.stop_session()
    assert cancelled.is_set()
    execute.assert_not_awaited()
