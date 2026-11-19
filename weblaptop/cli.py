"""
Command-line argument parsing and execution dispatch.
"""

import argparse
import sys
from typing import List, Optional

from rich.text import Text

from weblaptop import __version__
from weblaptop.agent import Agent
from weblaptop.banner import render_status_line
from weblaptop.client import OllamaClient
from weblaptop.config import Config
from weblaptop.repl import run_repl
from weblaptop.theme import PALETTE, style
from weblaptop.ui import console, print_blank, print_notice, print_section


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="weblaptop",
        description=(
            "Terminal coding agent for your LAN. Runs a ReAct loop against\n"
            "an Ollama server; BUILD executes directly, PLAN asks before\n"
            "any mutation."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  weblaptop                                  interactive REPL (BUILD)
  weblaptop --plan                           interactive REPL, read-only
  weblaptop "inspect the current directory"  run one task, then exit
  weblaptop --plan "review the diff"         analyse without mutating
  weblaptop --effort high                    deeper reasoning per turn
  weblaptop --model qwen2.5-coder:latest     pin a model
        """,
    )

    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Task to run once, then exit. Omit for the interactive REPL.",
    )

    agent = parser.add_argument_group("agent")
    mode = agent.add_mutually_exclusive_group()
    mode.add_argument(
        "-y",
        "--yolo",
        action="store_true",
        help="Auto-approve every tool action (BUILD mode).",
    )
    mode.add_argument(
        "--plan",
        action="store_true",
        help="Start in PLAN mode: read freely, approve every mutation.",
    )
    agent.add_argument(
        "-e",
        "--effort",
        choices=["off", "low", "medium", "high", "max"],
        metavar="LEVEL",
        default=None,
        help="Reasoning depth: off, low, medium, high, max (default: medium).",
    )
    agent.add_argument(
        "--max-steps",
        type=int,
        metavar="N",
        default=30,
        help="ReAct step ceiling for one task (default: 30).",
    )

    connection = parser.add_argument_group("connection")
    connection.add_argument(
        "-s",
        "--server",
        metavar="URL",
        default=None,
        help="Ollama endpoint (default: http://192.168.100.106:11434).",
    )
    connection.add_argument(
        "-m",
        "--model",
        metavar="NAME",
        default=None,
        help="Model name (default: auto-detected from the server's list).",
    )
    connection.add_argument(
        "--cwd",
        metavar="DIR",
        default=None,
        help="Working directory for tools (default: current directory).",
    )
    connection.add_argument(
        "--models",
        action="store_true",
        help="List the models the server actually has, then exit.",
    )

    general = parser.add_argument_group("general")
    general.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser.parse_args(argv)


def list_server_models(config: Config, client: OllamaClient) -> int:
    """Print exactly the models the configured server reports."""
    is_online, _ping_ms, error = client.ping()
    if not is_online:
        print_notice(f"cannot reach {config.server_url}", "error", detail=error or "")
        return 1

    models, models_error = client.fetch_models()
    if models_error:
        print_notice(
            f"could not read models from {config.server_url}",
            "error",
            detail=models_error,
        )
        return 1

    if not models:
        print_notice(
            f"{config.server_url} is reachable but has no models",
            "warn",
            detail="pull one on that device, e.g. ollama pull qwen2.5:7b",
        )
        return 1

    print_section("models", f"{len(models)} on {config.server_url}")
    for name in models:
        line = Text.assemble(("  ", ""), (name, f"bold {style('text')}"))
        if name == config.model:
            line.append("   active", style=style("muted"))
        console.print(line)
    print_blank()
    return 0


def run_cli(argv: Optional[List[str]] = None) -> int:

    """Main CLI entrypoint."""
    args = parse_args(argv)

    # Build config
    config = Config()
    if args.server:
        config.server_url = args.server
    if args.model:
        config.model = args.model
    if args.effort:
        config.reasoning_effort = args.effort
    if args.cwd:
        config.cwd = args.cwd
    if args.max_steps:
        config.max_steps = args.max_steps
    if args.plan:
        config.mode = "plan"
        config.yolo = False
    else:
        config.yolo = bool(args.yolo)

    client = OllamaClient(server_url=config.server_url, timeout=config.timeout)

    # Ask the server what it has; never infer a model list.
    if args.models:
        return list_server_models(config, client)

    # If no task prompt was passed, enter interactive REPL
    if not args.prompt:
        run_repl(config=config, client=client)
        return 0

    # Non-interactive / single-task execution mode
    models: List[str] = []
    models_error: Optional[str] = None
    with console.status(f"  [{PALETTE['muted']}]connecting…[/{PALETTE['muted']}]", spinner="dots") as status:
        is_online, ping_ms, error = client.ping()
        if is_online:
            status.update(f"  [{PALETTE['muted']}]loading models…[/{PALETTE['muted']}]")
            models, models_error = client.fetch_models()

    if not is_online:
        print_notice(f"cannot reach {config.server_url}", "error", detail=error or "")
        return 1

    if not models:
        detail = models_error or "pull one on that device, e.g. ollama pull qwen2.5:7b"
        print_notice(f"{config.server_url} reports no models", "error", detail=detail)
        return 1

    if config.model not in models:
        print_notice(
            f"model {config.model} is not installed on {config.server_url}",
            "warn",
            detail=f"using {models[0]}; available: {', '.join(models)}",
        )
        config.model = models[0]

    render_status_line(
        console,
        config,
        ping_ms=ping_ms,
        is_online=True,
        error_msg=None,
    )

    agent = Agent(config=config, client=client)
    try:
        agent.run_task(args.prompt)
        return 0
    except KeyboardInterrupt:
        print_notice("task cancelled", "warn")
        return 130
    except Exception as e:
        print_notice(f"task failed: {e}", "error")
        return 1
