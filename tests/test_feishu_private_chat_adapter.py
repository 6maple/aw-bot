import unittest

from c_auto_bridge.core.agent_session import HistoricalAgentSession, Workspace
from c_auto_bridge.core.use_cases import (
    FileFinderResult,
    ModelListResult,
    OpenCodeAgentSelected,
    PrivateChatTextMessage,
    ResumeSessionList,
    RunViewAction,
    SkillInfo,
    SkillListResult,
    WorkspaceListResult,
)
from c_auto_bridge.core.workspace import NamedWorkspace
from c_auto_bridge.feishu.gateway import IncomingCardAction
from c_auto_bridge.feishu.message import IncomingMenuEvent, IncomingMessage
from c_auto_bridge.feishu.private_chat_adapter import FeishuPrivateChatAdapter


class FeishuPrivateChatAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_private_chat_message_is_forwarded_to_core_use_cases(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_message(
            IncomingMessage(
                message_id="om_1",
                chat_id="chat_1",
                chat_type="p2p",
                user_id="user_1",
                text="ship it",
            )
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "ship it")],
        )

    async def test_non_private_chat_message_is_ignored(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_message(
            IncomingMessage(
                message_id="om_1",
                chat_id="chat_1",
                chat_type="group",
                user_id="user_1",
                text="ship it",
            )
        )

        self.assertEqual(use_cases.text_messages, [])

    async def test_file_finder_result_is_sent_as_text(self) -> None:
        use_cases = FakeUseCases(file_finder=FileFinderResult(paths=("src/app.py", "tests/test_app.py")))
        texts = FakeTexts()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_text=texts.send_text)

        await adapter.handle_message(
            IncomingMessage(
                message_id="om_1",
                chat_id="chat_1",
                chat_type="p2p",
                user_id="user_1",
                text="/files app",
            )
        )

        self.assertEqual(texts.sent, [("chat_1", "src/app.py\ntests/test_app.py")])

    async def test_model_list_result_is_sent_as_text(self) -> None:
        use_cases = FakeUseCases(
            model_list=ModelListResult(
                agent_name="codex",
                models=("test-model", "test-model-next"),
                selected_model="test-model-next",
            )
        )
        texts = FakeTexts()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_text=texts.send_text)

        await adapter.handle_message(
            IncomingMessage(
                message_id="om_1",
                chat_id="chat_1",
                chat_type="p2p",
                user_id="user_1",
                text="/model",
            )
        )

        self.assertEqual(
            texts.sent,
            [("chat_1", "Agent: codex\nCurrent: test-model-next\nModels:\n- test-model\n- test-model-next")],
        )

    async def test_skill_list_result_is_sent_as_text(self) -> None:
        use_cases = FakeUseCases(
            skill_list=SkillListResult(
                agent_name="codex",
                skills=(
                    SkillInfo(name="c-tdd", description="Test-driven development"),
                    SkillInfo(name="c-review", description=None),
                ),
            )
        )
        texts = FakeTexts()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_text=texts.send_text)

        await adapter.handle_message(
            IncomingMessage(
                message_id="om_1",
                chat_id="chat_1",
                chat_type="p2p",
                user_id="user_1",
                text="/skills",
            )
        )

        self.assertEqual(
            texts.sent,
            [("chat_1", "Agent: codex\nSkills:\n- c-tdd: Test-driven development\n- c-review")],
        )

    async def test_opencode_agent_selection_result_is_sent_as_text(self) -> None:
        use_cases = FakeUseCases(opencode_agent=OpenCodeAgentSelected(agent="plan"))
        texts = FakeTexts()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_text=texts.send_text)

        await adapter.handle_message(
            IncomingMessage(
                message_id="om_1",
                chat_id="chat_1",
                chat_type="p2p",
                user_id="user_1",
                text="/agent plan",
            )
        )

        self.assertEqual(texts.sent, [("chat_1", "OpenCode agent selected: plan")])

    async def test_stop_card_action_becomes_stop_command(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "stop", "run_id": "run_1"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/stop")],
        )

    async def test_menu_stop_action_becomes_stop_command(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:stop"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/stop")],
        )
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_menu_new_action_becomes_new_command(self) -> None:
        use_cases = FakeUseCases()
        texts = FakeTexts()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_text=texts.send_text)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:new"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/new")],
        )
        self.assertEqual(texts.sent, [("chat_1", "已开启新的任务上下文。请直接发送你的需求。")])
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_menu_reset_action_becomes_reset_command(self) -> None:
        use_cases = FakeUseCases()
        texts = FakeTexts()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_text=texts.send_text)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:reset"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/reset")],
        )
        self.assertEqual(texts.sent, [("chat_1", "已重置当前会话。请直接发送新的需求。")])
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_menu_stop_without_active_run_sends_chinese_feedback(self) -> None:
        use_cases = FakeUseCases(
            text_error=RuntimeError("scope does not have an active run for user: chat_1")
        )
        texts = FakeTexts()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_text=texts.send_text)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:stop"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/stop")],
        )
        self.assertEqual(texts.sent, [("chat_1", "当前没有正在运行的任务。")])

    async def test_menu_workspace_action_sends_saved_workspace_card(self) -> None:
        use_cases = FakeUseCases(
            workspace_list=WorkspaceListResult(
                workspaces=(
                    NamedWorkspace(
                        name="repo",
                        workspace=Workspace(path="D:/repo"),
                        updated_at="2026-06-06T12:00:00+00:00",
                    ),
                )
            )
        )
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_card=cards.send_card)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:workspace"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/ws list")],
        )
        self.assertEqual(use_cases.run_view_actions, [])
        self.assertEqual(len(cards.sent), 1)
        chat_id, card = cards.sent[0]
        self.assertEqual(chat_id, "chat_1")
        rendered = str(card)
        self.assertIn("已保存的工作区", rendered)
        self.assertIn("repo", rendered)
        self.assertIn("D:/repo", rendered)
        self.assertIn("2026-06-06T12:00:00+00:00", rendered)
        self.assertIn("menu:workspace:use:repo", _card_commands(card))

    async def test_menu_workspace_action_sends_empty_state_when_no_workspaces_are_saved(self) -> None:
        use_cases = FakeUseCases(workspace_list=WorkspaceListResult(workspaces=()))
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_card=cards.send_card)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:workspace"})
        )

        self.assertEqual(len(cards.sent), 1)
        rendered = str(cards.sent[0][1])
        self.assertIn("还没有保存的工作区。", rendered)
        commands = _card_commands(cards.sent[0][1])
        self.assertNotIn("/cd", rendered)
        self.assertNotIn("/ws save", rendered)
        self.assertNotIn("delete", rendered.lower())
        self.assertEqual(commands, [])

    async def test_menu_workspace_use_action_becomes_ws_use_command(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:workspace:use:repo"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/ws use repo")],
        )
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_menu_sessions_action_sends_historical_agent_sessions_card(self) -> None:
        use_cases = FakeUseCases(
            resume_list=ResumeSessionList(
                sessions=(
                    HistoricalAgentSession(
                        agent_session_id="session_1",
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        agent_name="codex",
                        workspace=Workspace(path="D:/repo"),
                        access_mode="workspace",
                        updated_at="2026-06-06T12:00:00+00:00",
                    ),
                )
            )
        )
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_card=cards.send_card)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:sessions"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/resume")],
        )
        self.assertEqual(use_cases.run_view_actions, [])
        self.assertEqual(len(cards.sent), 1)
        chat_id, card = cards.sent[0]
        self.assertEqual(chat_id, "chat_1")
        rendered = str(card)
        self.assertIn("历史 Agent 会话", rendered)
        self.assertIn("session_1", rendered)
        self.assertIn("D:/repo", rendered)
        self.assertIn("codex", rendered)
        self.assertIn("2026-06-06T12:00:00+00:00", rendered)
        self.assertIn("menu:sessions:resume:session_1", _card_commands(card))

    async def test_menu_sessions_card_uses_feishu_safe_element_ids_for_long_session_ids(self) -> None:
        session_id = "ses_15ecc37deffeFypGdc3TfY2aI1"
        use_cases = FakeUseCases(
            resume_list=ResumeSessionList(
                sessions=(
                    HistoricalAgentSession(
                        agent_session_id=session_id,
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        agent_name="opencode",
                        workspace=Workspace(path="D:/repo"),
                        access_mode="workspace",
                        updated_at="2026-06-08T20:09:39.020627+08:00",
                    ),
                )
            )
        )
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_card=cards.send_card)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:sessions"})
        )

        card = cards.sent[0][1]
        self.assertEqual(_card_commands(card), [f"menu:sessions:resume:{session_id}"])
        for element_id in _element_ids(card):
            self.assertRegex(element_id, r"^[A-Za-z][A-Za-z0-9_]{0,19}$")

    async def test_menu_sessions_action_sends_empty_state_when_no_sessions_are_compatible(self) -> None:
        use_cases = FakeUseCases(resume_list=ResumeSessionList(sessions=()))
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_card=cards.send_card)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:sessions"})
        )

        self.assertEqual(len(cards.sent), 1)
        rendered = str(cards.sent[0][1])
        self.assertIn("没有可恢复的历史会话。", rendered)
        self.assertEqual(_card_commands(cards.sent[0][1]), [])

    async def test_menu_session_resume_action_becomes_resume_command(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:sessions:resume:session_1"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/resume session_1")],
        )
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_menu_timeout_action_sends_idle_timeout_card(self) -> None:
        use_cases = FakeUseCases()
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_card=cards.send_card)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:timeout"})
        )

        self.assertEqual(use_cases.text_messages, [])
        self.assertEqual(use_cases.run_view_actions, [])
        self.assertEqual(len(cards.sent), 1)
        chat_id, card = cards.sent[0]
        self.assertEqual(chat_id, "chat_1")
        rendered = str(card)
        self.assertIn("空闲超时", rendered)
        commands = _card_commands(card)
        self.assertEqual(
            commands,
            [
                "menu:timeout:5",
                "menu:timeout:10",
                "menu:timeout:30",
                "menu:timeout:off",
                "menu:timeout:default",
            ],
        )

    async def test_menu_timeout_value_actions_become_timeout_commands(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        for action in (
            "menu:timeout:5",
            "menu:timeout:10",
            "menu:timeout:30",
            "menu:timeout:off",
            "menu:timeout:default",
        ):
            await adapter.handle_card_action(
                IncomingCardAction("chat_1", "user_1", {"cmd": action})
            )

        self.assertEqual(
            use_cases.text_messages,
            [
                PrivateChatTextMessage("chat_1", "user_1", "/timeout 5"),
                PrivateChatTextMessage("chat_1", "user_1", "/timeout 10"),
                PrivateChatTextMessage("chat_1", "user_1", "/timeout 30"),
                PrivateChatTextMessage("chat_1", "user_1", "/timeout off"),
                PrivateChatTextMessage("chat_1", "user_1", "/timeout default"),
            ],
        )
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_skills_menu_action_routes_through_shared_text_command(self) -> None:
        use_cases = FakeUseCases(skill_list=SkillListResult(agent_name="codex", skills=()))
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:skills"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/skills")],
        )
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_model_menu_action_sends_model_panel_through_shared_text_command(self) -> None:
        use_cases = FakeUseCases(
            model_list=ModelListResult(
                agent_name="codex",
                models=("test-model", "test-model-next"),
                selected_model="test-model",
            ),
        )
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_card=cards.send_card)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:model"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/model")],
        )
        self.assertEqual(len(cards.sent), 1)
        rendered = str(cards.sent[0][1])
        self.assertIn("test-model", rendered)
        self.assertIn("test-model-next", rendered)
        self.assertEqual(
            _card_commands(cards.sent[0][1]),
            ["menu:model:use:test-model", "menu:model:use:test-model-next"],
        )
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_model_use_menu_action_routes_through_shared_text_command(self) -> None:
        use_cases = FakeUseCases(
            model_list=ModelListResult(
                agent_name="codex",
                models=("test-model", "test-model-next"),
                selected_model="test-model-next",
            )
        )
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:model:use:test-model-next"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/model use test-model-next")],
        )
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_file_search_menu_action_sends_deterministic_template_without_core_calls(self) -> None:
        use_cases = FakeUseCases()
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_card=cards.send_card)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:files"})
        )

        self.assertEqual(use_cases.text_messages, [])
        self.assertEqual(len(cards.sent), 1)
        rendered = str(cards.sent[0][1])
        self.assertIn("/files <query>", rendered)
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_opencode_plan_build_menu_actions_route_through_shared_text_commands(self) -> None:
        use_cases = FakeUseCases(opencode_agent=OpenCodeAgentSelected(agent="plan"))
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        for action in ("menu:agent:plan", "menu:agent:build"):
            await adapter.handle_card_action(
                IncomingCardAction("chat_1", "user_1", {"cmd": action})
            )

        self.assertEqual(
            use_cases.text_messages,
            [
                PrivateChatTextMessage("chat_1", "user_1", "/agent plan"),
                PrivateChatTextMessage("chat_1", "user_1", "/agent build"),
            ],
        )
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_menu_help_action_sends_static_help_card_without_core_calls(self) -> None:
        use_cases = FakeUseCases()
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_card=cards.send_card)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:help"})
        )

        self.assertEqual(use_cases.text_messages, [])
        self.assertEqual(use_cases.run_view_actions, [])
        self.assertEqual(len(cards.sent), 1)
        chat_id, card = cards.sent[0]
        self.assertEqual(chat_id, "chat_1")
        rendered = str(card)
        for text in (
            "AW Bot 菜单帮助",
            "/new",
            "/stop",
            "/reset",
            "/ws use <名称>",
            "/resume <会话 ID>",
            "/timeout 5|10|30|off|default",
            "工作区",
            "历史 Agent 会话",
            "空闲超时",
            "普通任务文本",
            "只打开菜单不会启动任务",
        ):
            self.assertIn(text, rendered)
        self.assertEqual(_card_commands(card), [])

    async def test_menu_help_card_is_deterministic(self) -> None:
        use_cases = FakeUseCases()
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_card=cards.send_card)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:help"})
        )
        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "menu:help"})
        )

        self.assertEqual(use_cases.text_messages, [])
        self.assertEqual(use_cases.run_view_actions, [])
        self.assertEqual(len(cards.sent), 2)
        self.assertEqual(cards.sent[0][1], cards.sent[1][1])

    async def test_approval_card_action_is_mapped_to_core_run_view_action(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "approve", "pending_id": "pending_1"})
        )
        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"action": "reject", "pending_id": "pending_2"})
        )

        self.assertEqual(
            use_cases.run_view_actions,
            [
                RunViewAction("chat_1", "user_1", "accept", "pending_1"),
                RunViewAction("chat_1", "user_1", "deny", "pending_2"),
            ],
        )

    async def test_aw_bot_menu_sends_first_level_command_panel_without_core_calls(self) -> None:
        use_cases = FakeUseCases()
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_user_card=cards.send_card)

        await adapter.handle_menu(
            IncomingMenuEvent(
                user_id="ou_1",
                event_key="aw_bot_menu()",
            )
        )

        self.assertEqual(use_cases.text_messages, [])
        self.assertEqual(use_cases.run_view_actions, [])
        self.assertEqual(len(cards.sent), 1)
        open_id, card = cards.sent[0]
        self.assertEqual(open_id, "ou_1")
        commands = _card_commands(card)
        self.assertEqual(
            commands,
            [
                "menu:new",
                "menu:stop",
                "menu:reset",
                "menu:workspace",
                "menu:sessions",
                "menu:skills",
                "menu:model",
                "menu:files",
                "menu:timeout",
                "menu:help",
            ],
        )
        self.assertEqual([element["tag"] for element in card["body"]["elements"]], ["column_set"] * 4)
        self.assertEqual(
            [len(element["columns"]) for element in card["body"]["elements"]],
            [3, 3, 2, 2],
        )
        self.assertNotIn("menu:agent:plan", commands)
        self.assertNotIn("menu:agent:build", commands)
        for element_id in _element_ids(card):
            self.assertRegex(element_id, r"^[A-Za-z][A-Za-z0-9_]{0,19}$")

    async def test_opencode_aw_bot_menu_includes_plan_build_switching(self) -> None:
        use_cases = FakeUseCases()
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(
            use_cases=use_cases,
            send_user_card=cards.send_card,
            show_opencode_agent_controls=True,
        )

        await adapter.handle_menu(
            IncomingMenuEvent(
                user_id="ou_1",
                event_key="aw_bot_menu()",
            )
        )

        commands = _card_commands(cards.sent[0][1])
        self.assertIn("menu:agent:plan", commands)
        self.assertIn("menu:agent:build", commands)
        for element_id in _element_ids(cards.sent[0][1]):
            self.assertRegex(element_id, r"^[A-Za-z][A-Za-z0-9_]{0,19}$")
        self.assertEqual(use_cases.text_messages, [])
        self.assertEqual(use_cases.run_view_actions, [])

    async def test_menu_key_must_match_exactly(self) -> None:
        use_cases = FakeUseCases()
        cards = FakeMenuCards()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases, send_user_card=cards.send_card)

        await adapter.handle_menu(
            IncomingMenuEvent(
                user_id="ou_1",
                event_key="aw_bot_menu",
            )
        )

        self.assertEqual(cards.sent, [])
        self.assertEqual(use_cases.text_messages, [])
        self.assertEqual(use_cases.run_view_actions, [])


