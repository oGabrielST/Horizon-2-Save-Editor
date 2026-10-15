# Horizon 2 Save Editor v0.3.0

Manage Forza Horizon 2 Azimuth save backups through a portable Windows launcher and a local browser interface.

## Download

- **Horizon.2.Save.Editor.exe** — recommended for Windows. No installer or Python required. Open it and click **Open Save Editor**.
- **Horizon.2.Save.Editor.Source.zip** — Python launcher, browser assets and source. Extract the entire package and run `python horizon_editor.py` with Python 3.10+ and Tkinter.
- **SHA256SUMS.txt** — checksums of the release downloads.

## Included

- Profile editing for XP, credits, wheelspins and available skill tokens.
- A garage catalog with 334 eligible stock models, car replacement, duplication and active-car selection.
- Perk unlocks and experimental event, map, championship-history and story tools.
- Backup integrity checks, atomic action rollback and ZIP export with updated manifests.
- A desktop launch menu and usage instructions.

Direct level editing is disabled; XP editing preserves the stored level field. Car editing, XP and perks have been reported working by the user. Other progression features still await in-game testing, and not every car or garage action has been individually verified.

## Quick start

1. Launch the app and select the complete, extracted `player-1` backup folder.
2. Make your changes and click **Export edited copy (.zip)**.
3. Close the game and Azimuth, and back up the active save folder.
4. Extract the ZIP and replace `data/titles/1A96545B/saves/player-1` with the exported folder.
5. Test in-game, save, exit and reload. Restore your backup if needed.

See the repository README for the full guide and limitations. This release does not claim full-campaign completion or support for encrypted console saves. The Windows executable is unsigned.
