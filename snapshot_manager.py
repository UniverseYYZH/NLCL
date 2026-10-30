"""实例轻量快照：只备份 saves、config、options.txt。"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

SNAPSHOT_ITEMS = ("saves", "config", "options.txt")


class SnapshotError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Snapshot:
    snapshot_id: str
    path: Path
    version_id: str
    folder_name: str
    note: str
    created_at: str
    size: int
    files: int

    @property
    def title(self) -> str:
        return self.note or "未命名快照"


def default_snapshot_root() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "NLMCL" / "snapshots"


class SnapshotManager:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else default_snapshot_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def create_snapshot(
        self,
        minecraft_directory: str | Path,
        version_id: str,
        folder_name: str,
        note: str = "",
        *,
        prefix: str = "",
    ) -> Snapshot:
        mc_dir = Path(minecraft_directory)
        existing = [mc_dir / item for item in SNAPSHOT_ITEMS if (mc_dir / item).exists()]
        if not existing:
            raise SnapshotError(
                "没有可备份的内容：未找到 saves、config 或 options.txt"
            )

        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe_version = "".join(
            char if char.isalnum() or char in "-_." else "_"
            for char in folder_name
        )
        snapshot_id = f"{prefix}{stamp}-{safe_version}"
        target = self.root / snapshot_id
        suffix = 1
        while target.exists():
            snapshot_id = f"{prefix}{stamp}-{safe_version}-{suffix}"
            target = self.root / snapshot_id
            suffix += 1
        target.mkdir(parents=True)

        copied: list[str] = []
        for item in SNAPSHOT_ITEMS:
            source = mc_dir / item
            if not source.exists():
                continue
            destination = target / item
            if source.is_dir():
                shutil.copytree(source, destination, symlinks=False)
            else:
                shutil.copy2(source, destination)
            copied.append(item)

        size, files = _measure(target)
        metadata = {
            "snapshot_id": snapshot_id,
            "version_id": version_id,
            "folder_name": folder_name,
            "note": note.strip(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "size": size,
            "files": files,
            "items": copied,
        }
        (target / "snapshot.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return Snapshot(
            snapshot_id=snapshot_id,
            path=target,
            version_id=version_id,
            folder_name=folder_name,
            note=metadata["note"],
            created_at=metadata["created_at"],
            size=size,
            files=files,
        )

    def list_snapshots(self) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        if not self.root.is_dir():
            return snapshots
        for item in self.root.iterdir():
            if not item.is_dir():
                continue
            metadata = _read_metadata(item)
            if metadata is None:
                continue
            snapshots.append(
                Snapshot(
                    snapshot_id=item.name,
                    path=item,
                    version_id=str(metadata.get("version_id") or ""),
                    folder_name=str(metadata.get("folder_name") or ""),
                    note=str(metadata.get("note") or ""),
                    created_at=str(metadata.get("created_at") or ""),
                    size=int(metadata.get("size") or 0),
                    files=int(metadata.get("files") or 0),
                )
            )
        snapshots.sort(key=lambda item: item.created_at, reverse=True)
        return snapshots

    def rollback(
        self,
        snapshot: Snapshot,
        minecraft_directory: str | Path,
    ) -> Snapshot | None:
        """回滚前先自动创建保护快照，再恢复三个轻量路径。"""

        mc_dir = Path(minecraft_directory)
        if not snapshot.path.is_dir():
            raise SnapshotError("快照目录不存在")

        safety = None
        try:
            safety = self.create_snapshot(
                mc_dir,
                snapshot.version_id,
                snapshot.folder_name or snapshot.version_id,
                note=f"回滚前自动备份（{snapshot.title}）",
                prefix="auto-",
            )
        except SnapshotError:
            # 当前目录可能为空；仍允许回滚。
            safety = None

        for item in SNAPSHOT_ITEMS:
            source = snapshot.path / item
            destination = mc_dir / item
            if destination.is_dir():
                shutil.rmtree(destination)
            elif destination.exists():
                destination.unlink()
            if not source.exists():
                continue
            if source.is_dir():
                shutil.copytree(source, destination, symlinks=False)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)

        return safety

    def delete(self, snapshot: Snapshot) -> None:
        target = snapshot.path.resolve()
        root = self.root.resolve()
        if target.parent != root:
            raise SnapshotError("拒绝删除快照目录之外的内容")
        shutil.rmtree(target, ignore_errors=True)


def _read_metadata(path: Path) -> dict | None:
    try:
        data = json.loads((path / "snapshot.json").read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _measure(path: Path) -> tuple[int, int]:
    size = 0
    files = 0
    for item in path.rglob("*"):
        if item.is_file():
            files += 1
            try:
                size += item.stat().st_size
            except OSError:
                pass
    return size, files
