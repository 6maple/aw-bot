import asyncio
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
import unittest

from c_auto_bridge.agent.opencode_server import (
    OpenCodeEventRouter,
    OpenCodeQuestionCapability,
    OpenCodeServerAdapter,
)
from c_auto_bridge.agent.opencode_translator import translate_opencode_event
from c_auto_bridge.config_opencode import OpenCodeConfig
from c_auto_bridge.core.agent_events import (
    ApprovalRequested,
    RunCompleted,
    RunFailed,
    TextDelta,
    ToolFinished,
    ToolStarted,
    ThinkingDelta,
    UserInputRequested,
)
from c_auto_bridge.core.agent_session import AgentSession, Workspace
from c_auto_bridge.core.attachments import Attachment
from c_auto_bridge.store.file_store import FileStore


class OpenCodeTranslatorTest(unittest.TestCase):
    def test_ignores_global_events_without_session_id(self) -> None:
        self.assertIsNone(
            translate_opencode_event(
                {"type": "server.connected", "properties": {"version": "1.0.0"}}
            )
        )

    def test_translates_text_approval_and_completion(self) -> None:
        cases = [
            (
                {"type": "message.part.delta", "properties": {"sessionID": "s", "messageID": "m", "delta": "hi"}},
                TextDelta("hi"),
            ),
            (
                {
                    "type": "session.next.text.delta",
                    "properties": {
                        "timestamp": 1,
                        "sessionID": "s",
                        "assistantMessageID": "m_assistant",
                        "textID": "text_1",
                        "delta": "hi",
                    },
                },
                TextDelta("hi"),
            ),
            (
                {
                    "type": "session.next.reasoning.delta",
                    "properties": {
                        "timestamp": 1,
                        "sessionID": "s",
                        "assistantMessageID": "m_assistant",
                        "reasoningID": "reasoning_1",
                        "delta": "thinking",
                    },
                },
                ThinkingDelta("thinking"),
            ),
            (
                {"type": "permission.asked", "properties": {"sessionID": "s", "id": "p", "permission": "shell"}},
                ApprovalRequested("p", "shell", {"sessionID": "s", "id": "p", "permission": "shell"}),
            ),
            (
                {"type": "session.turn.close", "properties": {"sessionID": "s"}},
                RunCompleted(),
            ),
        ]
        for raw, expected in cases:
            self.assertEqual(translate_opencode_event(raw).event, expected)

    def test_translates_session_idle_to_completion(self) -> None:
        self.assertEqual(
            translate_opencode_event(
                {"type": "session.idle", "properties": {"sessionID": "s"}}
            ).event,
            RunCompleted(),
        )
        self.assertEqual(
            translate_opencode_event(
                {"type": "session.status", "properties": {"sessionID": "s", "status": {"type": "idle"}}}
            ).event,
            RunCompleted(),
        )
        self.assertIsNone(
            translate_opencode_event(
                {"type": "session.status", "properties": {"sessionID": "s", "status": {"type": "busy"}}}
            )
        )

    def test_separates_reasoning_and_ignores_part_updates(self) -> None:
        self.assertEqual(
            translate_opencode_event(
                {
                    "type": "message.part.delta",
                    "properties": {
                        "sessionID": "s",
                        "messageID": "m",
                        "delta": "thinking",
                        "part": {"type": "reasoning"},
                    },
                }
            ).event,
            ThinkingDelta("thinking"),
        )
        self.assertIsNone(
            translate_opencode_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "messageID": "m",
                        "part": {"type": "reasoning", "text": "thinking"},
                    },
                }
            )
        )
        self.assertEqual(
            translate_opencode_event(
                {
                    "type": "message.part.delta",
                    "properties": {
                        "sessionID": "s",
                        "messageID": "m",
                        "field": "reasoning",
                        "delta": "thinking",
                    },
                }
            ).event,
            ThinkingDelta("thinking"),
        )

    def test_translates_updated_text_delta(self) -> None:
        self.assertEqual(
            translate_opencode_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "delta": "final",
                        "part": {"sessionID": "s", "messageID": "m", "type": "text"},
                    },
                }
            ).event,
            TextDelta("final"),
        )

    def test_translates_running_tool_part_snapshot(self) -> None:
        self.assertEqual(
            translate_opencode_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {
                            "id": "part_tool",
                            "sessionID": "s",
                            "messageID": "m",
                            "type": "tool",
                            "callID": "call_tool",
                            "tool": "bash",
                            "state": {
                                "status": "running",
                                "input": {"command": "pytest"},
                            },
                        },
                    },
                }
            ).event,
            ToolStarted("part_tool", "bash", {"command": "pytest"}),
        )

    def test_translates_completed_tool_part_snapshot(self) -> None:
        self.assertEqual(
            translate_opencode_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {
                            "id": "part_tool",
                            "sessionID": "s",
                            "messageID": "m",
                            "type": "tool",
                            "callID": "call_tool",
                            "tool": "bash",
                            "state": {
                                "status": "completed",
                                "input": {"command": "pytest"},
                                "output": "passed",
                            },
                        },
                    },
                }
            ).event,
            ToolFinished("part_tool", "passed", False),
        )

    def test_translates_error_tool_part_snapshot(self) -> None:
        self.assertEqual(
            translate_opencode_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {
                            "id": "part_tool",
                            "sessionID": "s",
                            "messageID": "m",
                            "type": "tool",
                            "callID": "call_tool",
                            "tool": "bash",
                            "state": {
                                "status": "error",
                                "input": {"command": "pytest"},
                                "error": "failed",
                            },
                        },
                    },
                }
            ).event,
            ToolFinished("part_tool", "failed", True),
        )

    def test_turn_ignores_unbound_permission_request(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")

            payload = {
                "sessionID": "s",
                "id": "perm_1",
                "permission": "shell",
                "command": "git status",
            }
            await router.handle_event({"type": "permission.asked", "properties": payload})

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        asyncio.run(run())

    def test_turn_ignores_permission_requests_for_unrelated_sessions(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s_active", "m_user")

            await router.handle_event(
                {
                    "type": "permission.asked",
                    "properties": {
                        "sessionID": "s_other",
                        "id": "perm_1",
                        "permission": "shell",
                    },
                }
            )

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        asyncio.run(run())

    def test_turn_ignores_same_session_permission_for_unrelated_assistant_tool(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")

            await router.handle_event(
                {
                    "type": "message.updated",
                    "properties": {
                        "info": {
                            "id": "m_active_assistant",
                            "sessionID": "s",
                            "role": "assistant",
                            "parentID": "m_user",
                        }
                    },
                }
            )
            await router.handle_event(
                {
                    "type": "permission.asked",
                    "properties": {
                        "sessionID": "s",
                        "id": "perm_1",
                        "permission": "shell",
                        "tool": {"messageID": "m_other_assistant", "callID": "call_1"},
                    },
                }
            )

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        asyncio.run(run())

    def test_turn_routes_permission_for_bound_assistant_tool(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")

            await router.handle_event(
                {
                    "type": "message.updated",
                    "properties": {
                        "info": {
                            "id": "m_active_assistant",
                            "sessionID": "s",
                            "role": "assistant",
                            "parentID": "m_user",
                        }
                    },
                }
            )
            payload = {
                "sessionID": "s",
                "id": "perm_1",
                "permission": "shell",
                "tool": {"messageID": "m_active_assistant", "callID": "call_1"},
            }
            await router.handle_event({"type": "permission.asked", "properties": payload})

            self.assertEqual(
                await asyncio.wait_for(queue.get(), timeout=0.1),
                ApprovalRequested("perm_1", "shell", payload),
            )

        asyncio.run(run())

    def test_turn_routes_permission_for_active_user_message(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")

            payload = {
                "sessionID": "s",
                "messageID": "m_user",
                "id": "perm_1",
                "permission": "shell",
                "command": "git status",
            }
            await router.handle_event({"type": "permission.asked", "properties": payload})

            self.assertEqual(
                await asyncio.wait_for(queue.get(), timeout=0.1),
                ApprovalRequested("perm_1", "shell", payload),
            )

        asyncio.run(run())

    def test_turn_replays_early_permission_only_after_assistant_binds_to_active_turn(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")
            payload = {
                "sessionID": "s",
                "id": "perm_1",
                "permission": "shell",
                "tool": {"messageID": "m_active_assistant", "callID": "call_1"},
            }

            await router.handle_event({"type": "permission.asked", "properties": payload})
            await router.handle_event(
                {
                    "type": "message.updated",
                    "properties": {
                        "info": {
                            "id": "m_other_assistant",
                            "sessionID": "s",
                            "role": "assistant",
                            "parentID": "m_other_user",
                        }
                    },
                }
            )
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

            await router.handle_event(
                {
                    "type": "message.updated",
                    "properties": {
                        "info": {
                            "id": "m_active_assistant",
                            "sessionID": "s",
                            "role": "assistant",
                            "parentID": "m_user",
                        }
                    },
                }
            )

            self.assertEqual(
                await asyncio.wait_for(queue.get(), timeout=0.1),
                ApprovalRequested("perm_1", "shell", payload),
            )

        asyncio.run(run())

    def test_router_uses_message_role_and_part_type_context(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m")

            await router.handle_event(
                {"type": "message.updated", "properties": {"info": {"id": "m", "sessionID": "s", "role": "user"}}}
            )
            await router.handle_event(
                {"type": "message.part.delta", "properties": {"sessionID": "s", "messageID": "m", "delta": "prompt"}}
            )
            self.assertTrue(queue.empty())

            await router.handle_event(
                {
                    "type": "message.updated",
                    "properties": {
                        "info": {"id": "m_assistant", "sessionID": "s", "role": "assistant", "parentID": "m"}
                    },
                }
            )
            await router.handle_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {"id": "p1", "sessionID": "s", "messageID": "m_assistant", "type": "reasoning"}
                    },
                }
            )
            await router.handle_event(
                {
                    "type": "message.part.delta",
                    "properties": {"sessionID": "s", "messageID": "m_assistant", "partID": "p1", "field": "text", "delta": "think"},
                }
            )
            self.assertEqual(await queue.get(), ThinkingDelta("think"))

            await router.handle_event(
                {"type": "message.part.delta", "properties": {"sessionID": "s", "messageID": "m_assistant", "delta": "answer"}}
            )
            self.assertEqual(await asyncio.wait_for(queue.get(), timeout=0.1), TextDelta("answer"))
            await router.handle_event(
                {
                    "type": "session.next.text.delta",
                    "properties": {
                        "timestamp": 1,
                        "sessionID": "s",
                        "assistantMessageID": "m_assistant",
                        "textID": "text_1",
                        "delta": "v2 answer",
                    },
                }
            )
            self.assertEqual(await asyncio.wait_for(queue.get(), timeout=0.1), TextDelta("v2 answer"))

        asyncio.run(run())

    def test_router_converts_official_part_update_snapshots_to_deltas(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m")

            await router.handle_event(
                {"type": "message.updated", "properties": {"info": {"id": "m", "sessionID": "s", "role": "assistant"}}}
            )
            await router.handle_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {"id": "p1", "sessionID": "s", "messageID": "m", "type": "text", "text": "Hel"},
                        "time": 1,
                    },
                }
            )
            self.assertEqual(await asyncio.wait_for(queue.get(), timeout=0.1), TextDelta("Hel"))

            await router.handle_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {"id": "p1", "sessionID": "s", "messageID": "m", "type": "text", "text": "Hello"},
                        "time": 2,
                    },
                }
            )
            self.assertEqual(await asyncio.wait_for(queue.get(), timeout=0.1), TextDelta("lo"))

            await router.handle_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {"id": "p1", "sessionID": "s", "messageID": "m", "type": "text", "text": "Hello"},
                        "time": 3,
                    },
                }
            )
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        asyncio.run(run())

    def test_router_suppresses_part_update_snapshot_already_seen_as_delta(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m")

            await router.handle_event(
                {"type": "message.updated", "properties": {"info": {"id": "m", "sessionID": "s", "role": "assistant"}}}
            )
            await router.handle_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {"id": "p_reason", "sessionID": "s", "messageID": "m", "type": "reasoning"},
                    },
                }
            )
            await router.handle_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {"id": "p_text", "sessionID": "s", "messageID": "m", "type": "text"},
                    },
                }
            )
            await router.handle_event(
                {
                    "type": "message.part.delta",
                    "properties": {
                        "sessionID": "s",
                        "messageID": "m",
                        "partID": "p_reason",
                        "delta": "thinking",
                    },
                }
            )
            self.assertEqual(await asyncio.wait_for(queue.get(), timeout=0.1), ThinkingDelta("thinking"))
            await router.handle_event(
                {
                    "type": "message.part.delta",
                    "properties": {
                        "sessionID": "s",
                        "messageID": "m",
                        "partID": "p_text",
                        "delta": "final",
                    },
                }
            )
            self.assertEqual(await asyncio.wait_for(queue.get(), timeout=0.1), TextDelta("final"))

            await router.handle_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {
                            "id": "p_reason",
                            "sessionID": "s",
                            "messageID": "m",
                            "type": "reasoning",
                            "text": "thinking",
                        },
                    },
                }
            )
            await router.handle_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {
                            "id": "p_text",
                            "sessionID": "s",
                            "messageID": "m",
                            "type": "text",
                            "text": "final",
                        },
                    },
                }
            )

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        asyncio.run(run())

    def test_router_suppresses_duplicate_tool_part_snapshot_states(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m")

            await router.handle_event(
                {"type": "message.updated", "properties": {"info": {"id": "m", "sessionID": "s", "role": "assistant"}}}
            )
            running = {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": "s",
                    "part": {
                        "id": "part_tool",
                        "sessionID": "s",
                        "messageID": "m",
                        "type": "tool",
                        "callID": "call_tool",
                        "tool": "bash",
                        "state": {
                            "status": "running",
                            "input": {"command": "pytest"},
                        },
                    },
                },
            }

            await router.handle_event(running)
            self.assertEqual(
                await asyncio.wait_for(queue.get(), timeout=0.1),
                ToolStarted("part_tool", "bash", {"command": "pytest"}),
            )
            await router.handle_event(running)
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

            await router.handle_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {
                            "id": "part_tool",
                            "sessionID": "s",
                            "messageID": "m",
                            "type": "tool",
                            "callID": "call_tool",
                            "tool": "bash",
                            "state": {
                                "status": "completed",
                                "input": {"command": "pytest"},
                                "output": "passed",
                            },
                        },
                    },
                }
            )
            self.assertEqual(
                await asyncio.wait_for(queue.get(), timeout=0.1),
                ToolFinished("part_tool", "passed", False),
            )

        asyncio.run(run())

    def test_router_ignores_pending_tool_part_snapshot(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m")

            await router.handle_event(
                {"type": "message.updated", "properties": {"info": {"id": "m", "sessionID": "s", "role": "assistant"}}}
            )
            await router.handle_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {
                            "id": "part_tool",
                            "sessionID": "s",
                            "messageID": "m",
                            "type": "tool",
                            "callID": "call_tool",
                            "tool": "bash",
                            "state": {
                                "status": "pending",
                                "input": {"command": "pytest"},
                                "raw": "{\"command\":\"pytest\"}",
                            },
                        },
                    },
                }
            )

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        asyncio.run(run())

    def test_router_logs_and_suppresses_non_append_part_snapshots(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m")

            await router.handle_event(
                {"type": "message.updated", "properties": {"info": {"id": "m", "sessionID": "s", "role": "assistant"}}}
            )
            await router.handle_event(
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "s",
                        "part": {"id": "p1", "sessionID": "s", "messageID": "m", "type": "text", "text": "Hello"},
                        "time": 1,
                    },
                }
            )
            self.assertEqual(await asyncio.wait_for(queue.get(), timeout=0.1), TextDelta("Hello"))

            with self.assertLogs("c_auto_bridge.agent.opencode_server", level="WARNING") as logs:
                await router.handle_event(
                    {
                        "type": "message.part.updated",
                        "properties": {
                            "sessionID": "s",
                            "part": {"id": "p1", "sessionID": "s", "messageID": "m", "type": "text", "text": "Help"},
                            "time": 2,
                        },
                    }
                )
            self.assertEqual(logs.records[-1].levelname, "WARNING")
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        asyncio.run(run())

    def test_register_keeps_early_text_for_current_message_unless_role_is_user(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            await router.handle_event(
                {
                    "type": "message.updated",
                    "properties": {"info": {"id": "msg_assistant", "sessionID": "s", "role": "assistant", "parentID": "m"}},
                }
            )
            await router.handle_event(
                {"type": "message.part.delta", "properties": {"sessionID": "s", "messageID": "msg_assistant", "delta": "answer"}}
            )

            queue = router.register("s", "m")

            self.assertEqual(await asyncio.wait_for(queue.get(), timeout=0.1), TextDelta("answer"))

        asyncio.run(run())

    def test_turn_ignores_session_completion_until_current_assistant_activity_exists(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            with TemporaryDirectory() as tmpdir:
                client = FakeClient()
                adapter = OpenCodeServerAdapter(
                    config=_config(), store=FileStore(tmpdir), client=client,
                    event_router=router,
                    clock=lambda: datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix")
                events = agent_run.events

                await router.handle_event(
                    {"type": "session.idle", "properties": {"sessionID": "oc_1"}}
                )
                pending_next = asyncio.create_task(anext(events))
                await asyncio.sleep(0)
                self.assertFalse(pending_next.done())

                await router.handle_event(
                    {
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": "msg_assistant",
                                "sessionID": "oc_1",
                                "role": "assistant",
                                "parentID": client.message_id,
                            },
                        },
                    }
                )
                await router.handle_event(
                    {
                        "type": "session.next.text.delta",
                        "properties": {
                            "timestamp": 1,
                            "sessionID": "oc_1",
                            "assistantMessageID": "msg_assistant",
                            "textID": "text_1",
                            "delta": "answer",
                        },
                    }
                )
                await router.handle_event(
                    {"type": "session.idle", "properties": {"sessionID": "oc_1"}}
                )
                self.assertEqual(await asyncio.wait_for(pending_next, timeout=0.1), TextDelta("answer"))
                self.assertEqual(await asyncio.wait_for(anext(events), timeout=0.1), RunCompleted())

        asyncio.run(run())

    def test_turn_ignores_completion_without_current_assistant_output(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            with TemporaryDirectory() as tmpdir:
                client = FakeClient()
                adapter = OpenCodeServerAdapter(
                    config=_config(), store=FileStore(tmpdir), client=client,
                    event_router=router,
                    clock=lambda: datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="hi")
                client.messages = [
                    {
                        "info": {
                            "id": client.message_id,
                            "sessionID": "oc_1",
                            "role": "user",
                        },
                        "parts": [],
                    }
                ]

                await router.handle_event(
                    {"type": "session.idle", "properties": {"sessionID": "oc_1"}}
                )

                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(anext(agent_run.events), timeout=0.05)

        asyncio.run(run())

    def test_start_turn_uses_message_id_after_existing_opencode_assistant_id(self) -> None:
        async def run() -> None:
            with TemporaryDirectory() as tmpdir:
                client = FakeClient()
                adapter = OpenCodeServerAdapter(
                    config=_config(),
                    store=FileStore(tmpdir),
                    client=client,
                    clock=lambda: datetime(2026, 6, 7, 16, 49, 13, 505720, tzinfo=timezone.utc),
                )

                await adapter.start_turn(agent_session=_session(), prompt="hi")

            self.assertGreater(client.message_id, "msg_ea133c87c001DYV2kTDJnLkko2")

        asyncio.run(run())

    def test_turn_completion_backfills_assistant_message_snapshot(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            with TemporaryDirectory() as tmpdir:
                client = FakeClient()
                adapter = OpenCodeServerAdapter(
                    config=_config(), store=FileStore(tmpdir), client=client,
                    event_router=router,
                    clock=lambda: datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix")
                client.messages = [
                    {
                        "info": {
                            "id": "msg_assistant",
                            "sessionID": "oc_1",
                            "role": "assistant",
                            "parentID": client.message_id,
                        },
                        "parts": [
                            {
                                "id": "p_reason",
                                "sessionID": "oc_1",
                                "messageID": "msg_assistant",
                                "type": "reasoning",
                                "text": "thinking",
                            },
                            {
                                "id": "p_text",
                                "sessionID": "oc_1",
                                "messageID": "msg_assistant",
                                "type": "text",
                                "text": "final",
                            },
                        ],
                    }
                ]

                await router.handle_event(
                    {"type": "session.idle", "properties": {"sessionID": "oc_1"}}
                )
                events = agent_run.events
                self.assertEqual(await anext(events), ThinkingDelta("thinking"))
                self.assertEqual(await anext(events), TextDelta("final"))
                self.assertEqual(await anext(events), RunCompleted())

        asyncio.run(run())

    def test_turn_status_idle_backfills_only_missing_snapshot_suffixes(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            with TemporaryDirectory() as tmpdir:
                client = FakeClient()
                adapter = OpenCodeServerAdapter(
                    config=_config(), store=FileStore(tmpdir), client=client,
                    event_router=router,
                    clock=lambda: datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix")
                events = agent_run.events

                await router.handle_event(
                    {
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": "msg_assistant",
                                "sessionID": "oc_1",
                                "role": "assistant",
                                "parentID": client.message_id,
                            },
                        },
                    }
                )
                await router.handle_event(
                    {
                        "type": "session.next.reasoning.delta",
                        "properties": {
                            "timestamp": 1,
                            "sessionID": "oc_1",
                            "assistantMessageID": "msg_assistant",
                            "reasoningID": "reasoning_1",
                            "delta": "think",
                        },
                    }
                )
                await router.handle_event(
                    {
                        "type": "session.next.text.delta",
                        "properties": {
                            "timestamp": 1,
                            "sessionID": "oc_1",
                            "assistantMessageID": "msg_assistant",
                            "textID": "text_1",
                            "delta": "fi",
                        },
                    }
                )
                self.assertEqual(await anext(events), ThinkingDelta("think"))
                self.assertEqual(await anext(events), TextDelta("fi"))

                client.messages = [
                    {
                        "info": {
                            "id": "msg_assistant",
                            "sessionID": "oc_1",
                            "role": "assistant",
                            "parentID": client.message_id,
                        },
                        "parts": [
                            {
                                "id": "p_reason",
                                "sessionID": "oc_1",
                                "messageID": "msg_assistant",
                                "type": "reasoning",
                                "text": "thinking",
                            },
                            {
                                "id": "p_text",
                                "sessionID": "oc_1",
                                "messageID": "msg_assistant",
                                "type": "text",
                                "text": "final",
                            },
                        ],
                    }
                ]

                await router.handle_event(
                    {
                        "type": "session.status",
                        "properties": {"sessionID": "oc_1", "status": {"type": "idle"}},
                    }
                )
                self.assertEqual(await anext(events), ThinkingDelta("ing"))
                self.assertEqual(await anext(events), TextDelta("nal"))
                self.assertEqual(await anext(events), RunCompleted())

        asyncio.run(run())

    def test_start_turn_binds_output_only_after_assistant_parent_matches_user_message_id(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            with TemporaryDirectory() as tmpdir:
                client = FakeClient()
                adapter = OpenCodeServerAdapter(
                    config=_config(), store=FileStore(tmpdir), client=client,
                    event_router=router,
                    clock=lambda: datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix")
                events = agent_run.events

                await router.handle_event(
                    {
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": "msg_old_assistant",
                                "sessionID": "oc_1",
                                "role": "assistant",
                                "parentID": "msg_old_user",
                            },
                        },
                    }
                )
                await router.handle_event(
                    {
                        "type": "message.part.delta",
                        "properties": {
                            "sessionID": "oc_1",
                            "messageID": "msg_old_assistant",
                            "delta": "old output",
                        },
                    }
                )
                pending = asyncio.create_task(anext(events))
                await asyncio.sleep(0)
                self.assertFalse(pending.done())

                await router.handle_event(
                    {
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": "msg_current_assistant",
                                "sessionID": "oc_1",
                                "role": "assistant",
                                "parentID": client.message_id,
                            },
                        },
                    }
                )
                await router.handle_event(
                    {
                        "type": "message.part.delta",
                        "properties": {
                            "sessionID": "oc_1",
                            "messageID": "msg_current_assistant",
                            "delta": "current output",
                        },
                    }
                )
                self.assertEqual(await asyncio.wait_for(pending, timeout=0.1), TextDelta("current output"))

        asyncio.run(run())

    def test_ignores_question_variants_when_capability_is_absent(self) -> None:
        question = {
            "id": "que_1",
            "sessionID": "s",
            "questions": [
                {"header": "Path", "question": "Which path?", "options": []},
                {"header": "Mode", "question": "Which mode?", "options": []},
            ],
        }
        cases = [
            {"type": "question.asked", "properties": question},
            {"type": "question.v2.asked", "properties": question},
        ]
        for raw in cases:
            self.assertIsNone(translate_opencode_event(raw))

    def test_translates_structured_errors(self) -> None:
        cases = [
            (
                {
                    "type": "session.error",
                    "properties": {
                        "sessionID": "s",
                        "error": {
                            "name": "APIError",
                            "data": {"message": "rate limited", "isRetryable": True},
                        },
                    },
                },
                RunFailed("rate limited"),
            ),
            (
                {
                    "type": "session.error",
                    "properties": {
                        "sessionID": "s",
                        "error": {
                            "name": "MessageOutputLengthError",
                            "data": {},
                        },
                    },
                },
                RunFailed("MessageOutputLengthError"),
            ),
        ]
        for raw, expected in cases:
            self.assertEqual(translate_opencode_event(raw).event, expected)

    def test_question_like_event_without_capability_ignores_unbound_request(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")

            with self.assertLogs("c_auto_bridge.agent.opencode_server", level="DEBUG") as logs:
                await router.handle_event(
                    {
                        "type": "question.asked",
                        "properties": {
                            "id": "que_1",
                            "sessionID": "s",
                            "questions": [
                                {"header": "Path", "question": "Which path?", "options": []},
                            ],
                        },
                    }
                )

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)
            self.assertEqual(logs.records[-1].levelname, "DEBUG")

        asyncio.run(run())

    def test_question_like_event_without_capability_fails_active_message_request(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")

            with self.assertLogs("c_auto_bridge.agent.opencode_server", level="WARNING") as logs:
                await router.handle_event(
                    {
                        "type": "question.asked",
                        "properties": {
                            "id": "que_1",
                            "sessionID": "s",
                            "messageID": "m_user",
                            "questions": [
                                {"header": "Path", "question": "Which path?", "options": []},
                            ],
                        },
                    }
                )

            self.assertEqual(await asyncio.wait_for(queue.get(), timeout=0.1), RunFailed("OpenCode question support is unavailable"))
            self.assertEqual(len(logs.records), 1)

        asyncio.run(run())

    def test_enabled_question_capability_routes_single_free_form_question(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter(question_capability=_question_capability())
            queue = router.register("s", "m_user")

            payload = {
                "id": "que_1",
                "sessionID": "s",
                "questions": [
                    {"header": "Path", "question": "Which path?"},
                ],
                "tool": {"messageID": "m_assistant", "callID": "call_1"},
            }
            await router.handle_event({"type": "question.asked", "properties": payload})
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

            await router.handle_event(
                {
                    "type": "message.updated",
                    "properties": {
                        "info": {
                            "id": "m_assistant",
                            "sessionID": "s",
                            "role": "assistant",
                            "parentID": "m_user",
                        }
                    },
                }
            )

            self.assertEqual(
                await asyncio.wait_for(queue.get(), timeout=0.1),
                UserInputRequested("que_1", "Which path?", payload),
            )

        asyncio.run(run())

    def test_enabled_question_capability_fails_fast_for_unsupported_forms(self) -> None:
        async def run() -> None:
            cases = [
                [
                    {"header": "Path", "question": "Which path?"},
                    {"header": "Mode", "question": "Which mode?"},
                ],
                [{"header": "Path", "question": "Which path?", "multiple": True}],
                [{"header": "Path", "question": "Which path?", "options": [{"label": "src", "description": "source"}]}],
                [{"header": "Path", "question": "Which path?", "custom": True}],
            ]
            for questions in cases:
                router = OpenCodeEventRouter(question_capability=_question_capability())
                queue = router.register("s", "m_user")
                await router.handle_event(
                    {
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": "m_assistant",
                                "sessionID": "s",
                                "role": "assistant",
                                "parentID": "m_user",
                            }
                        },
                    }
                )

                await router.handle_event(
                    {
                        "type": "question.asked",
                        "properties": {
                            "id": "que_1",
                            "sessionID": "s",
                            "questions": questions,
                            "tool": {"messageID": "m_assistant", "callID": "call_1"},
                        },
                    }
                )

                self.assertEqual(
                    await asyncio.wait_for(queue.get(), timeout=0.1),
                    RunFailed("Unsupported OpenCode question request"),
                )

        asyncio.run(run())

    def test_unrelated_unknown_event_is_debug_logged_and_ignored(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s_active", "m_user")

            with self.assertLogs("c_auto_bridge.agent.opencode_server", level="DEBUG") as logs:
                await router.handle_event(
                    {
                        "type": "vendor.mystery",
                        "properties": {
                            "sessionID": "s_other",
                            "messageID": "m_other",
                            "partID": "p_other",
                            "part": {"type": "text"},
                        },
                    }
                )

            ignored = logs.records[-1]
            self.assertEqual(ignored.levelname, "DEBUG")
            self.assertEqual(ignored.event_type, "vendor.mystery")
            self.assertEqual(ignored.session_id, "s_other")
            self.assertEqual(ignored.message_id, "m_other")
            self.assertEqual(ignored.part_id, "p_other")
            self.assertEqual(ignored.part_type, "text")
            self.assertEqual(ignored.active_turn_match, "unrelated")
            self.assertEqual(ignored.handling_result, "ignored")
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        asyncio.run(run())

    def test_active_session_unknown_event_is_warning_logged_and_ignored(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")

            with self.assertLogs("c_auto_bridge.agent.opencode_server", level="WARNING") as logs:
                await router.handle_event(
                    {
                        "type": "vendor.mystery",
                        "properties": {
                            "sessionID": "s",
                            "messageID": "m_other",
                            "partID": "p_other",
                            "part": {"type": "text"},
                        },
                    }
                )

            self.assertEqual(len(logs.records), 1)
            ignored = logs.records[0]
            self.assertEqual(ignored.levelname, "WARNING")
            self.assertEqual(ignored.event_type, "vendor.mystery")
            self.assertEqual(ignored.session_id, "s")
            self.assertEqual(ignored.message_id, "m_other")
            self.assertEqual(ignored.part_id, "p_other")
            self.assertEqual(ignored.part_type, "text")
            self.assertEqual(ignored.active_turn_match, "active_session")
            self.assertEqual(ignored.handling_result, "ignored")
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        asyncio.run(run())

    def test_active_turn_unknown_event_is_warning_logged_and_ignored(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")

            with self.assertLogs("c_auto_bridge.agent.opencode_server", level="WARNING") as logs:
                await router.handle_event(
                    {
                        "type": "session.progress.snapshot",
                        "properties": {
                            "sessionID": "s",
                            "messageID": "m_user",
                            "partID": "p_status",
                            "part": {"type": "status"},
                        },
                    }
                )

            self.assertEqual(len(logs.records), 1)
            ignored = logs.records[0]
            self.assertEqual(ignored.levelname, "WARNING")
            self.assertEqual(ignored.event_type, "session.progress.snapshot")
            self.assertEqual(ignored.session_id, "s")
            self.assertEqual(ignored.message_id, "m_user")
            self.assertEqual(ignored.part_id, "p_status")
            self.assertEqual(ignored.part_type, "status")
            self.assertEqual(ignored.active_turn_match, "active_turn")
            self.assertEqual(ignored.handling_result, "ignored")
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        asyncio.run(run())

    def test_active_turn_unknown_interactive_event_is_warning_logged_and_fails_run(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")

            with self.assertLogs("c_auto_bridge.agent.opencode_server", level="WARNING") as logs:
                await router.handle_event(
                    {
                        "type": "input.requested",
                        "properties": {
                            "sessionID": "s",
                            "messageID": "m_user",
                            "partID": "p_input",
                            "part": {"type": "input"},
                        },
                    }
                )

            self.assertEqual(await asyncio.wait_for(queue.get(), timeout=0.1), RunFailed("Unsupported OpenCode interactive event: input.requested"))
            self.assertEqual(len(logs.records), 1)
            failed = logs.records[0]
            self.assertEqual(failed.levelname, "WARNING")
            self.assertEqual(failed.event_type, "input.requested")
            self.assertEqual(failed.session_id, "s")
            self.assertEqual(failed.message_id, "m_user")
            self.assertEqual(failed.part_id, "p_input")
            self.assertEqual(failed.part_type, "input")
            self.assertEqual(failed.active_turn_match, "active_turn")
            self.assertEqual(failed.handling_result, "run_failed")

        asyncio.run(run())

    def test_stream_interruption_fails_active_turn_with_clear_error(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")

            await router.handle_stream_interruption("OpenCode event stream ended")

            self.assertEqual(
                await asyncio.wait_for(queue.get(), timeout=0.1),
                RunFailed("OpenCode event stream interrupted: OpenCode event stream ended"),
            )

        asyncio.run(run())

    def test_stream_interruption_does_not_fail_inactive_turns(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            queue = router.register("s", "m_user")
            router.unregister("s", "m_user")

            await router.handle_stream_interruption("OpenCode event stream ended")

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        asyncio.run(run())

    def test_start_turn_routes_early_events_and_controls_run(self) -> None:
        async def run() -> None:
            router = OpenCodeEventRouter()
            await router.handle_event(
                {"type": "message.part.delta", "properties": {"sessionID": "oc_1", "messageID": "msg_actual", "delta": "early"}}
            )
            with TemporaryDirectory() as tmpdir:
                client = FakeClient()
                adapter = OpenCodeServerAdapter(
                    config=_config(), store=FileStore(tmpdir), client=client,
                    event_router=router,
                    clock=lambda: datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix")
                events = agent_run.events
                pending = asyncio.create_task(anext(events))
                await asyncio.sleep(0)
                self.assertFalse(pending.done())

                await router.handle_event(
                    {"type": "message.part.delta", "properties": {"sessionID": "oc_2", "messageID": "msg_other", "delta": "ignore me"}}
                )
                await asyncio.sleep(0)
                self.assertFalse(pending.done())

                await router.handle_event(
                    {
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": client.message_id,
                                "sessionID": "oc_1",
                                "role": "user",
                            },
                        },
                    }
                )
                await router.handle_event(
                    {"type": "message.part.delta", "properties": {"sessionID": "oc_1", "messageID": client.message_id, "delta": "echo"}}
                )
                await router.handle_event(
                    {
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": "msg_old_assistant",
                                "sessionID": "oc_1",
                                "role": "assistant",
                                "parentID": "msg_old_user",
                            },
                        },
                    }
                )
                await router.handle_event(
                    {"type": "message.part.delta", "properties": {"sessionID": "oc_1", "messageID": "msg_old_assistant", "delta": "stale"}}
                )
                await asyncio.sleep(0)
                self.assertFalse(pending.done())

                await router.handle_event(
                    {
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": "msg_actual",
                                "sessionID": "oc_1",
                                "role": "assistant",
                                "parentID": client.message_id,
                            },
                        },
                    }
                )
                self.assertEqual(await asyncio.wait_for(pending, timeout=0.1), TextDelta("early"))

                await router.handle_event(
                    {"type": "message.part.delta", "properties": {"sessionID": "oc_1", "messageID": "msg_actual", "delta": "later"}}
                )
                self.assertEqual(await anext(events), TextDelta("later"))
                await router.handle_event(
                    {
                        "type": "message.part.updated",
                        "properties": {
                            "delta": "updated",
                            "part": {
                                "sessionID": "oc_1",
                                "messageID": "msg_actual",
                                "type": "text",
                            },
                        },
                    }
                )
                self.assertEqual(await anext(agent_run.events), TextDelta("updated"))
                await router.handle_event(
                    {
                        "type": "permission.asked",
                        "properties": {
                            "sessionID": "oc_1",
                            "messageID": "msg_actual",
                            "id": "perm_1",
                            "permission": "shell",
                            "command": "git status",
                        },
                    }
                )
                self.assertEqual(
                    await anext(events),
                    ApprovalRequested(
                        "perm_1",
                        "shell",
                        {
                            "sessionID": "oc_1",
                            "messageID": "msg_actual",
                            "id": "perm_1",
                            "permission": "shell",
                            "command": "git status",
                        },
                    ),
                )
                await agent_run.stop()
                await agent_run.answer_approval("perm_1", "allow")
                await router.handle_event(
                    {"type": "session.idle", "properties": {"sessionID": "oc_1"}}
                )
                self.assertEqual(await anext(events), RunCompleted())
            self.assertEqual(
                client.calls,
                [
                    ("prompt", "fix"),
                    "abort",
                    ("permission", "perm_1", "once"),
                ],
            )

        asyncio.run(run())

    def test_turn_reject_maps_to_opencode_reject_and_unsupported_decisions_fail(self) -> None:
        async def run() -> None:
            with TemporaryDirectory() as tmpdir:
                client = FakeClient()
                adapter = OpenCodeServerAdapter(
                    config=_config(),
                    store=FileStore(tmpdir),
                    client=client,
                    clock=lambda: datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix")

                await agent_run.answer_approval("perm_reject", "reject")
                self.assertEqual(client.calls[-1], ("permission", "perm_reject", "reject"))

                for decision in ("remember", "always", "automatic", "approved", "denied"):
                    with self.assertRaises(ValueError):
                        await agent_run.answer_approval("perm_bad", decision)

        asyncio.run(run())

    def test_answer_user_input_fails_fast_when_question_support_is_unavailable(self) -> None:
        async def run() -> None:
            with TemporaryDirectory() as tmpdir:
                client = FakeClient()
                adapter = OpenCodeServerAdapter(
                    config=_config(),
                    store=FileStore(tmpdir),
                    client=client,
                    clock=lambda: datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix")

                with self.assertRaisesRegex(ValueError, "OpenCode question support is unavailable"):
                    await agent_run.answer_user_input("path")

        asyncio.run(run())

    def test_start_turn_rejects_attachments_with_clear_error(self) -> None:
        async def run() -> None:
            with TemporaryDirectory() as tmpdir:
                client = FakeClient()
                adapter = OpenCodeServerAdapter(
                    config=_config(),
                    store=FileStore(tmpdir),
                    client=client,
                    clock=lambda: datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )

                with self.assertRaisesRegex(ValueError, "OpenCode attachments are not supported"):
                    await adapter.start_turn(
                        agent_session=_session(),
                        prompt="fix",
                        attachments=(Attachment(kind="file", path="D:/cache/a.txt", name="a.txt"),),
                    )

                self.assertEqual(client.calls, [])

        asyncio.run(run())

    def test_answer_user_input_maps_single_string_to_opencode_question_reply(self) -> None:
        async def run() -> None:
            with TemporaryDirectory() as tmpdir:
                client = FakeClient()
                router = OpenCodeEventRouter(question_capability=_question_capability())
                adapter = OpenCodeServerAdapter(
                    config=_config(),
                    store=FileStore(tmpdir),
                    client=client,
                    event_router=router,
                    clock=lambda: datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix")
                await router.handle_event(
                    {
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": "m_assistant",
                                "sessionID": "oc_1",
                                "role": "assistant",
                                "parentID": client.message_id,
                            }
                        },
                    }
                )

                payload = {
                    "id": "que_1",
                    "sessionID": "oc_1",
                    "questions": [
                        {"header": "Path", "question": "Which path?", "options": []},
                    ],
                    "tool": {"messageID": "m_assistant", "callID": "call_1"},
                }
                await router.handle_event(
                    {
                        "type": "question.asked",
                        "properties": payload,
                    }
                )
                self.assertEqual(
                    await anext(agent_run.events),
                    UserInputRequested("que_1", "Which path?", payload),
                )

                await agent_run.answer_user_input("src/app.py")

            self.assertEqual(client.calls[-1], ("question", "que_1", [["src/app.py"]]))

        asyncio.run(run())

    def test_create_and_reuse_session_on_new_agent_port(self) -> None:
        async def run() -> None:
            with TemporaryDirectory() as tmpdir:
                client = FakeClient(session_id="oc_new")
                store = FileStore(tmpdir)
                adapter = OpenCodeServerAdapter(
                    config=_config(),
                    store=store,
                    client=client,
                    clock=lambda: datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )

                created = await adapter.create_session(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    agent_name="opencode",
                    workspace=Workspace(path="D:/repo"),
                    access_mode="workspace",
                )
                reused = await adapter.get_or_create_session(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    agent_name="opencode",
                    workspace=Workspace(path="D:/repo"),
                    access_mode="workspace",
                )

                self.assertEqual(created, reused)
                self.assertEqual(created.agent_session_id, "oc_new")
                self.assertEqual(store.get_current_session("user_1").bot_session_id, "oc_new")
                self.assertEqual(client.calls, [("create", "session_20260602_100000_000000")])

        asyncio.run(run())


class FakeClient:
    def __init__(self, session_id: str = "oc_1"):
        self.calls = []
        self.message_id = None
        self.session_id = session_id
        self.messages = []

    async def create_session(self, **kwargs):
        self.calls.append(("create", kwargs["title"]))
        return {"id": self.session_id}

    async def session_messages(self, **kwargs):
        return self.messages

    async def prompt_async(self, **kwargs):
        self.message_id = kwargs["message_id"]
        self.calls.append(("prompt", kwargs["text"]))
        return True

    async def abort_session(self, **kwargs):
        self.calls.append("abort")
        return True

    async def answer_question(self, **kwargs):
        self.calls.append(
            ("question", kwargs["question_id"], kwargs["answers"])
        )
        return True

    async def answer_permission(self, **kwargs):
        self.calls.append(("permission", kwargs["permission_id"], kwargs["decision"]))
        return True


def _config():
    return OpenCodeConfig("http://localhost", "D:/repo", "test-provider/test-model", "build")


def _session():
    return AgentSession(
        "oc_1", "chat_1", "ou_1", "opencode", Workspace(path="D:/repo"), "workspace",
    )


def _question_capability():
    return OpenCodeQuestionCapability(
        request_event="question.asked",
        reply_endpoint="/question/:requestID/reply",
    )


if __name__ == "__main__":
    unittest.main()