class FakeUseCases:
    def __init__(
        self,
        *,
        workspace_list: WorkspaceListResult | None = None,
        resume_list: ResumeSessionList | None = None,
        file_finder: FileFinderResult | None = None,
        model_list: ModelListResult | None = None,
        skill_list: SkillListResult | None = None,
        opencode_agent: OpenCodeAgentSelected | None = None,
        text_error: Exception | None = None,
    ) -> None:
        self.text_messages: list[PrivateChatTextMessage] = []
        self.run_view_actions: list[RunViewAction] = []
        self.workspace_list = workspace_list
        self.resume_list = resume_list
        self.file_finder = file_finder
        self.model_list = model_list
        self.skill_list = skill_list
        self.opencode_agent = opencode_agent
        self.text_error = text_error

    async def handle_private_chat_text(self, message: PrivateChatTextMessage) -> object:
        self.text_messages.append(message)
        if self.text_error is not None:
            raise self.text_error
        if message.text == "/ws list":
            if self.workspace_list is None:
                raise AssertionError("workspace list was not configured")
            return self.workspace_list
        if message.text == "/resume":
            if self.resume_list is None:
                raise AssertionError("resume list was not configured")
            return self.resume_list
        if message.text.startswith("/files "):
            if self.file_finder is None:
                raise AssertionError("file finder result was not configured")
            return self.file_finder
        if message.text.startswith("/model"):
            if self.model_list is None:
                raise AssertionError("model list result was not configured")
            return self.model_list
        if message.text == "/skills":
            if self.skill_list is None:
                raise AssertionError("skill list result was not configured")
            return self.skill_list
        if message.text.startswith("/agent "):
            if self.opencode_agent is None:
                raise AssertionError("OpenCode agent result was not configured")
            return self.opencode_agent
        return None

    async def handle_run_view_action(self, action: RunViewAction) -> None:
        self.run_view_actions.append(action)


