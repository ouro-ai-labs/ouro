"""Integration test: send a real email via Resend.

Requires RESEND_API_KEY and NOTIFY_EMAIL_FROM in .aloop/config.
Run with: RUN_INTEGRATION_TESTS=1 python -m pytest test/test_notify_integration.py -v
"""

import os

import pytest

from tools.notify import NotifyTool

pytestmark = pytest.mark.integration


@pytest.fixture
def notify_tool():
    return NotifyTool()


@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="Set RUN_INTEGRATION_TESTS=1 to run",
)
async def test_send_real_email(notify_tool):
    result = await notify_tool.execute(
        recipient="luoyixin6688@gmail.com",
        subject="AgenticLoop NotifyTool Test",
        body="This is a test email sent from the AgenticLoop NotifyTool integration test.",
    )
    print(result)
    assert "sent successfully" in result
