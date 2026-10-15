# Horizon 2 Save Editor v0.4.0

A standalone native Windows editor. Profile, garage, progression and story tools run directly inside the application window, with no browser or local web server.

## Download

- **Horizon.2.Save.Editor.exe** — portable Windows app. No installer or Python required.
- **Horizon.2.Save.Editor.Source.zip** — native Python app and complete source. Extract it and run `python horizon_editor.py` with Python 3.12+ including Tkinter and SQLite serialization support; tested with Python 3.14.
- **SHA256SUMS.txt** — checksums of the release downloads.

## Included

- Native folder selection, revision selection and four editing tabs.
- XP, credits, wheelspins and available skill tokens. Direct level editing remains disabled.
- Searchable catalog with 334 eligible stock models; add, replace, duplicate and select an active car.
- Perk unlocks and experimental event, map, championship-history and story tools.
- Python backend with manifest/hash validation, SQLite integrity checks, action rollback and atomic ZIP export.
- Source backups remain unchanged; export outside the source folder.
- Prompts before discarding unexported changes, and file reads/writes on a background worker.

## Quick start

1. Launch the app and click **Open backup folder**.
2. Select the complete, extracted `player-1` backup folder.
3. Prepare changes, then click **Export edited copy (.zip)**.
4. Close the game and Azimuth, and back up the active save.
5. Extract the ZIP and replace `data/titles/1A96545B/saves/player-1` with the exported folder.
6. Test in-game, save, exit and reload. Restore your backup if needed.

## Validation and limits

Native regression tests cover generated containers and a local compatible backup. The packaged executable is checked using its hidden native-widget self-test. XP edits preserve the stored level; other files and revisions remain unchanged.

Car editing, XP and perks were reported working in the earlier browser editor. This release uses a new Python backend and still needs in-game confirmation. Other progression features remain experimental. There is no verified complete-everything action or support for encrypted console saves. The executable is unsigned.
