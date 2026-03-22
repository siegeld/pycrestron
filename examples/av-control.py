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


if __name__ == "__main__":
    cli()
