from launcher_core import install_version, start_mc
from account_manager import add_account

# ===== 这里你可以改参数 =====
game_root = r"D:\MC_Game"
ver = "1.20.1"
user = "TestPlayer"
java_path = r"C:\Program Files\Java\jdk-17\bin\java.exe" # 改成你自己java17路径
# =========================

add_account(user)
install_version(ver, game_root)
proc = start_mc(ver, game_root, user, java_path)
