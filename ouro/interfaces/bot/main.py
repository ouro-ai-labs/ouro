"""Entry point for the ouro bot server."""

import argparse
import asyncio
import importlib.metadata
import warnings

from rich.console import Console

from ouro.config import Config
from ouro.core.log import setup_logger
from ouro.core.runtime import ensure_runtime_dirs
from ouro.interfaces.bot.server import run_bot
from ouro.interfaces.tui import terminal_ui

warnings.filterwarnings("ignore", message="Pydantic serializer warnings.*", category=UserWarning)


def main():
    """Bot CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run ouro as a bot server, receiving messages via IM channels (Lark, Slack, WeChat, etc.)"
    )

    try:
        version = importlib.metadata.version("ouro-ai")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"
    parser.add_argument("--version", "-V", action="version", version=f"ouro-bot {version}")

    parser.add_argument(
        "--model",
        "-m",
        type=str,
        help="Model to use (LiteLLM model ID, e.g. openai/gpt-4o)",
    )

    args = parser.parse_args()

    # Bot is a long-running daemon — always enable file logging and suppress
    # interactive Rich UI.
    terminal_ui.console = Console(quiet=True)
    ensure_runtime_dirs(create_logs=True)
    setup_logger()

    try:
        Config.validate()
    except ValueError as e:
        terminal_ui.print_error(str(e), title="Configuration Error")
        return

    asyncio.run(run_bot(model_id=args.model))


if __name__ == "__main__":
    main()
