"""Tests for bot.soul — soul file loading and defaults."""

from __future__ import annotations

from ouro.interfaces.bot.soul import _DEFAULT_SOUL, ensure_soul_file, load_soul


def test_ensure_soul_file_creates_default(tmp_path, monkeypatch):
    """ensure_soul_file creates soul.md with default content when missing."""
    soul_path = tmp_path / "bot" / "soul.md"
    monkeypatch.setattr("ouro.interfaces.bot.soul._BOT_DIR", str(tmp_path / "bot"))
    monkeypatch.setattr("ouro.interfaces.bot.soul._SOUL_FILE", str(soul_path))

    assert not soul_path.exists()
    ensure_soul_file()
    assert soul_path.exists()
    assert soul_path.read_text(encoding="utf-8") == _DEFAULT_SOUL


def test_ensure_soul_file_does_not_overwrite(tmp_path, monkeypatch):
    """ensure_soul_file does not overwrite an existing file."""
    bot_dir = tmp_path / "bot"
    bot_dir.mkdir()
    soul_path = bot_dir / "soul.md"
    soul_path.write_text("custom soul", encoding="utf-8")

    monkeypatch.setattr("ouro.interfaces.bot.soul._BOT_DIR", str(bot_dir))
    monkeypatch.setattr("ouro.interfaces.bot.soul._SOUL_FILE", str(soul_path))

    ensure_soul_file()
    assert soul_path.read_text(encoding="utf-8") == "custom soul"


def test_load_soul_returns_content(tmp_path, monkeypatch):
    """load_soul returns file content when file exists."""
    bot_dir = tmp_path / "bot"
    bot_dir.mkdir()
    soul_path = bot_dir / "soul.md"
    soul_path.write_text("# My Soul\nBe helpful.", encoding="utf-8")

    monkeypatch.setattr("ouro.interfaces.bot.soul._BOT_DIR", str(bot_dir))
    monkeypatch.setattr("ouro.interfaces.bot.soul._SOUL_FILE", str(soul_path))

    result = load_soul()
    assert result == "# My Soul\nBe helpful."


def test_load_soul_returns_none_for_empty(tmp_path, monkeypatch):
    """load_soul returns None when file is empty."""
    bot_dir = tmp_path / "bot"
    bot_dir.mkdir()
    soul_path = bot_dir / "soul.md"
    soul_path.write_text("   \n  ", encoding="utf-8")

    monkeypatch.setattr("ouro.interfaces.bot.soul._BOT_DIR", str(bot_dir))
    monkeypatch.setattr("ouro.interfaces.bot.soul._SOUL_FILE", str(soul_path))

    assert load_soul() is None


def test_load_soul_creates_default_if_missing(tmp_path, monkeypatch):
    """load_soul creates default soul.md and returns its content."""
    soul_path = tmp_path / "bot" / "soul.md"
    monkeypatch.setattr("ouro.interfaces.bot.soul._BOT_DIR", str(tmp_path / "bot"))
    monkeypatch.setattr("ouro.interfaces.bot.soul._SOUL_FILE", str(soul_path))

    result = load_soul()
    assert result is not None
    assert "Core Truths" in result
    assert soul_path.exists()
