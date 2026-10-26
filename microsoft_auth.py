"""微软账号设备码登录（OAuth 2.0 Device Authorization Grant）。

流程：
1. POST /devicecode 获取 user_code 和 device_code；
2. 自动打开 https://www.microsoft.com/link，用户输入 user_code；
3. 后台按 interval 轮询 /token，直到用户授权；
4. 用微软 access_token 换取 Xbox Live / XSTS / Minecraft 凭证；
5. 返回账号资料和 refresh_token，由 AccountStore 持久化。

说明：minecraft-launcher-lib 8.0 没有暴露 device code API，因此设备码请求和
轮询按 Microsoft 官方协议实现；后续 Xbox Live / XSTS / Minecraft 交换使用
与 minecraft-launcher-lib 相同的接口。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import requests

# mcauth3 内置的公共 device-code 客户端 ID，专用于公开的设备码登录场景。
# 可通过环境变量 NLCL_MS_CLIENT_ID 替换为自己在 Azure 注册的公共客户端。
PUBLIC_DEVICE_CLIENT_ID = "4a07b708-b86d-4365-a55f-f4f23ecb85ab"
MICROSOFT_CLIENT_ID = os.environ.get(
    "NLCL_MS_CLIENT_ID",
    PUBLIC_DEVICE_CLIENT_ID,
)

MICROSOFT_SCOPE = "XboxLive.signin offline_access"
DEVICE_CODE_URL = (
    "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
)
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
DEVICE_VERIFY_URL = "https://www.microsoft.com/link"

XBL_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MINECRAFT_AUTH_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MINECRAFT_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
REQUEST_TIMEOUT = 30


class MicrosoftAuthError(Exception):
    """微软登录过程中的可展示错误。"""


class DeviceCodeSlowDown(MicrosoftAuthError):
    """轮询太快，需要增加间隔。"""


@dataclass(frozen=True, slots=True)
class DeviceCodeSession:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int
    message: str = ""
    client_id: str = MICROSOFT_CLIENT_ID
    started_at: float = field(default_factory=time.monotonic)

    def remaining_seconds(self) -> int:
        elapsed = int(time.monotonic() - self.started_at)
        return max(0, self.expires_in - elapsed)


@dataclass(frozen=True, slots=True)
class MicrosoftAccountData:
    account_id: str
    name: str
    access_token: str
    refresh_token: str
    skin_url: str = ""
    client_id: str = MICROSOFT_CLIENT_ID


def start_device_login() -> DeviceCodeSession:
    """向微软申请设备码。该函数会访问网络，调用方应放到后台线程。"""

    data = _post_form(
        DEVICE_CODE_URL,
        {
            "client_id": MICROSOFT_CLIENT_ID,
            "scope": MICROSOFT_SCOPE,
        },
        params={"mtk": "zh-cn"},
    )

    if data.get("error"):
        raise MicrosoftAuthError(_oauth_error(data, "无法获取微软设备码"))

    device_code = data.get("device_code")
    user_code = data.get("user_code")
    verification_uri = data.get("verification_uri") or DEVICE_VERIFY_URL
    if not isinstance(device_code, str) or not device_code:
        raise MicrosoftAuthError("微软没有返回 device_code")
    if not isinstance(user_code, str) or not user_code:
        raise MicrosoftAuthError("微软没有返回设备验证码")

    try:
        expires_in = max(60, int(data.get("expires_in") or 900))
        interval = max(5, int(data.get("interval") or 5))
    except (TypeError, ValueError):
        expires_in = 900
        interval = 5

    return DeviceCodeSession(
        device_code=device_code,
        user_code=user_code,
        verification_uri=str(verification_uri),
        expires_in=expires_in,
        interval=interval,
        message=str(data.get("message") or ""),
    )


def poll_device_login(session: DeviceCodeSession) -> dict | None:
    """轮询一次授权状态。

    返回 token 字典表示授权成功；返回 None 表示仍在等待用户。
    其他终态错误抛出 MicrosoftAuthError。
    """

    data = _post_form(
        TOKEN_URL,
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": session.client_id,
            "device_code": session.device_code,
        },
    )

    if data.get("access_token"):
        return data

    error = str(data.get("error") or "")
    if error == "authorization_pending":
        return None
    if error == "slow_down":
        raise DeviceCodeSlowDown("微软要求降低轮询频率")
    if error == "authorization_declined":
        raise MicrosoftAuthError("你取消了微软账号授权")
    if error == "expired_token":
        raise MicrosoftAuthError("设备验证码已过期，请重新获取")
    if error == "bad_verification_code":
        raise MicrosoftAuthError("设备验证码无效，请重新获取")

    raise MicrosoftAuthError(_oauth_error(data, "微软授权失败"))


def complete_device_login(token_data: dict) -> MicrosoftAccountData:
    """授权成功后，用微软 token 换取 Minecraft 凭证。调用方应放到后台线程。"""

    return _finish_microsoft_auth(token_data)


def refresh_microsoft_login(refresh_token: str) -> MicrosoftAccountData:
    """使用 refresh_token 刷新登录。调用方应放到后台线程。"""

    token_data = _post_form(
        TOKEN_URL,
        {
            "client_id": MICROSOFT_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": MICROSOFT_SCOPE,
        },
    )
    return _finish_microsoft_auth(token_data, fallback_refresh_token=refresh_token)


def _finish_microsoft_auth(
    token_data: dict,
    fallback_refresh_token: str = "",
) -> MicrosoftAccountData:
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token") or fallback_refresh_token
    if not isinstance(access_token, str) or not access_token:
        raise MicrosoftAuthError(_oauth_error(token_data, "微软没有返回 access_token"))

    xbl = _authenticate_xbox(access_token)
    xbl_token = xbl.get("Token")
    try:
        user_hash = xbl["DisplayClaims"]["xui"][0]["uhs"]
    except (KeyError, IndexError, TypeError):
        user_hash = None
    if not xbl_token or not user_hash:
        raise MicrosoftAuthError("Xbox Live 验证失败，请稍后重试")

    xsts = _request_json(
        "post",
        XSTS_URL,
        json={
            "Properties": {
                "SandboxId": "RETAIL",
                "UserTokens": [xbl_token],
            },
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        },
        headers={"x-xbl-contract-version": "1"},
    )
    xsts_token = xsts.get("Token")
    if not xsts_token:
        raise MicrosoftAuthError(_xsts_error(xsts))

    minecraft_auth = _request_json(
        "post",
        MINECRAFT_AUTH_URL,
        json={"identityToken": f"XBL3.0 x={user_hash};{xsts_token}"},
    )
    minecraft_access = minecraft_auth.get("access_token")
    if not minecraft_access:
        raise MicrosoftAuthError(_oauth_error(minecraft_auth, "Minecraft 服务验证失败"))

    profile = _request_json(
        "get",
        MINECRAFT_PROFILE_URL,
        headers={"Authorization": f"Bearer {minecraft_access}"},
    )
    if profile.get("error") == "NOT_FOUND":
        raise MicrosoftAuthError("该微软账号没有 Minecraft Java 版")
    if not profile.get("id") or not profile.get("name"):
        raise MicrosoftAuthError(_oauth_error(profile, "无法获取 Minecraft 账号资料"))

    skin_url = ""
    skins = profile.get("skins")
    if isinstance(skins, list) and skins and isinstance(skins[0], dict):
        skin_url = str(skins[0].get("url") or "")

    return MicrosoftAccountData(
        account_id=str(profile["id"]),
        name=str(profile["name"]),
        access_token=minecraft_access,
        refresh_token=str(refresh_token or ""),
        skin_url=skin_url,
        client_id=MICROSOFT_CLIENT_ID,
    )


def _authenticate_xbox(access_token: str) -> dict:
    """设备码 token 有时需要 d= 前缀，失败时回退为原始 token。"""

    last_response: dict = {}
    for ticket in (f"d={access_token}", access_token):
        last_response = _request_json(
            "post",
            XBL_URL,
            json={
                "Properties": {
                    "AuthMethod": "RPS",
                    "SiteName": "user.auth.xboxlive.com",
                    "RpsTicket": ticket,
                },
                "RelyingParty": "http://auth.xboxlive.com",
                "TokenType": "JWT",
            },
            headers={"x-xbl-contract-version": "1"},
        )
        if last_response.get("Token"):
            return last_response
    return last_response


def _post_form(url: str, data: dict, params: dict | None = None) -> dict:
    try:
        response = requests.post(
            url,
            data=data,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MicrosoftAuthError(f"网络请求失败：{exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise MicrosoftAuthError(
            f"服务器返回了无效数据（HTTP {response.status_code}）"
        ) from exc

    if not isinstance(payload, dict):
        raise MicrosoftAuthError("服务器返回格式不正确")
    return payload


def _request_json(method: str, url: str, **kwargs) -> dict:
    try:
        if method == "post":
            response = requests.post(url, timeout=REQUEST_TIMEOUT, **kwargs)
        else:
            response = requests.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise MicrosoftAuthError(f"网络请求失败：{exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise MicrosoftAuthError(
            f"服务器返回了无效数据（HTTP {response.status_code}）"
        ) from exc

    if not isinstance(data, dict):
        raise MicrosoftAuthError("服务器返回格式不正确")
    return data


def _oauth_error(data: dict, fallback: str) -> str:
    description = data.get("error_description") or data.get("error")
    return str(description) if description else fallback


def _xsts_error(data: dict) -> str:
    code = data.get("XErr")
    hints = {
        "2148916233": "该微软账号尚未创建 Xbox 档案",
        "2148916235": "该地区无法使用 Xbox Live",
        "2148916238": "该账号是未成年人账号，需要在家长账号下授权",
    }
    if code is not None:
        return hints.get(str(code), f"Xbox 安全验证失败（XErr={code}）")
    return "Xbox 安全验证失败"
