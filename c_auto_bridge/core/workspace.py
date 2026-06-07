from dataclasses import dataclass
from pathlib import Path

from c_auto_bridge.core.agent_session import Workspace


@dataclass(frozen=True)
class WorkspaceValidator:
    home_directory: Path
    temp_directory: Path
    system_directories: tuple[Path, ...]

    def validate(self, raw_path: str) -> Workspace:
        path = self._expand(raw_path)
        if not path.is_absolute():
            raise ValueError("workspace path must be absolute")
        if not path.is_dir():
            raise ValueError("workspace path must be an existing directory")
        resolved_path = path.resolve()
        if resolved_path == Path(resolved_path.anchor):
            raise ValueError("workspace path cannot be the filesystem root")
        if resolved_path == self.home_directory.resolve():
            raise ValueError("workspace path cannot be the home root")
        if resolved_path == self.temp_directory.resolve():
            raise ValueError("workspace path cannot be the temporary directory root")
        for system_directory in self.system_directories:
            if resolved_path == system_directory.resolve():
                raise ValueError("workspace path cannot be a system directory")
        return Workspace(path=str(resolved_path))

    def _expand(self, raw_path: str) -> Path:
        if raw_path == "~":
            return self.home_directory
        if raw_path.startswith("~/"):
            return self.home_directory / raw_path.removeprefix("~/")
        return Path(raw_path)


@dataclass(frozen=True)
class NamedWorkspace:
    name: str
    workspace: Workspace
    updated_at: str
