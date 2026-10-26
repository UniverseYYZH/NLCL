import minecraft_launcher_lib
import subprocess
import threading
import queue
from typing import Optional

log_queue = queue.Queue()

def get_version_list():
    return minecraft_launcher_lib.utils.get_version_list()

def install_version(version_id: str, game_dir: str):
    minecraft_launcher_lib.install.install_minecraft_version(
        version_id,
        game_dir,
        callback=lambda d: log_queue.put(f"【下载】{d}")
    )

def install_fabric(version_id: str, game_dir: str):
    fabric_ver = minecraft_launcher_lib.fabric.get_latest_fabric_version(version_id)
    minecraft_launcher_lib.fabric.install_fabric(
        version_id, fabric_ver, game_dir,
        callback=lambda d: log_queue.put(f"【Fabric】{d}")
    )

def start_mc(version_id: str, game_dir: str, username: str, java_path: str, max_mem: str = "4G") -> subprocess.Popen:
    uuid = minecraft_launcher_lib.utils.get_uuid_offline(username)
    opt = {
        "username": username,
        "uuid": uuid,
        "token": "",
        "jvmArguments": [f"-Xmx{max_mem}", "-Xms2G"]
    }
    cmd = minecraft_launcher_lib.command.get_minecraft_command(version_id, game_dir, opt)
    proc = subprocess.Popen(
        cmd,
        cwd=game_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    def read_log():
        for line in proc.stdout:
            log_queue.put(line.strip())
    threading.Thread(target=read_log, daemon=True).start()
    return proc