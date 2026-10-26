"""Windows 原生文件拖拽（Flet 0.28 没有外部文件 drop API）。

通过给 Flet 顶层窗口挂 DragAcceptFiles + WndProc 子类，把
WM_DROPFILES 转成 Flet 协程。失败时静默降级到文件选择器。
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import threading
from ctypes import wintypes
from pathlib import Path

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4

is_windows = os.name == "nt"


class WindowsFileDrop:
    def __init__(self, loop: asyncio.AbstractEventLoop, handler) -> None:
        self.loop = loop
        self.handler = handler
        self.hwnd = 0
        self._original_proc = None
        self._new_proc = None
        self._thread: threading.Thread | None = None
        self.available = False

    def start(self) -> None:
        if not is_windows or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._install,
            name="nlcl-windows-drop",
            daemon=True,
        )
        self._thread.start()

    def _install(self) -> None:
        import time

        hwnd = 0
        for _ in range(30):
            hwnd = _find_window_for_current_process()
            if hwnd:
                break
            time.sleep(0.5)
        if not hwnd:
            return
        self.hwnd = hwnd
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            user32.SetWindowLongPtrW.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_void_p,
            ]
            user32.CallWindowProcW.restype = ctypes.c_void_p
            user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
            shell32.DragQueryFileW.argtypes = [
                ctypes.c_void_p,
                wintypes.UINT,
                wintypes.LPWSTR,
                wintypes.UINT,
            ]
            shell32.DragQueryFileW.restype = wintypes.UINT
            shell32.DragFinish.argtypes = [ctypes.c_void_p]

            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_void_p,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )

            def wndproc(hwnd_value, message, wparam, lparam):
                if message == WM_DROPFILES:
                    try:
                        count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                        paths: list[str] = []
                        for index in range(count):
                            length = shell32.DragQueryFileW(wparam, index, None, 0)
                            buffer = ctypes.create_unicode_buffer(length + 1)
                            shell32.DragQueryFileW(wparam, index, buffer, length + 1)
                            if buffer.value:
                                paths.append(buffer.value)
                        shell32.DragFinish(wparam)
                        if paths:
                            asyncio.run_coroutine_threadsafe(
                                self.handler(paths),
                                self.loop,
                            )
                    except Exception:
                        pass
                    return 0
                return user32.CallWindowProcW(
                    self._original_proc,
                    hwnd_value,
                    message,
                    wparam,
                    lparam,
                )

            self._new_proc = WNDPROC(wndproc)
            self._original_proc = user32.SetWindowLongPtrW(
                hwnd,
                GWLP_WNDPROC,
                ctypes.cast(self._new_proc, ctypes.c_void_p),
            )
            shell32.DragAcceptFiles(hwnd, True)
            self.available = True
        except Exception:
            self.available = False


def _find_window_for_current_process() -> int:
    """找到当前 Python/Flet 进程的可见顶层窗口。"""

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    pid = os.getpid()
    candidates: list[tuple[int, int, str]] = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        window_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value != pid:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)
        class_name = class_buffer.value
        if not title and "FLUTTER" not in class_name.upper():
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = max(rect.right - rect.left, 0) * max(rect.bottom - rect.top, 0)
        candidates.append((area, int(hwnd), title))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    if not candidates:
        return 0
    candidates.sort(reverse=True)
    return candidates[0][1]


def existing_files(paths: list[str]) -> list[Path]:
    return [Path(item) for item in paths if Path(item).is_file()]
