#!/usr/bin/env python3
"""AV Control CLI — control sources, TV, and screen via Crestron.

Usage:
    python av-control.py roku
    python av-control.py tv-on
    python av-control.py screen-down
    python av-control.py --help
"""

from __future__ import annotations

import asyncio
import sys
import os

import click

# Add src/ to path for local dev
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pycrestron import CIPConnection, CrestronClient
from pycrestron.protocol import CIPPacketType, parse_cresnet_signals, parse_extended_data_signals

# ---------------------------------------------------------------
# Connection config
# ---------------------------------------------------------------
HOST = "10.11.4.155"
IP_ID = 0x1B
USERNAME = "admin"
PASSWORD = "password"

# ---------------------------------------------------------------
# Join map
# ---------------------------------------------------------------
SOURCES = {
    "roku": 20,
    "apple": 21,
    "shield": 22,
    "bluray": 24,
    "firestick": 25,
    "chromecast": 26,
    "dante": 27,
}

COMMANDS = {
    "tv-on": 30,
    "tv-off": 31,
    "screen-down": 40,
    "screen-up": 41,
}

ALL_ACTIONS = {**SOURCES, **COMMANDS}


def action_names() -> list[str]:
    return list(ALL_ACTIONS.keys())


async def do_press(action: str) -> None:
    join = ALL_ACTIONS[action]
    async with CrestronClient(HOST, IP_ID, username=USERNAME, password=PASSWORD, auto_reconnect=False) as client:
        await client.press(join)
        click.echo(click.style(f"  Pressed join {join}", fg="green"))


async def do_multi(actions: list[str]) -> None:
    async with CrestronClient(HOST, IP_ID, username=USERNAME, password=PASSWORD, auto_reconnect=False) as client:
        for action in actions:
            join = ALL_ACTIONS[action]
            await client.press(join)
            click.echo(click.style(f"  Pressed join {join} ({action})", fg="green"))
            await asyncio.sleep(0.3)


# ---------------------------------------------------------------
# CLI
# ---------------------------------------------------------------

class ActionType(click.ParamType):
    name = "action"

    def get_metavar(self, param):
        return "[" + "|".join(action_names()) + "]"

    def shell_complete(self, ctx, param, incomplete):
        from click.shell_completion import CompletionItem
        return [
            CompletionItem(name)
            for name in action_names()
            if name.startswith(incomplete)
        ]

    def convert(self, value, param, ctx):
        if value not in ALL_ACTIONS:
            self.fail(
                f"Unknown action '{value}'. Choose from: {', '.join(action_names())}",
                param, ctx,
            )
        return value


