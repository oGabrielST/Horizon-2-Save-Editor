"""Create release downloads from an explicit source-file allowlist."""
import hashlib
from pathlib import Path
import shutil
import zipfile

from horizon_editor import ASSETS

root = Path(__file__).resolve().parent
dist = root / "dist"
dist.mkdir(exist_ok=True)
source_files = sorted(set(ASSETS) | {
    "horizon_editor.py", "build_windows.py", "package_release.py",
    "package.json", "package-lock.json", "tests/core.test.cjs",
    "RELEASE_NOTES.md", ".gitignore",
})
with zipfile.ZipFile(dist / "Horizon.2.Save.Editor.Source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for name in source_files:
        archive.write(root / name, "Horizon 2 Save Editor/" + name)
exe = dist / "Horizon.2.Save.Editor.exe"
shutil.copyfile(dist / "Horizon 2 Save Editor.exe", exe)
downloads = [exe, dist / "Horizon.2.Save.Editor.Source.zip"]
(dist / "SHA256SUMS.txt").write_text(
    "".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in downloads),
    encoding="utf-8",
)
print("Release files:", ", ".join(path.name for path in downloads))
