"""Build the standalone Windows launcher using PyInstaller (development only)."""
from pathlib import Path
import subprocess
import sys

from horizon_editor import ASSETS

root = Path(__file__).resolve().parent
command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile",
           "--windowed", "--noupx", "--name", "Horizon 2 Save Editor",
           "--distpath", str(root / "dist"), "--workpath", str(root / "build"),
           "--specpath", str(root / "build")]
for name in ASSETS:
    destination = str(Path(name).parent)
    command.extend(["--add-data", f"{root / name}:{destination}"])
command.append(str(root / "horizon_editor.py"))
subprocess.run(command, check=True, cwd=root)
