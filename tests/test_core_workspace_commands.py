import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from c_auto_bridge.core.agent_events import RunCompleted, TextDelta
from c_auto_bridge.core.agent_session import AgentSession, AgentTurn, Workspace
from c_auto_bridge.core.run_view import RunView
from c_auto_bridge.core.use_cases import (
    CoreUseCases,
    FileFinderResult,
    OpenCodeAgentSelected,
    ModelListResult,
    PrivateChatTextMessage,
    SkillInfo,
    SkillListResult,
    WorkspaceChanged,
    WorkspaceListResult,
    WorkspaceRemoved,
    WorkspaceSaved,
)
from c_auto_bridge.core.workspace import NamedWorkspace, WorkspaceValidator


class CoreWorkspaceCommandsTest(unittest.IsolatedAsyncioTestCase):
    async def test_opencode_agent_plan_selects_agent_for_subsequent_turn(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
                agent_name="opencode",
            )

            selected = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/agent plan",
                )
            )
            first_run_task = asyncio.create_task(
                use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="work",
                    )
                )
            )
            await agent.wait_for_active_turn()
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/stop",
                )
            )
            await first_run_task

            self.assertEqual(selected, OpenCodeAgentSelected(agent="plan"))
            self.assertEqual(agent.started_opencode_agents, ["plan"])

    async def test_opencode_agent_build_selects_agent_for_subsequent_turn(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
                agent_name="opencode",
            )

            selected = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/agent build",
                )
            )
            first_run_task = asyncio.create_task(
                use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="work",
                    )
                )
            )
            await agent.wait_for_active_turn()
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/stop",
                )
            )
            await first_run_task

            self.assertEqual(selected, OpenCodeAgentSelected(agent="build"))
            self.assertEqual(agent.started_opencode_agents, ["build"])

    async def test_agent_command_rejects_unknown_opencode_agent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            use_cases = build_use_cases(
                agent=agent,
                persistence=FakeWorkspacePersistence(),
                run_view_sink=FakeRunViewSink(),
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
                agent_name="opencode",
            )

            for command in ("/agent", "/agent   "):
                with self.assertRaisesRegex(ValueError, "OpenCode agent value is required"):
                    await use_cases.handle_private_chat_text(
                        PrivateChatTextMessage("chat_1", "user_1", command)
                    )
            with self.assertRaisesRegex(ValueError, "unknown OpenCode agent: review"):
                await use_cases.handle_private_chat_text(
                    PrivateChatTextMessage("chat_1", "user_1", "/agent review")
                )

            self.assertEqual(agent.started_prompts, [])

    async def test_codex_runtime_rejects_opencode_agent_switch(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            use_cases = build_use_cases(
                agent=agent,
                persistence=FakeWorkspacePersistence(),
                run_view_sink=FakeRunViewSink(),
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            for command in ("/agent plan", "/agent build"):
                with self.assertRaisesRegex(ValueError, f"{command} is only available for OpenCode"):
                    await use_cases.handle_private_chat_text(
                        PrivateChatTextMessage("chat_1", "user_1", command)
                    )

            self.assertEqual(agent.started_prompts, [])

    async def test_opencode_agent_switch_does_not_mutate_active_run_agent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
                agent_name="opencode",
            )

            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage("chat_1", "user_1", "/agent plan")
            )
            first_run_task = asyncio.create_task(
                use_cases.handle_private_chat_text(
                    PrivateChatTextMessage("chat_1", "user_1", "work")
                )
            )
            await agent.wait_for_active_turn()
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage("chat_1", "user_1", "/agent build")
            )
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage("chat_1", "user_1", "/stop")
            )
            await first_run_task

            self.assertEqual(agent.started_opencode_agents, ["plan"])

    async def test_queued_turn_after_opencode_agent_switch_uses_selected_agent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
                agent_name="opencode",
            )

            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage("chat_1", "user_1", "/agent plan")
            )
            first_run_task = asyncio.create_task(
                use_cases.handle_private_chat_text(
                    PrivateChatTextMessage("chat_1", "user_1", "work")
                )
            )
            await agent.wait_for_active_turn()
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage("chat_1", "user_1", "/agent build")
            )
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage("chat_1", "user_1", "queued")
            )
            agent.release_first_turn()
            await first_run_task

            self.assertEqual(agent.started_opencode_agents, ["plan", "build"])
            self.assertEqual(agent.created_sessions, ["session_1", "session_2"])

    async def test_skills_lists_active_agent_skills_without_starting_agent_turn(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort(
                skills=(
                    SkillInfo(name="c-tdd", description="Test-driven development"),
                    SkillInfo(name="c-review", description=None),
                )
            )
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            result = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/skills",
                )
            )

            self.assertEqual(
                result,
                SkillListResult(
                    agent_name="codex",
                    skills=(
                        SkillInfo(name="c-tdd", description="Test-driven development"),
                        SkillInfo(name="c-review", description=None),
                    ),
                ),
            )
            self.assertEqual(agent.skill_workspaces, [str(workspace_dir.resolve())])
            self.assertEqual(agent.started_prompts, [])

    async def test_model_lists_active_agent_models_and_current_scope_selection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort(models=("test-model", "test-model-next"))
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            result = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/model",
                )
            )

            self.assertEqual(
                result,
                ModelListResult(
                    agent_name="codex",
                    models=("test-model", "test-model-next"),
                    selected_model=None,
                ),
            )
            self.assertEqual(agent.started_prompts, [])

    async def test_model_use_selects_model_for_current_private_chat_scope_only(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort(models=("test-model", "test-model-next"))
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            selected = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/model use test-model-next",
                )
            )
            same_scope = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/model",
                )
            )
            other_scope = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_2",
                    user_id="user_1",
                    text="/model",
                )
            )

            self.assertEqual(
                selected,
                ModelListResult(
                    agent_name="codex",
                    models=("test-model", "test-model-next"),
                    selected_model="test-model-next",
                ),
            )
            self.assertEqual(same_scope.selected_model, "test-model-next")
            self.assertIsNone(other_scope.selected_model)
            self.assertEqual(agent.started_prompts, [])

    async def test_selected_model_is_passed_to_new_agent_turn(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort(models=("test-model", "test-model-next"))
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/model use test-model-next",
                )
            )
            first_run_task = asyncio.create_task(
                use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="work",
                    )
                )
            )
            await agent.wait_for_active_turn()
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/stop",
                )
            )
            await first_run_task

            self.assertEqual(agent.started_models, ["test-model-next"])

    async def test_model_switch_clears_current_session_for_subsequent_turns(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort(models=("test-model", "test-model-next"))
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            first_run_task = asyncio.create_task(
                use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="work",
                    )
                )
            )
            await agent.wait_for_active_turn()
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/stop",
                )
            )
            await first_run_task
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/model use test-model-next",
                )
            )
            next_run = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="fresh",
                )
            )

            self.assertEqual(persistence.cleared_session_scope_ids, ["chat_1"])
            self.assertEqual(agent.created_sessions, ["session_1", "session_2"])
            self.assertEqual(next_run.agent_session_id, "session_2")
            self.assertEqual(agent.started_models, [None, "test-model-next"])

    async def test_model_switch_does_not_mutate_active_run_model(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort(models=("test-model", "test-model-next"))
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            first_run_task = asyncio.create_task(
                use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="work",
                    )
                )
            )
            await agent.wait_for_active_turn()
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/model use test-model-next",
                )
            )
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/stop",
                )
            )
            await first_run_task

            self.assertEqual(agent.started_models, [None])

    async def test_queued_turn_after_model_switch_uses_selected_model_and_fresh_session(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort(models=("test-model", "test-model-next"))
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            first_run_task = asyncio.create_task(
                use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="work",
                    )
                )
            )
            await agent.wait_for_active_turn()
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/model use test-model-next",
                )
            )
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="queued",
                )
            )
            agent.release_first_turn()
            final_run = await first_run_task

            self.assertEqual(final_run.agent_session_id, "session_2")
            self.assertEqual(agent.created_sessions, ["session_1", "session_2"])
            self.assertEqual(agent.started_models, [None, "test-model-next"])

    async def test_model_use_requires_known_model_value(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort(models=("test-model",))
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            for command in ("/model use", "/model use   "):
                with self.assertRaisesRegex(ValueError, "model value is required"):
                    await use_cases.handle_private_chat_text(
                        PrivateChatTextMessage(
                            private_chat_scope_id="chat_1",
                            user_id="user_1",
                            text=command,
                        )
                    )
            with self.assertRaisesRegex(ValueError, "unknown model: test-model-missing"):
                await use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="/model use test-model-missing",
                    )
                )

            listed = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/model",
                )
            )
            self.assertIsNone(listed.selected_model)
            self.assertEqual(agent.started_prompts, [])

    async def test_files_returns_workspace_relative_matches_without_starting_agent_turn(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            (workspace_dir / "src").mkdir()
            (workspace_dir / "src" / "app.py").write_text("", encoding="utf-8")
            (workspace_dir / "notes.txt").write_text("", encoding="utf-8")
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            result = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/files app",
                )
            )

            self.assertEqual(result, FileFinderResult(paths=("src/app.py",)))
            self.assertEqual(agent.started_prompts, [])

    async def test_files_excludes_noisy_directories_and_limits_results(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            (workspace_dir / "src").mkdir()
            for index in range(11):
                (workspace_dir / "src" / f"match_{index:02}.txt").write_text("", encoding="utf-8")
            for directory in (".git", ".venv", "node_modules", ".data", ".cache"):
                noisy_dir = workspace_dir / directory
                noisy_dir.mkdir()
                (noisy_dir / "match_noise.txt").write_text("", encoding="utf-8")
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            result = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/files match",
                )
            )

            self.assertEqual(
                result,
                FileFinderResult(
                    paths=tuple(f"src/match_{index:02}.txt" for index in range(10))
                ),
            )

    async def test_files_requires_query(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            for command in ("/files", "/files   "):
                with self.assertRaisesRegex(ValueError, "file query is required"):
                    await use_cases.handle_private_chat_text(
                        PrivateChatTextMessage(
                            private_chat_scope_id="chat_1",
                            user_id="user_1",
                            text=command,
                        )
                    )

            self.assertEqual(agent.started_prompts, [])

    async def test_cd_switches_workspace_interrupts_run_and_clears_session(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            current_workspace_dir = Path(tmpdir) / "current"
            next_workspace_dir = Path(tmpdir) / "next"
            current_workspace_dir.mkdir()
            next_workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(current_workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            first_run_task = asyncio.create_task(
                use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="work",
                    )
                )
            )
            await agent.wait_for_active_turn()

            result = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text=f"/cd {next_workspace_dir}",
                )
            )
            await first_run_task
            next_run = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="fresh",
                )
            )

            self.assertEqual(result, WorkspaceChanged(workspace=Workspace(path=str(next_workspace_dir.resolve()))))
            self.assertEqual(agent.stopped_turn_ids, ["turn_1"])
            self.assertEqual(persistence.cleared_session_scope_ids, ["chat_1"])
            self.assertEqual(agent.created_sessions, ["session_1", "session_2"])
            self.assertEqual(agent.session_workspaces, [str(current_workspace_dir.resolve()), str(next_workspace_dir.resolve())])
            self.assertEqual(next_run.agent_session_id, "session_2")

    async def test_ws_save_and_list_named_workspaces(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            saved = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/ws save repo",
                )
            )
            listed = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/ws list",
                )
            )

            named_workspace = NamedWorkspace(
                name="repo",
                workspace=Workspace(path=str(workspace_dir.resolve())),
                updated_at="2026-06-06T12:00:00+00:00",
            )
            self.assertEqual(saved, WorkspaceSaved(named_workspace=named_workspace))
            self.assertEqual(listed, WorkspaceListResult(workspaces=(named_workspace,)))

    async def test_ws_use_switches_workspace_interrupts_run_and_clears_session(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            current_workspace_dir = Path(tmpdir) / "current"
            next_workspace_dir = Path(tmpdir) / "next"
            current_workspace_dir.mkdir()
            next_workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            persistence.named_workspaces["next"] = NamedWorkspace(
                name="next",
                workspace=Workspace(path=str(next_workspace_dir.resolve())),
                updated_at="2026-06-06T11:00:00+00:00",
            )
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(current_workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            first_run_task = asyncio.create_task(
                use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="work",
                    )
                )
            )
            await agent.wait_for_active_turn()

            result = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/ws use next",
                )
            )
            await first_run_task
            next_run = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="fresh",
                )
            )

            self.assertEqual(result, WorkspaceChanged(workspace=Workspace(path=str(next_workspace_dir.resolve()))))
            self.assertEqual(agent.stopped_turn_ids, ["turn_1"])
            self.assertEqual(persistence.cleared_session_scope_ids, ["chat_1"])
            self.assertEqual(agent.session_workspaces, [str(current_workspace_dir.resolve()), str(next_workspace_dir.resolve())])
            self.assertEqual(next_run.agent_session_id, "session_2")

    async def test_ws_remove_deletes_named_workspace(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            persistence.named_workspaces["repo"] = NamedWorkspace(
                name="repo",
                workspace=Workspace(path=str(workspace_dir.resolve())),
                updated_at="2026-06-06T11:00:00+00:00",
            )
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            removed = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/ws remove repo",
                )
            )
            listed = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/ws list",
                )
            )

            self.assertEqual(removed, WorkspaceRemoved(name="repo"))
            self.assertEqual(listed, WorkspaceListResult(workspaces=()))

    async def test_cd_rejects_relative_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            agent = FakeWorkspaceAgentPort()
            persistence = FakeWorkspacePersistence()
            run_view_sink = FakeRunViewSink()
            use_cases = build_use_cases(
                agent=agent,
                persistence=persistence,
                run_view_sink=run_view_sink,
                workspace=Workspace(path=str(home_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
            )

            with self.assertRaisesRegex(ValueError, "absolute"):
                await use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="/cd repo",
                    )
                )


