"""Manual projects own one newly created child of the selected parent."""

from pathlib import PurePosixPath, PureWindowsPath


class ProjectNameConflictError(ValueError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f'project name already exists: "{name}"')


def project_directory(parent: str, name: str, device_os: str | None = None) -> str:
    name = name.strip()
    if (
        not name
        or name in {".", ".."}
        or any(c in name for c in '/\\\0<>:"|?*')
        or name.endswith((".", " "))
    ):
        raise ValueError("项目名称必须是有效的单层文件夹名称")
    if any(ord(c) < 32 for c in name) or name.split(".", 1)[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        raise ValueError("项目名称不能使用系统保留名称或控制字符")
    parent = parent.strip()
    windows = (
        device_os == "windows"
        or (len(parent) > 1 and parent[1] == ":")
        or parent.startswith("\\\\")
    )
    path = PureWindowsPath(parent) if windows else PurePosixPath(parent)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("请选择有效的绝对父目录")
    return str(path / name)
