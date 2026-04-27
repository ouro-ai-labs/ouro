#!/usr/bin/env python3
"""Command-line interface for ouro."""

import os
import sys

# Add current directory to path to allow imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    """Main CLI entry point."""
    from ouro.interfaces.cli.main import main as run_main

    run_main()


if __name__ == "__main__":
    main()