def build_use_cases(
    agent,
    persistence,
    run_view_sink,
    workspace: Workspace,
    workspace_validator: WorkspaceValidator,
    agent_name: str = "codex",
) -> CoreUseCases:
    return build_use_cases_with_agent_name(
        agent=agent,
        persistence=persistence,
        run_view_sink=run_view_sink,
        workspace=workspace,
        workspace_validator=workspace_validator,
        agent_name=agent_name,
    )


def build_use_cases_with_agent_name(
    agent,
    persistence,
    run_view_sink,
    workspace: Workspace,
    workspace_validator: WorkspaceValidator,
    agent_name: str,
) -> CoreUseCases:
    return CoreUseCases(
        agent=agent,
        persistence=persistence,
        run_view_sink=run_view_sink,
        workspace=workspace,
        workspace_validator=workspace_validator,
        access_mode="workspace",
        agent_name=agent_name,
        clock=lambda: datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc),
        run_id_factory=RunIdFactory(),
    )


class RunIdFactory:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, now: datetime) -> str:
        self.value += 1
        return f"run_{self.value}"


class FakeWorkspaceAgentPort:
    def __init__(
        self,
        *,
        models: tuple[str, ...] = ("test-model",),
        skills: tuple[SkillInfo, ...] = (),
    ) -> None:
        self.models = models
        self.skills = skills
        self.skill_workspaces: list[str] = []
        self.created_sessions: list[str] = []
        self.session_workspaces: list[str] = []
        self.started_prompts: list[str] = []
        self.started_models: list[str | None] = []
        self.started_opencode_agents: list[str | None] = []
        self.stopped_turn_ids: list[str] = []
        self._active_turn = asyncio.Event()
        self._stop_first_turn = asyncio.Event()
        self._session_counter = 0
        self._current_session: AgentSession | None = None

    async def list_models(self, *, workspace: Workspace) -> tuple[str, ...]:
        return self.models

    async def list_skills(self, *, workspace: Workspace) -> tuple[SkillInfo, ...]:
        self.skill_workspaces.append(workspace.path)
        return self.skills

    async def get_or_create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: str,
    ) -> AgentSession:
        if self._current_session is None:
            self._current_session = await self.create_session(
                private_chat_scope_id=private_chat_scope_id,
                user_id=user_id,
                agent_name=agent_name,
                workspace=workspace,
                access_mode=access_mode,
            )
        return self._current_session

    async def create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: str,
    ) -> AgentSession:
        self._session_counter += 1
        session = AgentSession(
            agent_session_id=f"session_{self._session_counter}",
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_name=agent_name,
            workspace=workspace,
            access_mode=access_mode,
        )
        self.created_sessions.append(session.agent_session_id)
        self.session_workspaces.append(workspace.path)
        self._current_session = session
        return session

    async def start_turn(
        self,
        *,
        agent_session: AgentSession,
        prompt: str,
        model: str | None,
        opencode_agent: str | None = None,
    ) -> "FakeWorkspaceTurn":
        self.started_prompts.append(prompt)
        self.started_models.append(model)
        self.started_opencode_agents.append(opencode_agent)
        turn_id = f"turn_{len(self.started_prompts)}"
        if len(self.started_prompts) == 1:
            return FakeWorkspaceTurn(
                port=self,
                agent_turn=AgentTurn(agent_turn_id=turn_id),
                events=self._blocking_events(),
            )
        return FakeWorkspaceTurn(
            port=self,
            agent_turn=AgentTurn(agent_turn_id=turn_id),
            events=self._completed_events(prompt),
        )

    async def wait_for_active_turn(self) -> None:
        for _ in range(50):
            if self._active_turn.is_set():
                return
            await asyncio.sleep(0)
        raise AssertionError("active turn did not start")

    def release_first_turn(self) -> None:
        self._stop_first_turn.set()

    async def _blocking_events(self) -> AsyncIterator[object]:
        self._active_turn.set()
        yield TextDelta("working")
        await self._stop_first_turn.wait()
        yield RunCompleted()

    async def _completed_events(self, prompt: str) -> AsyncIterator[object]:
        yield TextDelta(prompt)
        yield RunCompleted()


