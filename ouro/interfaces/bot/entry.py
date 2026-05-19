#!/usr/bin/env python3
"""Command-line shim for the ouro bot server (`ouro-bot`)."""


def main():
    """Bot CLI entry point."""
    from ouro.interfaces.bot.main import main as run_main

    run_main()


if __name__ == "__main__":
    main()
