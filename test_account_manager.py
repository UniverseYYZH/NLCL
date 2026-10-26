"""账号持久化与微软登录辅助函数的单元测试（不访问网络）。"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from account_manager import (
    Account,
    AccountStore,
    create_offline_account,
)
from microsoft_auth import (
    DeviceCodeSession,
    DeviceCodeSlowDown,
    MicrosoftAuthError,
    poll_device_login,
    start_device_login,
)


class AccountManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"account-{uuid4().hex}"
        self.path = self.root / "accounts.json"
        self.store = AccountStore(self.path)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_offline_login_persists_and_restores(self) -> None:
        account = create_offline_account("TestPlayer")
        self.assertEqual(account.account_type, "offline")
        self.assertEqual(account.uuid, account.id)
        self.assertEqual(account.type_label, "离线账号")

        state = self.store.save_account(account)
        self.assertIsNotNone(state.active_account())
        self.assertTrue(self.path.is_file())

        restored = AccountStore(self.path)
        self.assertIsNotNone(restored.active_account)
        self.assertEqual(restored.active_account.name, "TestPlayer")
        self.assertEqual(restored.active_account.uuid, account.uuid)

    def test_microsoft_tokens_roundtrip(self) -> None:
        account = Account(
            id="11111111-1111-1111-1111-111111111111",
            account_type="microsoft",
            name="MSPlayer",
            uuid="11111111-1111-1111-1111-111111111111",
            access_token="access",
            refresh_token="refresh",
            skin_url="https://example.invalid/skin",
            client_id="client",
        )
        self.store.save_account(account)

        restored = AccountStore(self.path).active_account
        self.assertIsNotNone(restored)
        self.assertEqual(restored.access_token, "access")
        self.assertEqual(restored.refresh_token, "refresh")
        self.assertTrue(restored.is_microsoft)

    def test_switch_and_logout(self) -> None:
        first = create_offline_account("FirstPlayer")
        second = create_offline_account("SecondPlayer")
        self.store.save_account(first)
        self.store.save_account(second)

        state = self.store.set_active(first.id)
        self.assertEqual(state.active_id, first.id)

        state = self.store.remove_account(first.id)
        self.assertEqual(state.active_id, second.id)
        self.assertEqual(len(state.accounts), 1)
        self.assertEqual(AccountStore(self.path).active_account.name, "SecondPlayer")

    def test_recovers_pending_temp_file(self) -> None:
        """兼容保存中断：只剩 accounts.json.tmp 时也能恢复并提升为正式文件。"""

        account = create_offline_account("RecoveredUser")
        self.root.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(self.path.name + ".tmp")
        temp_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "active_id": account.id,
                    "accounts": [account.to_dict()],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        recovered = AccountStore(self.path)
        self.assertIsNotNone(recovered.active_account)
        self.assertEqual(recovered.active_account.name, "RecoveredUser")
        self.assertTrue(self.path.is_file())
        self.assertFalse(temp_path.exists())

    def test_invalid_offline_name(self) -> None:
        with self.assertRaises(ValueError):
            create_offline_account("a")
        with self.assertRaises(ValueError):
            create_offline_account("bad name!")

    def test_device_code_request_and_poll_states(self) -> None:
        response = {
            "device_code": "device-code-value",
            "user_code": "ABCD1234",
            "verification_uri": "https://www.microsoft.com/link",
            "expires_in": 900,
            "interval": 5,
        }
        with patch("microsoft_auth._post_form", return_value=response) as post:
            session = start_device_login()

        self.assertEqual(session.user_code, "ABCD1234")
        self.assertEqual(session.verification_uri, "https://www.microsoft.com/link")
        self.assertGreater(session.remaining_seconds(), 0)
        self.assertEqual(post.call_args.kwargs["params"], {"mtk": "zh-cn"})

        with patch(
            "microsoft_auth._post_form",
            return_value={"error": "authorization_pending"},
        ):
            self.assertIsNone(poll_device_login(session))

        with patch(
            "microsoft_auth._post_form",
            return_value={"access_token": "ms-token", "refresh_token": "refresh"},
        ):
            token = poll_device_login(session)
        self.assertEqual(token["access_token"], "ms-token")

        with patch(
            "microsoft_auth._post_form",
            return_value={"error": "slow_down"},
        ):
            with self.assertRaises(DeviceCodeSlowDown):
                poll_device_login(session)

        with patch(
            "microsoft_auth._post_form",
            return_value={"error": "expired_token"},
        ):
            with self.assertRaises(MicrosoftAuthError):
                poll_device_login(session)

    def test_device_code_session_countdown(self) -> None:
        session = DeviceCodeSession(
            device_code="device",
            user_code="CODE",
            verification_uri="https://www.microsoft.com/link",
            expires_in=900,
            interval=5,
        )
        self.assertGreater(session.remaining_seconds(), 0)
        self.assertLessEqual(session.remaining_seconds(), 900)


if __name__ == "__main__":
    unittest.main()