@dataclass
class FakeWorkspaceTurn:
    port: FakeWorkspaceAgentPort
    agent_turn: AgentTurn
    events: AsyncIterator[object]

    async def answer_user_input(self, text: str) -> None:
        raise AssertionError("user input is not used in these tests")

    async def answer_approval(self, pending_request_id: str, decision: str) -> None:
        raise AssertionError("approval is not used in these tests")

    async def stop(self) -> None:
        self.port.stopped_turn_ids.append(self.agent_turn.agent_turn_id)
        self.port._stop_first_turn.set()
        self.port._current_session = None


class FakeWorkspacePersistence:
    def __init__(self) -> None:
        self.created_runs = []
        self.run_events: dict[str, list[object]] = {}
        self.terminal_statuses: list[tuple[str, str, str]] = []
        self.opened_pending_requests = []
        self.closed_pending_requests = []
        self.cleared_session_scope_ids: list[str] = []
        self.named_workspaces: dict[str, NamedWorkspace] = {}
        self.saved_agent_sessions = []

    async def record_run_created(self, run) -> None:
        self.created_runs.append(run)
        self.run_events[run.run_id] = []

    async def record_run_event(self, *, run_id: str, event: object) -> None:
        self.run_events[run_id].append(event)

    async def record_run_terminal_status(self, *, run_id: str, status: str, updated_at: str) -> None:
        self.terminal_statuses.append((run_id, status, updated_at))

    async def open_pending_request(self, *, run_id: str, pending_request) -> None:
        self.opened_pending_requests.append((run_id, pending_request.pending_request_id))

    async def close_pending_request(self, *, pending_request_id: str, status: str) -> None:
        self.closed_pending_requests.append((pending_request_id, status))

    async def clear_current_session(self, *, private_chat_scope_id: str) -> None:
        self.cleared_session_scope_ids.append(private_chat_scope_id)

    async def save_named_workspace(self, *, workspace: NamedWorkspace) -> None:
        self.named_workspaces[workspace.name] = workspace

    async def get_named_workspace(self, *, name: str) -> NamedWorkspace | None:
        return self.named_workspaces.get(name)

    async def list_named_workspaces(self) -> list[NamedWorkspace]:
        return list(self.named_workspaces.values())

    async def remove_named_workspace(self, *, name: str) -> None:
        self.named_workspaces.pop(name, None)

    async def save_agent_session(self, *, agent_session) -> None:
        self.saved_agent_sessions.append(agent_session)

    async def list_agent_sessions(self, *, private_chat_scope_id: str, user_id: str) -> list:
        return []


class FakeRunViewSink:
    def __init__(self) -> None:
        self.views: list[RunView] = []

    async def publish(self, *, private_chat_scope_id: str, run_view: RunView) -> None:
        self.views.append(run_view)


if __name__ == "__main__":
    unittest.main()
