#!/usr/bin/env python3
"""CLI tool for managing memory sessions.

Usage:
    python tools/session_manager.py list
    python tools/session_manager.py show <session_id>
    python tools/session_manager.py delete <session_id>
    python tools/session_manager.py stats <session_id>
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.store import MemoryStore


def format_timestamp(ts: str) -> str:
    """Format ISO timestamp to readable string."""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts


def list_sessions(store: MemoryStore, limit: int = 50):
    """List all sessions."""
    sessions = store.list_sessions(limit=limit)

    if not sessions:
        print("No sessions found.")
        return

    print(f"\n📚 Sessions (showing {len(sessions)}):")
    print("=" * 100)
    print(f"{'Session ID':<38} {'Created':<20} {'Messages':<10} {'Summaries':<10}")
    print("-" * 100)

    for session in sessions:
        session_id = session["id"]
        created = format_timestamp(session["created_at"])
        msg_count = session["message_count"]
        summary_count = session["summary_count"]

        print(f"{session_id:<38} {created:<20} {msg_count:<10} {summary_count:<10}")

    print("=" * 100)


def show_session(store: MemoryStore, session_id: str, show_messages: bool = False):
    """Show detailed session information."""
    session_data = store.load_session(session_id)

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
    print(f"  Summaries: {len(session_data['summaries'])}")
    print(f"  Compression Count: {stats['compression_count']}")

    # Summaries
    if session_data["summaries"]:
        print(f"\n📝 Summaries ({len(session_data['summaries'])}):")
        for i, summary in enumerate(session_data["summaries"], 1):
            print(f"\n  Summary {i}:")
            print(f"    Original Messages: {summary.original_message_count}")
            print(f"    Original Tokens: {summary.original_tokens}")
            print(f"    Compressed Tokens: {summary.compressed_tokens}")
            print(f"    Compression Ratio: {summary.compression_ratio:.2f}")
            print(f"    Token Savings: {summary.token_savings}")
            print(f"    Preserved Messages: {len(summary.preserved_messages)}")
            print(f"    Summary Text: {summary.summary[:100]}...")

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


def show_stats(store: MemoryStore, session_id: str):
    """Show session statistics."""
    stats = store.get_session_stats(session_id)

    if not stats:
        print(f"❌ Session {session_id} not found")
        return

    print(f"\n📊 Session Statistics: {session_id}")
    print("=" * 80)

    print("\n⏰ Timing:")
    print(f"  Created: {format_timestamp(stats['created_at'])}")

    print("\n📨 Messages:")
    print(f"  System Messages: {stats['system_message_count']}")
    print(f"  Regular Messages: {stats['message_count']}")
    print(f"  Total Messages: {stats['system_message_count'] + stats['message_count']}")

    print("\n🗜️  Compression:")
    print(f"  Compressions: {stats['compression_count']}")
    print(f"  Summaries: {stats['summary_count']}")

    print("\n🎫 Tokens:")
    print(f"  Message Tokens: {stats['total_message_tokens']:,}")
    print(f"  Original Tokens (pre-compression): {stats['total_original_tokens']:,}")
    print(f"  Compressed Tokens: {stats['total_compressed_tokens']:,}")
    print(f"  Token Savings: {stats['token_savings']:,}")

    if stats["total_original_tokens"] > 0:
        savings_pct = (stats["token_savings"] / stats["total_original_tokens"]) * 100
        print(f"  Savings Percentage: {savings_pct:.1f}%")

    print("=" * 80)


def delete_session(store: MemoryStore, session_id: str, confirm: bool = False):
    """Delete a session."""
    if not confirm:
        response = input(f"Are you sure you want to delete session {session_id}? (yes/no): ")
        if response.lower() not in ["yes", "y"]:
            print("Cancelled.")
            return

    success = store.delete_session(session_id)
    if success:
        print(f"✅ Session {session_id} deleted")
    else:
        print(f"❌ Session {session_id} not found")


def main():
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
        "--db",
        type=str,
        default="data/memory.db",
        help="Path to database file (default: data/memory.db)",
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
    store = MemoryStore(db_path=args.db)

    # Execute command
    if args.command == "list":
        list_sessions(store, limit=args.limit)
    elif args.command == "show":
        show_session(store, args.session_id, show_messages=args.messages)
    elif args.command == "stats":
        show_stats(store, args.session_id)
    elif args.command == "delete":
        delete_session(store, args.session_id, confirm=args.yes)


if __name__ == "__main__":
    main()
