"""NLMCL 的界面主题：颜色、间距和版本类型样式。

main.py（本地版本页）和 download_ui.py（下载弹窗）共用这里，
避免两处颜色、圆角、标签样式不一致。
"""

from __future__ import annotations

import flet as ft

# Flet 1.x 使用 ft.Padding / ft.Border 的类方法；
# Flet 0.28.x 使用 ft.padding / ft.border 模块函数。
PADDING = ft.Padding if hasattr(ft.Padding, "symmetric") else ft.padding
BORDER = ft.Border if hasattr(ft.Border, "all") else ft.border
BUTTON_LABEL_FIELD = "text" if hasattr(ft.FilledButton, "text") else "content"
TEXT_BUTTON_LABEL_FIELD = "text" if hasattr(ft.TextButton, "text") else "content"

# 整体使用浅色纸感背景 + 深绿色侧栏。
BG = "#F4F6F1"
CARD = "#FFFFFF"
SURFACE = "#F8FAF7"
BORDER_COLOR = "#E4E9E2"
TEXT = "#17231B"
MUTED = "#68776D"
FAINT = "#96A29A"
PRIMARY = "#2F6B4F"
PRIMARY_SOFT = "#E8F1EA"
SIDEBAR_BG = "#173B2B"
SIDEBAR_ACTIVE = "#285A41"
SIDEBAR_TEXT = "#F4FAF6"
SIDEBAR_MUTED = "#9DB5A6"

AMBER = "#966000"
AMBER_BG = "#FFF6E2"
AMBER_BORDER = "#EFDDB5"
SNAPSHOT = "#A85F00"
SNAPSHOT_BG = "#FFF1DA"
OLD = "#5D6B61"
OLD_BG = "#EFF2EE"

ERROR = "#B42318"
ERROR_BG = "#FEF3F2"
ERROR_BORDER = "#F3C7C3"

# 版本类型对应的展示样式：文字色、底色、图标。
TYPE_STYLES = {
    "release": (PRIMARY, PRIMARY_SOFT, ft.Icons.INVENTORY_2_OUTLINED),
    "snapshot": (SNAPSHOT, SNAPSHOT_BG, ft.Icons.SCIENCE_OUTLINED),
    "old_beta": (OLD, OLD_BG, ft.Icons.HISTORY),
    "old_alpha": (OLD, OLD_BG, ft.Icons.HISTORY),
}
