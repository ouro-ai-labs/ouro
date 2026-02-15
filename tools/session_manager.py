#!/usr/bin/env python3
"""CLI tool for managing memory sessions.

Usage:
    python tools/session_manager.py list
    python tools/session_manager.py show <session_id>
    python tools/session_manager.py delete <session_id>
    python tools/session_manager.py stats <session_id>
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.store import YamlFileMemoryStore
from utils.runtime import get_sessions_dir


def format_timestamp(ts: str) -> str:
    """Format ISO timestamp to readable string."""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts


async def list_sessions(store: YamlFileMemoryStore, limit: int = 50):
    """List all sessions."""
    sessions = await store.list_sessions(limit=limit)

    if not sessions:
        print("No sessions found.")
        return

    print(f"\n📚 Sessions (showing {len(sessions)}):")
    print("=" * 100)
    print(f"{'Session ID':<38} {'Updated':<20} {'Messages':<10} {'Preview':<30}")
    print("-" * 100)

    for session in sessions:
        session_id = session["id"]
        updated = format_timestamp(session.get("updated_at", session.get("created_at", "")))
        msg_count = session["message_count"]
        preview = session.get("preview", "")[:30]

        print(f"{session_id:<38} {updated:<20} {msg_count:<10} {preview:<30}")

    print("=" * 100)


async def show_session(store: YamlFileMemoryStore, session_id: str, show_messages: bool = False):
    """Show detailed session information."""
    session_data = await store.load_session(session_id)

    if not session_data:
        print(f"❌ Session {session_id} not found")
        return

    stats = session_data["stats"]

    print(f"\n📋 Session: {session_id}")
    print("=" * 100)

    # Stats
    print("\n📊 Statistics:")
    print(f"  Created: {format_timestamp(stats['created_at'])}")
    print(f"  System Messages: {len(session_data['system_messages'])}")
    print(f"  Messages: {len(session_data['messages'])}")

    # Messages (if requested)
    if show_messages and session_data["messages"]:
        print(f"\n💬 Messages ({len(session_data['messages'])}):")
        for i, msg in enumerate(session_data["messages"], 1):
            role = msg.role
            content = str(msg.content)
            if len(content) > 100:
                content = content[:100] + "..."

            print(f"\n  Message {i} [{role}]:")
            print(f"    {content}")

    print("=" * 100)


async def show_stats(store: YamlFileMemoryStore, session_id: str):
    """Show session statistics."""
    stats = await store.get_session_stats(session_id)

    if not stats:
        print(f"❌ Session {session_id} not found")
        return

    print(f"\n📊 Session Statistics: {session_id}")
    print("=" * 80)

    print("\n⏰ Timing:")
    print(f"  Created: {format_timestamp(stats['created_at'])}")
    if stats.get("updated_at"):
        print(f"  Updated: {format_timestamp(stats['updated_at'])}")

    print("\n📨 Messages:")
    print(f"  System Messages: {stats['system_message_count']}")
    print(f"  Regular Messages: {stats['message_count']}")
    print(f"  Total Messages: {stats['system_message_count'] + stats['message_count']}")

    print("\n🎫 Tokens:")
    print(f"  Message Tokens: {stats['total_message_tokens']:,}")

    print("=" * 80)


async def delete_session(store: YamlFileMemoryStore, session_id: str, confirm: bool = False):
    """Delete a session."""
    if not confirm:
        response = input(f"Are you sure you want to delete session {session_id}? (yes/no): ")
        if response.lower() not in ["yes", "y"]:
            print("Cancelled.")
            return

    success = await store.delete_session(session_id)
    if success:
        print(f"✅ Session {session_id} deleted")
    else:
        print(f"❌ Session {session_id} not found")


async def main():
    parser = argparse.ArgumentParser(
        description="Manage memory sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  List all sessions:
    python tools/session_manager.py list

  Show session details:
    python tools/session_manager.py show <session_id>

  Show session with messages:
    python tools/session_manager.py show <session_id> --messages

  Show session statistics:
    python tools/session_manager.py stats <session_id>

  Delete a session:
    python tools/session_manager.py delete <session_id>
        """,
    )

    parser.add_argument(
        "--sessions-dir",
        type=str,
        default=None,
        help="Path to sessions directory (default: .ouro/sessions/)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # List command
    list_parser = subparsers.add_parser("list", help="List all sessions")
    list_parser.add_argument("--limit", type=int, default=50, help="Max sessions to show")

    # Show command
    show_parser = subparsers.add_parser("show", help="Show session details")
    show_parser.add_argument("session_id", help="Session ID")
    show_parser.add_argument("--messages", action="store_true", help="Show messages")

    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Show session statistics")
    stats_parser.add_argument("session_id", help="Session ID")

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a session")
    delete_parser.add_argument("session_id", help="Session ID")
    delete_parser.add_argument("--yes", action="store_true", help="Skip confirmation")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Initialize store
    sessions_dir = args.sessions_dir if args.sessions_dir else get_sessions_dir()
    store = YamlFileMemoryStore(sessions_dir=sessions_dir)

    # Execute command
    if args.command == "list":
        await list_sessions(store, limit=args.limit)
    elif args.command == "show":
        await show_session(store, args.session_id, show_messages=args.messages)
    elif args.command == "stats":
        await show_stats(store, args.session_id)
    elif args.command == "delete":
        await delete_session(store, args.session_id, confirm=args.yes)


if __name__ == "__main__":
    asyncio.run(main())
