"""Tests for the NotifyTool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.notify import NotifyTool


@pytest.fixture
def notify_tool():
    return NotifyTool()


class TestNotifyToolProperties:
    def test_name(self, notify_tool):
        assert notify_tool.name == "notify"

    def test_description(self, notify_tool):
        assert "email" in notify_tool.description.lower()

    def test_parameters(self, notify_tool):
        params = notify_tool.parameters
        assert "recipient" in params
        assert "subject" in params
        assert "body" in params

    def test_schema(self, notify_tool):
        schema = notify_tool.to_anthropic_schema()
        assert schema["name"] == "notify"
        required = schema["input_schema"]["required"]
        assert "recipient" in required
        assert "subject" in required
        assert "body" in required


class TestNotifyExecution:
    async def test_missing_recipient(self, notify_tool):
        result = await notify_tool.execute(recipient="", subject="Hi", body="Test")
        assert "Error" in result
        assert "recipient" in result.lower()

    async def test_missing_api_key(self, notify_tool):
        with patch("tools.notify.Config") as mock_config:
            mock_config.RESEND_API_KEY = ""
            result = await notify_tool.execute(
                recipient="user@example.com", subject="Hi", body="Test"
            )
        assert "Error" in result
        assert "RESEND_API_KEY" in result

    async def test_missing_from_address(self, notify_tool):
        with patch("tools.notify.Config") as mock_config:
            mock_config.RESEND_API_KEY = "re_123"
            mock_config.NOTIFY_EMAIL_FROM = ""
            result = await notify_tool.execute(
                recipient="user@example.com", subject="Hi", body="Test"
            )
        assert "Error" in result
        assert "NOTIFY_EMAIL_FROM" in result

    @patch("tools.notify.httpx.AsyncClient")
    @patch("tools.notify.Config")
    async def test_send_success(self, mock_config, mock_client_cls, notify_tool):
        mock_config.RESEND_API_KEY = "re_123"
        mock_config.NOTIFY_EMAIL_FROM = "agent@example.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await notify_tool.execute(
            recipient="user@example.com", subject="Hello", body="World"
        )

        assert "sent successfully" in result
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["to"] == ["user@example.com"]
        assert call_kwargs[1]["json"]["subject"] == "Hello"

    @patch("tools.notify.httpx.AsyncClient")
    @patch("tools.notify.Config")
    async def test_send_api_error(self, mock_config, mock_client_cls, notify_tool):
        mock_config.RESEND_API_KEY = "re_123"
        mock_config.NOTIFY_EMAIL_FROM = "agent@example.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await notify_tool.execute(
            recipient="user@example.com", subject="Hello", body="World"
        )

        assert "Error" in result
        assert "403" in result

    @patch("tools.notify.httpx.AsyncClient")
    @patch("tools.notify.Config")
    async def test_send_network_error(self, mock_config, mock_client_cls, notify_tool):
        mock_config.RESEND_API_KEY = "re_123"
        mock_config.NOTIFY_EMAIL_FROM = "agent@example.com"

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await notify_tool.execute(
            recipient="user@example.com", subject="Hello", body="World"
        )

        assert "Error" in result
        assert "Connection refused" in result
