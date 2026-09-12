"""
Avatar tests — personas on agents (John on Claude, Madeleine on OpenAI).

Covers the model, the agent service, the HTTP API and the CLI commands.
API fixtures are reused from ``tests.test_api`` via attribute assignment so
its test classes are not collected twice.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from memanto.app.models.session import (
    AVATAR_PRESETS,
    AgentAvatar,
    AgentCreate,
    AgentProvider,
    get_avatar_preset,
)
from memanto.app.services.agent_service import AgentService
from memanto.app.utils.errors import AgentNotFoundError
from memanto.cli.commands.avatar import avatar_glyph, avatar_label, build_avatar
from memanto.cli.main import app
from tests import test_api as _api

# Reuse the isolated-environment fixtures of the API suite.
test_env_setup = _api.test_env_setup
client = _api.client
auth_headers = _api.auth_headers
mock_moorcheh = _api.mock_moorcheh

runner = CliRunner()


# ============================================================================
# Model
# ============================================================================


class TestAvatarModel:
    def test_madeleine_preset_uses_single_codepoint_emoji(self):
        assert AVATAR_PRESETS["madeleine"].emoji == "👩"
        guide = (
            Path(__file__).resolve().parents[1] / "docs/CLI_USER_GUIDE.md"
        ).read_text(encoding="utf-8")
        assert "| `madeleine` | 👩 Madeleine | OpenAI |" in guide

    def test_presets_cover_john_and_madeleine(self):
        assert set(AVATAR_PRESETS) == {"john", "madeleine"}
        john = get_avatar_preset("John")
        madeleine = get_avatar_preset("MADELEINE")
        assert john is not None and john.provider == AgentProvider.CLAUDE
        assert madeleine is not None and madeleine.provider == AgentProvider.OPENAI
        assert get_avatar_preset("nobody") is None

    def test_preset_lookup_returns_a_copy(self):
        john = get_avatar_preset("john")
        assert john is not None
        john.name = "Johnny"
        assert AVATAR_PRESETS["john"].name == "John"

    def test_name_is_stripped_and_required(self):
        assert AgentAvatar(name="  John  ").name == "John"
        with pytest.raises(ValidationError):
            AgentAvatar(name="   ")

    def test_initials_fallback(self):
        assert AgentAvatar(name="John").initials == "JO"
        assert AgentAvatar(name="Bene Digital").initials == "BD"
        assert AgentAvatar(name="John", emoji="   ").emoji is None

    def test_invalid_provider_and_color_rejected(self):
        with pytest.raises(ValidationError):
            AgentAvatar(name="X", provider="gemini")
        with pytest.raises(ValidationError):
            AgentAvatar(name="X", color="red")
        assert AgentAvatar(name="X", color="#AbCdEf").color == "#AbCdEf"

    def test_agent_create_accepts_avatar_dict(self):
        created = AgentCreate(
            agent_id="john", avatar={"name": "John", "provider": "claude"}
        )
        assert created.avatar is not None
        assert created.avatar.provider is AgentProvider.CLAUDE
        assert AgentCreate(agent_id="plain").avatar is None


# ============================================================================
# Service
# ============================================================================


@pytest.fixture
def agent_service(tmp_path):
    service = AgentService(agents_dir=tmp_path / "agents")
    with patch(
        "memanto.app.services.agent_service.get_moorcheh_client"
    ) as get_client_mock:
        get_client_mock.return_value = MagicMock()
        yield service


class TestAvatarService:
    def test_create_persists_avatar(self, agent_service):
        agent = agent_service.create_agent(
            AgentCreate(agent_id="john", avatar=get_avatar_preset("john")),
            moorcheh_api_key="k",
        )
        assert agent.avatar is not None and agent.avatar.name == "John"
        reloaded = agent_service.get_agent("john")
        assert reloaded is not None and reloaded.avatar is not None
        assert reloaded.avatar.provider is AgentProvider.CLAUDE

    def test_set_and_clear_avatar(self, agent_service):
        agent_service.create_agent(AgentCreate(agent_id="a1"), moorcheh_api_key="k")
        updated = agent_service.set_avatar("a1", get_avatar_preset("madeleine"))
        assert updated.avatar is not None and updated.avatar.name == "Madeleine"
        reloaded = agent_service.get_agent("a1")
        assert reloaded is not None and reloaded.avatar is not None
        assert reloaded.avatar.provider is AgentProvider.OPENAI

        cleared = agent_service.set_avatar("a1", None)
        assert cleared.avatar is None
        reloaded = agent_service.get_agent("a1")
        assert reloaded is not None and reloaded.avatar is None

    def test_set_avatar_unknown_agent(self, agent_service):
        with pytest.raises(AgentNotFoundError):
            agent_service.set_avatar("ghost", get_avatar_preset("john"))

    def test_find_by_avatar_name_prefers_agent_id(self, agent_service):
        agent_service.create_agent(
            AgentCreate(agent_id="coach", avatar=get_avatar_preset("john")),
            moorcheh_api_key="k",
        )
        agent_service.create_agent(
            AgentCreate(
                agent_id="john", avatar=AgentAvatar(name="Madeleine", provider="openai")
            ),
            moorcheh_api_key="k",
        )
        # Agent ID wins over an avatar called the same.
        hit = agent_service.find_by_avatar_name("john")
        assert hit is not None and hit.agent_id == "john"
        # Avatar names resolve case-insensitively.
        hit = agent_service.find_by_avatar_name("madeleine")
        assert hit is not None and hit.agent_id == "john"
        assert agent_service.find_by_avatar_name("nobody") is None
        assert agent_service.find_by_avatar_name("   ") is None

    def test_legacy_agent_file_without_avatar_loads(self, agent_service):
        agent_service.create_agent(AgentCreate(agent_id="old"), moorcheh_api_key="k")
        agent_file = agent_service.agents_dir / "old.json"
        raw = agent_file.read_text(encoding="utf-8")
        assert '"avatar": null' in raw
        agent_file.write_text(raw.replace('"avatar": null,\n', ""), encoding="utf-8")
        loaded = agent_service.get_agent("old")
        assert loaded is not None and loaded.avatar is None


# ============================================================================
# API
# ============================================================================


class TestAvatarAPI:
    @pytest.mark.asyncio
    async def test_presets_endpoint(self, client, auth_headers):
        response = await client.get("/api/v2/avatars/presets", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["john"]["provider"] == "claude"
        assert data["madeleine"]["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_create_agent_with_avatar(self, client, auth_headers):
        payload = {
            "agent_id": "john",
            "pattern": "support",
            "avatar": {"name": "John", "provider": "claude", "emoji": "🧭"},
        }
        response = await client.post(
            "/api/v2/agents", headers=auth_headers, json=payload
        )
        assert response.status_code == 201
        assert response.json()["avatar"]["name"] == "John"

        listed = await client.get("/api/v2/agents", headers=auth_headers)
        agents = {a["agent_id"]: a for a in listed.json()["agents"]}
        assert agents["john"]["avatar"]["provider"] == "claude"

    @pytest.mark.asyncio
    async def test_put_and_delete_avatar(self, client, auth_headers):
        await client.post(
            "/api/v2/agents", headers=auth_headers, json={"agent_id": "a1"}
        )
        response = await client.put(
            "/api/v2/agents/a1/avatar",
            headers=auth_headers,
            json={"name": "Madeleine", "provider": "openai", "color": "#10a37f"},
        )
        assert response.status_code == 200
        assert response.json()["avatar"]["name"] == "Madeleine"

        response = await client.get("/api/v2/agents/a1", headers=auth_headers)
        assert response.json()["avatar"]["provider"] == "openai"

        response = await client.delete("/api/v2/agents/a1/avatar", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["avatar"] is None

    @pytest.mark.asyncio
    async def test_put_avatar_validation_and_unknown_agent(self, client, auth_headers):
        await client.post(
            "/api/v2/agents", headers=auth_headers, json={"agent_id": "a1"}
        )
        response = await client.put(
            "/api/v2/agents/a1/avatar",
            headers=auth_headers,
            json={"name": "X", "provider": "gemini"},
        )
        assert response.status_code == 422
        response = await client.put(
            "/api/v2/agents/ghost/avatar",
            headers=auth_headers,
            json={"name": "X", "provider": "claude"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_put_avatar_requires_credential(self, client):
        response = await client.put(
            "/api/v2/agents/a1/avatar", json={"name": "X", "provider": "claude"}
        )
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_status_shows_active_avatar(self, client, auth_headers):
        await client.post(
            "/api/v2/agents",
            headers=auth_headers,
            json={"agent_id": "john", "avatar": {"name": "John", "provider": "claude"}},
        )
        response = await client.post(
            "/api/v2/agents/john/activate", headers=auth_headers
        )
        assert response.status_code == 200
        response = await client.get("/api/v2/status", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["avatar"]["name"] == "John"

    @pytest.mark.asyncio
    async def test_switching_avatars_moves_the_active_session(
        self, client, auth_headers
    ):
        for agent_id, preset in (("john", "john"), ("madeleine", "madeleine")):
            avatar = AVATAR_PRESETS[preset].model_dump(mode="json")
            await client.post(
                "/api/v2/agents",
                headers=auth_headers,
                json={"agent_id": agent_id, "avatar": avatar},
            )
        await client.post("/api/v2/agents/john/activate", headers=auth_headers)
        await client.post("/api/v2/agents/madeleine/activate", headers=auth_headers)
        status = await client.get("/api/v2/status", headers=auth_headers)
        assert status.json()["agent_id"] == "madeleine"
        assert status.json()["avatar"]["provider"] == "openai"


# ============================================================================
# CLI
# ============================================================================


@pytest.fixture
def cli_client():
    """Mock get_client/config_manager in the avatar and agent command modules."""
    mock_client = MagicMock()
    patches = []
    for module in ("memanto.cli.commands.avatar", "memanto.cli.commands.agent"):
        p = patch(f"{module}.get_client", return_value=mock_client)
        p.start()
        patches.append(p)
        p_cfg = patch(f"{module}.config_manager")
        cfg = p_cfg.start()
        cfg.get_active_session.return_value = ("john", "tok")
        patches.append(p_cfg)
    try:
        yield mock_client
    finally:
        for p in patches:
            p.stop()


JOHN = {"name": "John", "provider": "claude", "emoji": "🧭", "color": "#d97757"}
MADELEINE = {"name": "Madeleine", "provider": "openai", "emoji": None, "color": None}


class TestAvatarHelpers:
    def test_glyph_and_label(self):
        assert avatar_glyph(None) == "—"
        assert avatar_glyph(JOHN) == "🧭"
        assert avatar_glyph(MADELEINE) == "MA"
        assert avatar_glyph({"name": "Bene Digital"}) == "BD"
        assert "Madeleine · OpenAI" in avatar_label(MADELEINE)

    def test_build_avatar_merges_preset_and_overrides(self):
        assert build_avatar(None, None, None, None, None) is None
        john = build_avatar("john", None, None, None, None)
        assert john == AVATAR_PRESETS["john"].model_dump(mode="json")
        mixed = build_avatar("john", None, "openai", "", "#000000")
        assert mixed["provider"] == "openai" and mixed["emoji"] is None
        assert mixed["color"] == "#000000" and mixed["name"] == "John"
        with pytest.raises(ValueError):
            build_avatar("nobody", None, None, None, None)
        with pytest.raises(ValueError):
            build_avatar(None, "X", "gemini", None, None)
        with pytest.raises(ValueError):
            build_avatar(None, None, "claude", None, None)


class TestAvatarCLI:
    @pytest.mark.parametrize("online", [True, False])
    @pytest.mark.parametrize("avatar", [JOHN, MADELEINE, None])
    def test_status_displays_current_agent_avatar(self, online, avatar):
        from memanto.app.clients.backend import Backend

        with (
            patch("memanto.cli.commands.core.config_manager") as cfg,
            patch("memanto.cli.commands.core.get_client") as get_client,
            patch("memanto.cli.commands.core.httpx.get") as health,
        ):
            cfg.is_configured.return_value = True
            cfg.get_backend.return_value = Backend.CLOUD
            cfg.get_active_session.return_value = ("active", "token")
            cfg.get_server_url.return_value = "http://localhost:8000"
            if not online:
                health.side_effect = ConnectionError("offline")
            else:
                health.return_value.json.return_value = {"status": "healthy"}
            client = get_client.return_value
            client.get_session_info.return_value = {"agent_id": "active"}
            client.get_agent.return_value = {"avatar": avatar}
            client.list_agents.return_value = []
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0, result.stdout
        assert "Avatar" in result.stdout
        if avatar:
            assert avatar["name"] in result.stdout
            assert ("Claude" if avatar == JOHN else "OpenAI") in result.stdout
        client.get_agent.assert_called_once_with("active")

    def test_presets(self, cli_client):
        result = runner.invoke(app, ["avatar", "presets"])
        assert result.exit_code == 0
        assert "john" in result.stdout and "madeleine" in result.stdout

    def test_list_marks_active(self, cli_client):
        cli_client.list_agents.return_value = {
            "agents": [
                {"agent_id": "john", "avatar": JOHN},
                {"agent_id": "madeleine", "avatar": MADELEINE},
                {"agent_id": "plain", "avatar": None},
            ],
            "warnings": [],
        }
        result = runner.invoke(app, ["avatar", "list"])
        assert result.exit_code == 0
        assert "John" in result.stdout and "Madeleine" in result.stdout
        assert "active" in result.stdout
        assert "no avatar" in result.stdout

    def test_current(self, cli_client):
        cli_client.get_agent.return_value = {"agent_id": "john", "avatar": JOHN}
        result = runner.invoke(app, ["avatar", "current"])
        assert result.exit_code == 0
        assert "John" in result.stdout and "Claude" in result.stdout

    def test_switch_by_avatar_name(self, cli_client):
        cli_client.find_agent_by_avatar.return_value = {
            "agent_id": "madeleine",
            "avatar": MADELEINE,
        }
        cli_client.get_agent.return_value = {"agent_id": "john", "avatar": JOHN}
        cli_client.activate_agent.return_value = {"expires_at": "2026-09-13T00:00:00Z"}

        result = runner.invoke(app, ["avatar", "switch", "Madeleine"])
        assert result.exit_code == 0, result.stdout
        cli_client.find_agent_by_avatar.assert_called_once_with("Madeleine")
        cli_client.activate_agent.assert_called_once_with("madeleine", 6)
        assert "Switched to" in result.stdout and "Madeleine" in result.stdout

    def test_switch_to_already_active_is_noop(self, cli_client):
        cli_client.find_agent_by_avatar.return_value = {
            "agent_id": "john",
            "avatar": JOHN,
        }
        result = runner.invoke(app, ["avatar", "switch", "john"])
        assert result.exit_code == 0
        assert "already active" in result.stdout
        cli_client.activate_agent.assert_not_called()

    def test_switch_unknown(self, cli_client):
        cli_client.find_agent_by_avatar.return_value = None
        result = runner.invoke(app, ["avatar", "switch", "nobody"])
        assert result.exit_code == 1
        assert "No avatar or agent named" in result.stdout

    def test_set_from_preset(self, cli_client):
        cli_client.set_agent_avatar.return_value = {
            "agent_id": "a1",
            "avatar": MADELEINE,
        }
        result = runner.invoke(app, ["avatar", "set", "a1", "--preset", "madeleine"])
        assert result.exit_code == 0, result.stdout
        args, _ = cli_client.set_agent_avatar.call_args
        assert args[0] == "a1" and args[1]["provider"] == "openai"
        assert "Madeleine" in result.stdout

    def test_set_without_anything(self, cli_client):
        result = runner.invoke(app, ["avatar", "set", "a1"])
        assert result.exit_code == 1
        cli_client.set_agent_avatar.assert_not_called()

    def test_clear(self, cli_client):
        cli_client.set_agent_avatar.return_value = {"agent_id": "a1", "avatar": None}
        result = runner.invoke(app, ["avatar", "clear", "a1"])
        assert result.exit_code == 0
        cli_client.set_agent_avatar.assert_called_once_with("a1", None)

    def test_agent_create_with_avatar_preset(self, cli_client):
        cli_client.create_agent.return_value = {"agent_id": "john"}
        cli_client.activate_agent.return_value = {"expires_at": "x"}
        result = runner.invoke(
            app, ["agent", "create", "john", "--avatar", "john", "--provider", "openai"]
        )
        assert result.exit_code == 0, result.stdout
        _, kwargs = cli_client.create_agent.call_args
        assert kwargs["avatar"]["name"] == "John"
        assert kwargs["avatar"]["provider"] == "openai"
        assert "Avatar:" in result.stdout

    def test_agent_create_with_unknown_preset(self, cli_client):
        result = runner.invoke(app, ["agent", "create", "x", "--avatar", "nobody"])
        assert result.exit_code == 1
        cli_client.create_agent.assert_not_called()

    def test_agent_create_without_avatar_keeps_old_call(self, cli_client):
        cli_client.create_agent.return_value = {"agent_id": "x"}
        cli_client.activate_agent.return_value = {"expires_at": "x"}
        result = runner.invoke(app, ["agent", "create", "x"])
        assert result.exit_code == 0
        cli_client.create_agent.assert_called_once_with("x", "tool", None)

    def test_agent_list_shows_avatar_column(self, cli_client):
        cli_client.list_agents.return_value = {
            "agents": [{"agent_id": "john", "pattern": "tool", "avatar": JOHN}],
            "warnings": [],
        }
        result = runner.invoke(app, ["agent", "list"])
        assert result.exit_code == 0
        assert "John" in result.stdout and "Claude" in result.stdout


class TestAvatarMemoryContext:
    @pytest.mark.parametrize("client_kind", ["direct", "sdk"])
    def test_sync_and_hook_replace_previous_persona_and_memories(
        self, tmp_path, client_kind
    ):
        from memanto.app.services.memory_export_service import MemoryExportService
        from memanto.cli.client.direct_client import DirectClient
        from memanto.cli.client.sdk_client import SdkClient
        from memanto.cli.connect.assets.hooks import session_start as hook

        cls = DirectClient if client_kind == "direct" else SdkClient
        client = object.__new__(cls)
        project = tmp_path / "project"
        for agent_id in ("john", "madeleine"):
            avatar = AVATAR_PRESETS[agent_id].model_dump(mode="json")
            with (
                patch.object(client, "_get_validated_session_for_agent"),
                patch.object(
                    client,
                    "_gather_memories_by_type",
                    return_value={
                        "fact": [{"title": "Private", "content": f"Only {agent_id}"}]
                    },
                ),
                patch.object(
                    client,
                    "_get_export_service",
                    return_value=MemoryExportService(tmp_path / "exports"),
                ),
                patch.object(client, "get_agent", return_value={"avatar": avatar}),
            ):
                client.sync_memory_to_project(agent_id, str(project))
            with (
                patch.object(hook, "_read_stdin", return_value={"cwd": str(project)}),
                patch.object(hook, "_claim", return_value=True),
                patch.object(
                    hook.subprocess, "run", return_value=MagicMock(returncode=0)
                ),
                patch.object(hook, "install_statusline", return_value=None),
                patch.object(hook, "_out") as out,
            ):
                hook.main()
            assert out.call_args.args[0].startswith(
                f"Du sprichst als {avatar['emoji']} {avatar['name']}"
            )
            content = (project / "MEMORY.md").read_text(encoding="utf-8")
            assert f"Only {agent_id}" in content
            other = "madeleine" if agent_id == "john" else "john"
            assert f"Only {other}" not in content

    @pytest.mark.parametrize("preset", ["john", "madeleine", None])
    def test_export_header_and_utf8_lf(self, tmp_path, preset):
        from memanto.app.services.memory_export_service import MemoryExportService

        avatar = AVATAR_PRESETS[preset].model_dump(mode="json") if preset else None
        path = MemoryExportService(tmp_path).write_memory_md(
            "owner",
            {"fact": [{"title": "Private", "content": "Owner memory"}]},
            avatar=avatar,
        )
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw
        content = raw.decode("utf-8")
        if preset:
            provider = "Claude" if preset == "john" else "OpenAI"
            assert content.startswith(
                f"Du sprichst als {avatar['emoji']} {avatar['name']} ({provider})\n\n"
            )
        else:
            assert content.startswith("# Memory — owner\n")
        assert "Owner memory" in content

    def test_avatar_metadata_cannot_inject_header_lines(self):
        from memanto.app.services.memory_export_service import MemoryExportService

        content = MemoryExportService().format_memory_md(
            "owner", {}, avatar={"name": "Bene\nDigital", "emoji": "\nX"}
        )
        assert content.splitlines()[0] == "Du sprichst als X Bene Digital (other)"

    @pytest.mark.parametrize("client_kind", ["direct", "sdk"])
    @pytest.mark.parametrize("missing_metadata", [True, False])
    def test_export_uses_target_agent_not_active_persona(
        self, tmp_path, client_kind, missing_metadata
    ):
        from memanto.app.services.memory_export_service import MemoryExportService
        from memanto.cli.client.direct_client import DirectClient
        from memanto.cli.client.sdk_client import SdkClient

        cls = DirectClient if client_kind == "direct" else SdkClient
        client = object.__new__(cls)
        client.agent_id = "john"
        with (
            patch.object(client, "_get_validated_session_for_agent"),
            patch.object(client, "_gather_memories_by_type", return_value={}) as gather,
            patch.object(
                client,
                "_get_export_service",
                return_value=MemoryExportService(tmp_path),
            ),
            patch.object(
                client, "get_agent", return_value={"avatar": MADELEINE}
            ) as get_agent,
        ):
            if missing_metadata:
                get_agent.side_effect = AgentNotFoundError("No local metadata")
            result = client.export_memory_md("madeleine")
        get_agent.assert_called_once_with("madeleine")
        gather.assert_called_once_with("madeleine", 25)
        content = Path(result["output_path"]).read_text(encoding="utf-8")
        if missing_metadata:
            assert content.startswith("# Memory — madeleine")
        else:
            assert content.startswith("Du sprichst als MA Madeleine (OpenAI)")
        assert "John" not in content

    @pytest.mark.parametrize("synced", [True, False])
    @pytest.mark.parametrize(
        "persona", ["Du sprichst als 🧭 John (Claude)", "# Memory — plain"]
    )
    def test_session_hook_emits_only_synced_header(self, tmp_path, synced, persona):
        from memanto.cli.connect.assets.hooks import session_start as hook

        (tmp_path / "MEMORY.md").write_text(
            persona + "\n\n> Total memories: **0**\n", encoding="utf-8"
        )
        with (
            patch.object(hook, "_read_stdin", return_value={"cwd": str(tmp_path)}),
            patch.object(hook, "_claim", return_value=True),
            patch.object(
                hook,
                "sync_memory",
                return_value="MEMORY.md refreshed." if synced else None,
            ),
            patch.object(hook, "install_statusline", return_value=None),
            patch.object(hook, "_out") as out,
        ):
            hook.main()
        if not synced:
            out.assert_not_called()
        else:
            message = out.call_args.args[0]
            assert message.startswith(persona) == persona.startswith("Du sprichst als ")

    def test_readme_documents_presets_and_manual_switch(self):
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
            encoding="utf-8"
        )
        section = readme.split("## Avatars\n", 1)[1].split("\n---", 1)[0]
        assert "John (Claude)" in section and "Madeleine (OpenAI)" in section
        assert "memanto avatar switch Madeleine" in section
        assert "manual" in section and "namespace" in section
