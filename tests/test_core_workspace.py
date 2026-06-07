from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from c_auto_bridge.core.agent_session import Workspace
from c_auto_bridge.core.workspace import WorkspaceValidator


class WorkspaceValidatorTest(unittest.TestCase):
    def test_accepts_existing_absolute_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir) / "repo"
            workspace_dir.mkdir()
            validator = WorkspaceValidator(
                home_directory=Path(tmpdir) / "home",
                temp_directory=Path(tmpdir) / "temp",
                system_directories=(),
            )

            workspace = validator.validate(str(workspace_dir))

            self.assertEqual(workspace, Workspace(path=str(workspace_dir.resolve())))

    def test_accepts_home_relative_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            workspace_dir = home_dir / "repo"
            workspace_dir.mkdir(parents=True)
            validator = WorkspaceValidator(
                home_directory=home_dir,
                temp_directory=Path(tmpdir) / "temp",
                system_directories=(),
            )

            workspace = validator.validate("~/repo")

            self.assertEqual(workspace, Workspace(path=str(workspace_dir.resolve())))

    def test_rejects_non_absolute_relative_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            validator = WorkspaceValidator(
                home_directory=Path(tmpdir) / "home",
                temp_directory=Path(tmpdir) / "temp",
                system_directories=(),
            )

            with self.assertRaisesRegex(ValueError, "absolute"):
                validator.validate("repo")

    def test_rejects_missing_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            validator = WorkspaceValidator(
                home_directory=Path(tmpdir) / "home",
                temp_directory=Path(tmpdir) / "temp",
                system_directories=(),
            )

            with self.assertRaisesRegex(ValueError, "existing directory"):
                validator.validate(str(Path(tmpdir) / "missing"))

    def test_rejects_home_root_system_directory_temp_root_and_filesystem_root(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            temp_dir = Path(tmpdir) / "temp"
            system_dir = Path(tmpdir) / "system"
            home_dir.mkdir()
            temp_dir.mkdir()
            system_dir.mkdir()
            validator = WorkspaceValidator(
                home_directory=home_dir,
                temp_directory=temp_dir,
                system_directories=(system_dir,),
            )

            with self.assertRaisesRegex(ValueError, "home root"):
                validator.validate(str(home_dir))
            with self.assertRaisesRegex(ValueError, "system directory"):
                validator.validate(str(system_dir))
            with self.assertRaisesRegex(ValueError, "temporary directory root"):
                validator.validate(str(temp_dir))
            with self.assertRaisesRegex(ValueError, "filesystem root"):
                validator.validate(str(home_dir.anchor))


if __name__ == "__main__":
    unittest.main()
