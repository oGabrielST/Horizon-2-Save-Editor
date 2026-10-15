# Horizon 2 Save Editor

A local save editor for **Forza Horizon 2 on Azimuth**. Edit XP and resources, manage your garage, unlock perks and explore optional progression tools. The editor reads your backup and exports a new copy; it never overwrites the selected source folder.

## Download

**[Download the Windows application](https://github.com/oGabrielST/Horizon-2-Save-Editor/releases/latest/download/Horizon.2.Save.Editor.exe)**

- **Windows EXE:** portable native desktop application. All editing happens in its own window. No browser, local server, Python installation or installer is required.
- **[Python + source package](https://github.com/oGabrielST/Horizon-2-Save-Editor/releases/latest/download/Horizon.2.Save.Editor.Source.zip):** extract the entire ZIP, then run `python horizon_editor.py`. Requires Python 3.12+ with Tkinter and SQLite serialization support. Tested with Python 3.14. Keep the script, `native_core.py` and `catalog.js` together.
- **[Release notes and all downloads](https://github.com/oGabrielST/Horizon-2-Save-Editor/releases/latest)**

The EXE includes its Python runtime, native Tk widgets, SQLite and the model catalog. It operates offline and does not start a web server or open a browser. No administrator privileges are required. The executable is not digitally signed.

## How to use

1. Open **Horizon 2 Save Editor.exe**, then click **Open backup folder** in the application window.
2. Select the **complete, extracted `player-1` folder** from an Azimuth save backup. Do not select a single blob or a ZIP. The editor validates manifests, SHA-256 hashes and SQLite integrity, then selects the latest complete profile revision.
3. Choose a tab:
   - **Profile:** credits, wheelspins, XP and available skill tokens.
   - **Garage:** select your active car, add a stock model, replace a car or duplicate an existing one.
   - **Progress:** unlock perks or use the clearly marked experimental actions.
   - **Advanced story:** edit existing flags and counters only if you understand the progression state.
4. Review **Prepared changes**, then click **Export edited copy (.zip)**. Profile fields are applied during export; the other action buttons prepare changes immediately in memory.
5. Close the game and Azimuth. **Copy your active `player-1` folder somewhere safe before replacing it.**
6. Extract the downloaded ZIP. Replace `data/titles/1A96545B/saves/player-1` with the exported `player-1` folder, then launch the game. Editing a `data/saves-backup-*` folder alone does not affect the active save.
7. Check the change in-game, save, quit and load again. If a test fails, close the game and restore the entire original folder.

The app asks before discarding unexported changes when switching revisions, opening another backup or closing. **Discard changes** reloads the original selected revision, including after an export. Do not mix blobs from different revisions. Export outside your source backup folder.

## Features and testing status

| Feature | Available actions | Status |
| --- | --- | --- |
| XP | Edit stored XP while preserving the level field | Reported working in the earlier browser editor |
| Garage | Add or replace with 334 eligible stock models; duplicate; select active car | Reported working in the earlier browser editor; not every model or action individually verified |
| Perks | Unlock all 25 known perks | Reported working in the earlier browser editor |
| Other resources | Credits, wheelspins and available skill tokens | Structural tests passed; not separately confirmed in the latest user test |
| Event unlocks | 673 mainland regular events or individual entries from a 790-event catalog | Experimental; in-game testing pending |
| Other progression | Six destinations, map discoveries, existing boards, 45 solo bucket lists and 168 mainland championship history entries | Experimental; in-game testing pending |
| Advanced story | Existing boolean flags and numeric counters in CareerState and iestate | Experimental; story dependencies are not fully mapped |

**Direct level editing is disabled.** Editing XP does not rewrite the stored level or calculate rewards. The game determines progression behavior.

Version 0.4.0 ports the save transformations to Python. Automated tests pass against generated data and a local backup, but in-game confirmation of this native version is still pending. Earlier reports describe tests on one local setup, not certification of every model, build or feature. A valid database and correct hashes do not guarantee valid story progression.

## Limitations

- Supports the observed Azimuth v2 revision manifests, `ssmc` wrappers and VersionFlags 6. Xbox 360 containers and encrypted console saves are not supported.
- There is no verified **complete everything** action. Championship history changes do not finish the active championship, run story scripts or grant rewards.
- Replacing a car resets its stock parts/settings and removes purchased parts. Duplicating keeps tuning and existing livery references; it does not create an independent livery.
- Special liveries, DLC, electric cars and other variants can require installed content and additional game initialization. Catalog presence does not install or license content.
- Bulk progression actions target the mainland. Island events are available individually but still depend on the installed content and career state.
- Backups are limited to 256 MB and 10,000 files. Edited database payloads must fit the original blob capacity. Exported ZIPs are uncompressed.
- This tool does not fix Azimuth startup errors such as failure to load the native static-TLS helper.

## Development

`horizon_editor.py` implements the native Tk interface. `native_core.py` validates and edits the save using Python's standard library, preserving 64-bit SQLite values. `catalog.js` contains a shared JSON literal that the native app parses as data; it does not execute JavaScript. The original browser edition is retained in the source package for reference and is not bundled in the native EXE.

```powershell
# Launch the native application from source
python horizon_editor.py

# Run native regression tests; the real-backup test is optional
$env:FH2_SAMPLE = 'C:\path\to\player-1'
python -m unittest discover -s tests -p test_native.py -v

# Check native widgets and optionally exercise a local backup
python horizon_editor.py --self-test python-selftest.json --fixture $env:FH2_SAMPLE

# Build and package the standalone Windows executable
python -m pip install pyinstaller==6.22.3
python build_windows.py
python package_release.py
```

The executable is created at `dist/Horizon 2 Save Editor.exe`. Build it on Windows. Native tests cover byte-preserving no-op export, corrupt manifests, profile rollback, XP without level mutation, garage identities, 64-bit values, purchased parts, progression records, container capacity and atomic ZIP writes. Set `FH2_SAMPLE` to additionally test a compatible local backup. Test saves and game executables are not distributed.

The desktop self-test constructs all four native tabs without displaying a window and checks the bundled catalog. With `--fixture`, it also loads a backup, edits XP, adds a car, unlocks perks and validates an exported snapshot. Tests do not run the game or replace the active save.

For the retained browser core, run `npm ci --ignore-scripts` and `npm test`. See [RESEARCH.md](RESEARCH.md) for format evidence and remaining uncertainties.

## Credits

The native editor uses Python, Tk and SQLite. The retained browser edition uses **sql.js 1.15.0**, with its license at [vendor/sql.js-LICENSE](vendor/sql.js-LICENSE). This is an unofficial project and is not affiliated with the game's developers or publisher.