ACTION = ActionType()


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """AV Control — Crestron source selection, TV power, and screen control.

    \b
    Sources:  roku, apple, shield, bluray, firestick, chromecast, dante
    TV:       tv-on, tv-off
    Screen:   screen-down, screen-up
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("action", type=ACTION)
def press(action):
    """Press a single button (momentary)."""
    click.echo(f"  {action}")
    asyncio.run(do_press(action))


@cli.command()
@click.argument("actions", type=ACTION, nargs=-1, required=True)
def sequence(actions):
    """Press multiple buttons in sequence with 300ms between each."""
    click.echo(f"  Sequence: {' → '.join(actions)}")
    asyncio.run(do_multi(list(actions)))


# --- Shortcut commands for every action ---

@cli.command()
def roku():
    """Select Roku source."""
    asyncio.run(do_press("roku"))

@cli.command()
def apple():
    """Select Apple TV source."""
    asyncio.run(do_press("apple"))

@cli.command()
def shield():
    """Select NVIDIA Shield source."""
    asyncio.run(do_press("shield"))

@cli.command()
def bluray():
    """Select Blu-ray source."""
    asyncio.run(do_press("bluray"))

@cli.command()
def firestick():
    """Select Fire Stick source."""
    asyncio.run(do_press("firestick"))

@cli.command()
def chromecast():
    """Select Chromecast source."""
    asyncio.run(do_press("chromecast"))

@cli.command()
def dante():
    """Select Dante audio source."""
    asyncio.run(do_press("dante"))

@cli.command("tv-on")
def tv_on():
    """Turn TV on."""
    asyncio.run(do_press("tv-on"))

@cli.command("tv-off")
def tv_off():
    """Turn TV off."""
    asyncio.run(do_press("tv-off"))

@cli.command("screen-down")
def screen_down():
    """Lower projection screen."""
    asyncio.run(do_press("screen-down"))

@cli.command("screen-up")
def screen_up():
    """Raise projection screen."""
    asyncio.run(do_press("screen-up"))


# --- Combo macros ---

@cli.command()
@click.argument("source", type=click.Choice(list(SOURCES.keys())))
def watch(source):
    """Turn on TV, lower screen, select source.

    \b
    Example: av-control.py watch roku
    """
    click.echo(f"  Starting: TV on → screen down → {source}")
    asyncio.run(do_multi(["tv-on", "screen-down", source]))


@cli.command()
def off():
    """Turn everything off (TV off, screen up)."""
    click.echo("  Shutting down: TV off → screen up")
    asyncio.run(do_multi(["tv-off", "screen-up"]))


@cli.command("list")
def list_actions():
    """List all available actions and their join numbers."""
    click.echo("\n  Sources:")
    for name, join in SOURCES.items():
        click.echo(f"    {name:14s} join {join}")
    click.echo("\n  Commands:")
    for name, join in COMMANDS.items():
        click.echo(f"    {name:14s} join {join}")
    click.echo()


# ---------------------------------------------------------------
# Snoop — live traffic monitor
# ---------------------------------------------------------------

PACKET_NAMES = {v: v.name for v in CIPPacketType}

DATA_TYPES = {
    CIPPacketType.DATA,
    CIPPacketType.CRESNET_DATA,
    CIPPacketType.EXTENDED_DATA,
}


async def do_snoop(raw: bool) -> None:
    from pycrestron.auth import fetch_auth_token
    from datetime import datetime

    click.echo(click.style(f"  Connecting to {HOST} IP ID 0x{IP_ID:02x}...", fg="cyan"))
    token = await fetch_auth_token(HOST, USERNAME, PASSWORD)

    async with CIPConnection(HOST, IP_ID, port=49200) as conn:
        click.echo(click.style("  Connected — snooping all traffic (Ctrl+C to stop)\n", fg="green"))

        def on_packet(ptype: int, payload: bytes) -> None:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            name = PACKET_NAMES.get(ptype, f"0x{ptype:02x}")

            # Parse signal data from DATA packets
            if ptype in DATA_TYPES and len(payload) > 2:
                cresnet = payload[2:]  # skip handle
                if ptype == CIPPacketType.EXTENDED_DATA:
                    events = parse_extended_data_signals(cresnet)
                else:
                    events = parse_cresnet_signals(cresnet)

                for e in events:
                    stype = e.signal_type.value
                    val = e.value
                    if stype == "analog":
                        pct = f" ({val / 65535 * 100:.0f}%)"
                    else:
                        pct = ""
                    color = {"digital": "yellow", "analog": "cyan", "serial": "magenta"}[stype]
                    click.echo(f"  {ts}  {click.style(f'{stype:8s}', fg=color)} join={e.join:<5d} value={val}{pct}")

                if raw and events:
                    click.echo(click.style(f"           raw: {payload.hex()}", fg="bright_black"))
            elif raw:
                click.echo(f"  {ts}  {click.style(name, fg='bright_black'):20s} len={len(payload):4d}  {payload[:32].hex()}")
            elif ptype not in (CIPPacketType.HEARTBEAT, CIPPacketType.HEARTBEAT_RESPONSE):
                click.echo(f"  {ts}  {click.style(name, fg='bright_black'):20s} len={len(payload)}")

        conn.on_packet(on_packet)

        try:
            while conn.connected:
                await asyncio.sleep(0.5)
        except KeyboardInterrupt:
            pass

    click.echo(click.style("\n  Disconnected.", fg="red"))


@cli.command()
@click.option("--raw", is_flag=True, help="Show raw hex for all packets including heartbeats.")
def snoop(raw):
    """Live monitor of all CIP traffic — signals, packets, everything.

    \b
    Shows real-time digital, analog, and serial signal changes.
    Use --raw to see hex dumps of every packet.
    """
    try:
        asyncio.run(do_snoop(raw))
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------

INTERACTIVE_COMMANDS: dict[str, str] = {}  # populated in _build_help


def _build_help() -> str:
    global INTERACTIVE_COMMANDS
    INTERACTIVE_COMMANDS = {
        "connect": "Connect to the Crestron processor",
        "disconnect": "Disconnect from the processor",
        "status": "Show connection status",
        **{name: f"Select {name} source (join {join})" for name, join in SOURCES.items()},
        "tv-on": f"Turn TV on (join {COMMANDS['tv-on']})",
        "tv-off": f"Turn TV off (join {COMMANDS['tv-off']})",
        "screen-down": f"Lower screen (join {COMMANDS['screen-down']})",
        "screen-up": f"Raise screen (join {COMMANDS['screen-up']})",
        "watch <source>": "TV on + screen down + select source",
        "off": "TV off + screen up",
        "press <join>": "Press a raw digital join number",
        "set-analog <join> <value>": "Set analog join (0-65535)",
        "set-serial <join> <text>": "Set serial join text",
        "get <d|a|s> <join>": "Get cached value for a join",
        "snoop": "Toggle live signal display on/off",
        "list": "List all named actions and joins",
        "help": "Show this help",
        "quit": "Disconnect and exit",
    }
    lines = ["\n  Commands:\n"]
    for cmd, desc in INTERACTIVE_COMMANDS.items():
        lines.append(f"    {cmd:30s} {desc}")
    lines.append("")
    return "\n".join(lines)


HELP_TEXT = _build_help()

# All words that can appear as the first token
_COMPLETIONS = sorted(set(
    list(SOURCES.keys())
    + list(COMMANDS.keys())
    + ["connect", "disconnect", "status", "watch", "off",
       "press", "set-analog", "set-serial", "get", "snoop",
       "list", "help", "quit", "exit"]
))


def _make_completer():
    from prompt_toolkit.completion import Completer, Completion

    class AVCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            parts = text.split()

            if len(parts) <= 1:
                prefix = parts[0] if parts else ""
                for word in _COMPLETIONS:
                    if word.startswith(prefix):
                        yield Completion(word, start_position=-len(prefix))
            elif parts[0] == "watch" and len(parts) == 2:
                prefix = parts[1]
                for s in SOURCES:
                    if s.startswith(prefix):
                        yield Completion(s, start_position=-len(prefix))
            elif parts[0] == "get" and len(parts) == 2:
                prefix = parts[1]
                for t in ("d", "a", "s"):
                    if t.startswith(prefix):
                        yield Completion(t, start_position=-len(prefix))

    return AVCompleter()


async def interactive_loop() -> None:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.patch_stdout import patch_stdout
    from datetime import datetime

    session: PromptSession = PromptSession(
        completer=_make_completer(),
        complete_while_typing=True,
    )

    client: CrestronClient | None = None
    snooping = False

    def _snoop_callback(ptype: int, payload: bytes) -> None:
        if not snooping:
            return
        if ptype not in DATA_TYPES or len(payload) <= 2:
            return
        cresnet = payload[2:]
        if ptype == CIPPacketType.EXTENDED_DATA:
            events = parse_extended_data_signals(cresnet)
        else:
            events = parse_cresnet_signals(cresnet)
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        for e in events:
            stype = e.signal_type.value
            val = e.value
            extra = f" ({val / 65535 * 100:.0f}%)" if stype == "analog" else ""
            color = {"digital": "yellow", "analog": "cyan", "serial": "magenta"}[stype]
            click.echo(f"  {ts}  {click.style(f'{stype:8s}', fg=color)} join={e.join:<5d} value={val}{extra}")

    def _prompt_text():
        if client and client.connected:
            return HTML("<ansigreen>av</ansigreen>> ")
        return HTML("<ansired>av</ansired>> ")

    click.echo(click.style("\n  AV Control — Interactive Mode", bold=True))
    click.echo(click.style(f"  Processor: {HOST}  IP ID: 0x{IP_ID:02x}", fg="cyan"))
    click.echo('  Type "connect" to start, "help" for commands.\n')

    while True:
        try:
            with patch_stdout():
                line = await session.prompt_async(_prompt_text)
        except (EOFError, KeyboardInterrupt):
            break

        line = line.strip()
        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()
        args = parts[1:]

        try:
            # --- Connection ---
            if cmd == "connect":
                if client and client.connected:
                    click.echo(click.style("  Already connected.", fg="yellow"))
                    continue
                click.echo(click.style(f"  Connecting to {HOST}...", fg="cyan"))
                client = CrestronClient(
                    HOST, IP_ID,
                    username=USERNAME, password=PASSWORD,
                    auto_reconnect=True,
                    reconnect_interval=5.0,
                )
                client.on_connect = lambda: click.echo(click.style("  Connected.", fg="green"))
                client.on_disconnect = lambda: click.echo(click.style("  Disconnected.", fg="red"))
                await client.start()
                # Register snoop callback on the raw connection
                client.connection.on_packet(_snoop_callback)

            elif cmd == "disconnect":
                if client:
                    await client.stop()
                    client = None
                    click.echo(click.style("  Disconnected.", fg="red"))
                else:
                    click.echo("  Not connected.")

            elif cmd == "status":
                if client and client.connected:
                    click.echo(click.style(f"  Connected to {HOST} (IP ID 0x{IP_ID:02x})", fg="green"))
                else:
                    click.echo(click.style("  Not connected.", fg="red"))

            # --- Named actions (sources + commands) ---
            elif cmd in ALL_ACTIONS:
                if not client or not client.connected:
                    click.echo(click.style("  Not connected. Type 'connect' first.", fg="red"))
                    continue
                join = ALL_ACTIONS[cmd]
                await client.press(join)
                click.echo(click.style(f"  {cmd} (join {join})", fg="green"))

            # --- Watch macro ---
            elif cmd == "watch":
                if not args:
                    click.echo(f"  Usage: watch <{'|'.join(SOURCES.keys())}>")
                    continue
                source = args[0].lower()
                if source not in SOURCES:
                    click.echo(click.style(f"  Unknown source: {source}", fg="red"))
                    continue
                if not client or not client.connected:
                    click.echo(click.style("  Not connected. Type 'connect' first.", fg="red"))
                    continue
                for action in ["tv-on", "screen-down", source]:
                    join = ALL_ACTIONS[action]
                    await client.press(join)
                    click.echo(click.style(f"  {action} (join {join})", fg="green"))
                    await asyncio.sleep(0.3)

            # --- Off macro ---
            elif cmd == "off":
                if not client or not client.connected:
                    click.echo(click.style("  Not connected. Type 'connect' first.", fg="red"))
                    continue
                for action in ["tv-off", "screen-up"]:
                    join = ALL_ACTIONS[action]
                    await client.press(join)
                    click.echo(click.style(f"  {action} (join {join})", fg="green"))
                    await asyncio.sleep(0.3)

            # --- Raw press ---
            elif cmd == "press":
                if not args:
                    click.echo("  Usage: press <join_number>")
                    continue
                if not client or not client.connected:
                    click.echo(click.style("  Not connected.", fg="red"))
                    continue
                join = int(args[0])
                await client.press(join)
                click.echo(click.style(f"  Pressed join {join}", fg="green"))

            # --- Set analog ---
            elif cmd == "set-analog":
                if len(args) < 2:
                    click.echo("  Usage: set-analog <join> <value 0-65535>")
                    continue
                if not client or not client.connected:
                    click.echo(click.style("  Not connected.", fg="red"))
                    continue
                join, value = int(args[0]), int(args[1])
                await client.set_analog(join, value)
                click.echo(click.style(f"  Analog {join} = {value} ({value/65535*100:.0f}%)", fg="green"))

            # --- Set serial ---
            elif cmd == "set-serial":
                if len(args) < 2:
                    click.echo("  Usage: set-serial <join> <text>")
                    continue
                if not client or not client.connected:
                    click.echo(click.style("  Not connected.", fg="red"))
                    continue
                join = int(args[0])
                text = " ".join(args[1:])
                await client.set_serial(join, text)
                click.echo(click.style(f"  Serial {join} = \"{text}\"", fg="green"))

            # --- Get cached ---
            elif cmd == "get":
                if len(args) < 2:
                    click.echo("  Usage: get <d|a|s> <join>")
                    continue
                if not client:
                    click.echo(click.style("  Not connected.", fg="red"))
                    continue
                sig_type, join = args[0].lower(), int(args[1])
                if sig_type == "d":
                    val = client.get_digital(join)
                elif sig_type == "a":
                    val = client.get_analog(join)
                elif sig_type == "s":
                    val = client.get_serial(join)
                else:
                    click.echo("  Type must be d (digital), a (analog), or s (serial).")
                    continue
                if val is None:
                    click.echo(f"  No cached value for join {join}.")
                else:
                    click.echo(f"  {val}")

            # --- Snoop toggle ---
            elif cmd == "snoop":
                snooping = not snooping
                state = click.style("ON", fg="green") if snooping else click.style("OFF", fg="red")
                click.echo(f"  Live signal display: {state}")

            # --- List ---
            elif cmd == "list":
                click.echo("\n  Sources:")
                for name, join in SOURCES.items():
                    click.echo(f"    {name:14s} join {join}")
                click.echo("\n  Commands:")
                for name, join in COMMANDS.items():
                    click.echo(f"    {name:14s} join {join}")
                click.echo()

            # --- Help ---
            elif cmd == "help":
                click.echo(HELP_TEXT)

            # --- Quit ---
            elif cmd in ("quit", "exit"):
                break

            else:
                click.echo(click.style(f"  Unknown command: {cmd}. Type 'help' for commands.", fg="red"))

        except Exception as exc:
            click.echo(click.style(f"  Error: {exc}", fg="red"))

    # Cleanup
    if client:
        await client.stop()
    click.echo("  Bye.")


@cli.command("interactive")
def interactive():
    """Interactive mode — persistent connection with command prompt.

    \b
    Connect once, then issue commands interactively with
    tab-completion, live signal snooping, and raw join access.
    """
    asyncio.run(interactive_loop())


if __name__ == "__main__":
    cli()
