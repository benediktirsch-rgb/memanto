"""
MEMANTO CLI - Avatar commands (list, current, switch, set, clear, presets).

An avatar is the face of an agent: a display name such as ``John`` or
``Madeleine``, the model provider behind it (``claude``, ``openai``, ``other``)
and an optional emoji / colour. Every avatar lives on exactly one agent, so
switching avatars is the same as activating that agent — memories stay in the
agent's own namespace and never mix between personas.
"""

from typing import Any

import typer
from rich.table import Table

from memanto.app.models.session import AVATAR_PRESETS, AgentProvider
from memanto.app.utils.errors import SessionNotFoundError
from memanto.cli.commands._shared import (
    ACCENT,
    BOLD_PRIMARY,
    BRIGHT,
    SUCCESS,
    _error,
    avatar_app,
    config_manager,
    console,
    get_client,
)

PROVIDER_LABELS = {
    AgentProvider.CLAUDE.value: "Claude",
    AgentProvider.OPENAI.value: "OpenAI",
    AgentProvider.OTHER.value: "other",
}


def avatar_glyph(avatar: dict[str, Any] | None) -> str:
    """Emoji if set, otherwise two-letter initials of the display name."""
    if not avatar:
        return "—"
    emoji = avatar.get("emoji")
    if emoji:
        return str(emoji)
    parts = [p for p in str(avatar.get("name", "")).split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def avatar_label(avatar: dict[str, Any] | None) -> str:
    """One-line label like ``🧭 John · Claude`` for tables and messages."""
    if not avatar:
        return "[dim]—[/dim]"
    provider = PROVIDER_LABELS.get(str(avatar.get("provider", "other")), "other")
    return f"{avatar_glyph(avatar)} {avatar.get('name', '?')} · {provider}"


def build_avatar(
    preset: str | None,
    name: str | None,
    provider: str | None,
    emoji: str | None,
    color: str | None,
) -> dict[str, Any] | None:
    """
    Merge ``--avatar <preset>`` with explicit ``--avatar-name`` etc. into an
    avatar dict, or return ``None`` when nothing avatar-related was given.

    Explicit values win over the preset so ``--avatar john --provider openai``
    yields John on OpenAI.
    """
    avatar: dict[str, Any] = {}
    if preset:
        found = AVATAR_PRESETS.get(preset.strip().lower())
        if not found:
            raise ValueError(
                f"Unknown avatar preset '{preset}'. "
                f"Available: {', '.join(sorted(AVATAR_PRESETS))}"
            )
        avatar = found.model_dump(mode="json")
    if name:
        avatar["name"] = name
    if provider:
        value = provider.strip().lower()
        valid = [p.value for p in AgentProvider]
        if value not in valid:
            raise ValueError(
                f"Invalid provider '{provider}'. Must be one of: {', '.join(valid)}"
            )
        avatar["provider"] = value
    if emoji is not None:
        avatar["emoji"] = emoji or None
    if color:
        avatar["color"] = color
    if not avatar:
        return None
    if not avatar.get("name"):
        raise ValueError(
            "An avatar needs a name: pass --avatar-name or --avatar <preset>."
        )
    return avatar


@avatar_app.command("presets")
def avatar_presets():
    """Show the built-in avatar presets (john on Claude, madeleine on OpenAI)."""
    table = Table(title="Avatar presets", show_header=True, header_style=BOLD_PRIMARY)
    table.add_column("Preset", style=BRIGHT)
    table.add_column("Avatar")
    table.add_column("Provider", style=ACCENT)
    table.add_column("Colour", style="white")
    for key, preset in AVATAR_PRESETS.items():
        data = preset.model_dump(mode="json")
        table.add_row(
            key,
            f"{avatar_glyph(data)} {data['name']}",
            PROVIDER_LABELS.get(data["provider"], data["provider"]),
            data.get("color") or "—",
        )
    console.print(table)
    console.print(
        "[dim]Use: memanto agent create <id> --avatar <preset>  or  "
        "memanto avatar set <agent-id> --preset <preset>[/dim]"
    )


@avatar_app.command("list")
def avatar_list():
    """List agents with their avatars; the active one is marked."""
    client = get_client()
    try:
        response = client.list_agents()
    except Exception as e:
        _error(f"Failed to list agents: {e}")

    agents = response.get("agents", [])
    for w in response.get("warnings", []):
        console.print(f"[yellow]Warning: {w}[/yellow]")
    if not agents:
        console.print(
            "[yellow]No agents found. Create one with "
            "'memanto agent create <id> --avatar john'[/yellow]"
        )
        return

    active_agent, _ = config_manager.get_active_session()
    table = Table(title="Avatars", show_header=True, header_style=BOLD_PRIMARY)
    table.add_column("", width=2)
    table.add_column("Avatar")
    table.add_column("Provider", style=ACCENT)
    table.add_column("Agent ID", style=BRIGHT)
    table.add_column("Status", style=SUCCESS)
    for agent in agents:
        avatar = agent.get("avatar")
        is_active = agent["agent_id"] == active_agent
        table.add_row(
            "●" if is_active else "",
            f"{avatar_glyph(avatar)} {avatar['name']}"
            if avatar
            else "[dim]— no avatar[/dim]",
            PROVIDER_LABELS.get(str(avatar.get("provider")), "other") if avatar else "",
            agent["agent_id"],
            "active" if is_active else "",
        )
    console.print(table)
    console.print("[dim]Switch with: memanto avatar switch <name-or-agent-id>[/dim]")


@avatar_app.command("current")
def avatar_current():
    """Show which avatar (agent) is currently active."""
    active_agent, _ = config_manager.get_active_session()
    if not active_agent:
        console.print("[yellow]No active agent — nobody is wearing an avatar.[/yellow]")
        return
    client = get_client()
    try:
        agent = client.get_agent(active_agent)
    except Exception as e:
        _error(f"Failed to load agent '{active_agent}': {e}")
    avatar = agent.get("avatar")
    if avatar:
        console.print(
            f"[green]{avatar_label(avatar)}[/green]  [dim](agent {active_agent})[/dim]"
        )
    else:
        console.print(
            f"[green]{active_agent}[/green] is active but has no avatar. "
            f"[dim]Give it one: memanto avatar set {active_agent} --preset john[/dim]"
        )


@avatar_app.command("switch")
def avatar_switch(
    name: str = typer.Argument(..., help="Avatar name (e.g. John) or agent ID"),
    duration_hours: int = typer.Option(
        6, "--hours", "-h", min=1, help="Activation duration in hours (default: 6)"
    ),
):
    """Switch to another avatar: ends the current session, activates its agent."""
    client = get_client()
    try:
        target = client.find_agent_by_avatar(name)
    except Exception as e:
        _error(f"Failed to look up avatar '{name}': {e}")
    if not target:
        _error(
            f"No avatar or agent named '{name}'.",
            hint="Run 'memanto avatar list' to see who is available.",
        )

    previous_id, _ = config_manager.get_active_session()
    if previous_id == target["agent_id"]:
        console.print(
            f"[green]{avatar_label(target.get('avatar'))}[/green] is already active "
            f"[dim](agent {target['agent_id']})[/dim]"
        )
        return

    previous_label = None
    previous_summary = None
    if previous_id:
        try:
            previous_label = avatar_label(client.get_agent(previous_id).get("avatar"))
        except Exception:
            previous_label = previous_id
        # End the previous session for real — it is marked terminated on disk
        # and yields a summary — instead of only dropping the local pointer.
        # No model call is involved. If the session is already gone, fall
        # back to clearing the pointer so the switch still goes through.
        try:
            previous_summary = client.deactivate_agent(previous_id)
        except SessionNotFoundError:
            previous_summary = None
        except Exception as e:
            _error(f"Failed to end session for '{previous_id}': {e}")
        config_manager.clear_active_session()

    try:
        result = client.activate_agent(target["agent_id"], duration_hours)
    except Exception as e:
        _error(f"Failed to activate agent '{target['agent_id']}': {e}")

    if previous_summary:
        console.print(
            f"[dim]Ended session of {previous_label} "
            f"({previous_summary.get('duration_hours', '?')} h)[/dim]"
        )
    if previous_label:
        console.print(f"[dim]{previous_label} → [/dim]", end="")
    console.print(
        f"[green]Switched to {avatar_label(target.get('avatar')) if target.get('avatar') else target['agent_id']}[/green]"
    )
    console.print(
        f"[dim]Agent: {target['agent_id']}  ·  expires: {result.get('expires_at', 'unknown')}[/dim]"
    )


@avatar_app.command("set")
def avatar_set(
    agent_id: str = typer.Argument(..., help="Agent that gets the avatar"),
    preset: str | None = typer.Option(
        None, "--preset", "-p", help="Start from a built-in preset (john, madeleine)"
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Display name"),
    provider: str | None = typer.Option(
        None, "--provider", help="Model provider: claude, openai or other"
    ),
    emoji: str | None = typer.Option(None, "--emoji", help="Glyph shown in the UI"),
    color: str | None = typer.Option(None, "--color", help="Accent colour #RRGGBB"),
):
    """Give an agent an avatar, from a preset and/or explicit values."""
    try:
        avatar = build_avatar(preset, name, provider, emoji, color)
    except ValueError as e:
        _error(str(e))
    if not avatar:
        _error(
            "Nothing to set.",
            hint="Pass --preset john|madeleine or --name <display name> [--provider claude|openai].",
        )

    client = get_client()
    try:
        agent = client.set_agent_avatar(agent_id, avatar)
    except Exception as e:
        msg = str(e)
        hint = (
            "Run 'memanto agent list' to see available agents."
            if "not found" in msg.lower()
            else None
        )
        _error(f"Failed to set avatar on '{agent_id}': {msg}", hint=hint)
    console.print(
        f"[green]Agent '{agent_id}' now appears as {avatar_label(agent.get('avatar'))}[/green]"
    )


@avatar_app.command("clear")
def avatar_clear(
    agent_id: str = typer.Argument(..., help="Agent whose avatar is removed"),
):
    """Remove the avatar from an agent (memories are untouched)."""
    client = get_client()
    try:
        client.set_agent_avatar(agent_id, None)
    except Exception as e:
        _error(f"Failed to clear avatar on '{agent_id}': {e}")
    console.print(f"[green]Avatar removed from agent '{agent_id}'.[/green]")