class FakeMenuCards:
    def __init__(self) -> None:
        self.sent = []

    async def send_card(self, chat_id: str, card: dict) -> None:
        self.sent.append((chat_id, card))


class FakeTexts:
    def __init__(self) -> None:
        self.sent = []

    async def send_text(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


def _card_commands(card: dict) -> list[str]:
    commands = []
    for element in card["body"]["elements"]:
        if element["tag"] == "action":
            commands.extend(action["value"]["cmd"] for action in element["actions"])
            continue
        if element["tag"] == "column_set":
            for column in element["columns"]:
                commands.extend(
                    child["value"]["cmd"]
                    for child in column["elements"]
                    if child["tag"] == "button"
                )
            continue
        if element["tag"] != "button":
            continue
        commands.append(element["value"]["cmd"])
    return commands


def _element_ids(card: dict) -> list[str]:
    element_ids = []
    for element in card["body"]["elements"]:
        if "element_id" in element:
            element_ids.append(element["element_id"])
        if element["tag"] == "action":
            element_ids.extend(
                action["element_id"] for action in element["actions"] if "element_id" in action
            )
        if element["tag"] == "column_set":
            for column in element["columns"]:
                element_ids.extend(
                    child["element_id"] for child in column["elements"] if "element_id" in child
                )
    return element_ids


if __name__ == "__main__":
    unittest.main()
