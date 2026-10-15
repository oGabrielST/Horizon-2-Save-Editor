# Horizon 2 Save Editor

A local save editor for **Forza Horizon 2 on Azimuth**. Edit XP and resources, manage your garage, unlock perks and explore optional progression tools. The editor reads your backup and exports a new copy; it never overwrites the selected source folder.

## Download

**[Download the Windows application](https://github.com/oGabrielST/Horizon-2-Save-Editor/releases/latest/download/Horizon.2.Save.Editor.exe)**

- **Windows EXE:** portable application with an interactive launch menu. No Python installation or installer required. Click **Open Save Editor** to open the editor in your default browser. Chrome or Edge is recommended.
- **[Python + source package](https://github.com/oGabrielST/Horizon-2-Save-Editor/releases/latest/download/Horizon.2.Save.Editor.Source.zip):** extract the entire ZIP, then run `python horizon_editor.py`. Requires Python 3.10+ with Tkinter. Keep the script and editor assets together.
- **Browser-only:** extract the source package and open `index.html` in Chrome or Edge, or serve the folder with a local static web server.
- **[Release notes and all downloads](https://github.com/oGabrielST/Horizon-2-Save-Editor/releases/latest)**

The EXE includes its Python runtime and UI assets. It serves only the bundled interface on `127.0.0.1` using an automatically assigned port. The save stays in browser memory and is not uploaded to the launcher or GitHub. No administrator privileges are required. The executable is not digitally signed.

## How to use

1. Open **Horizon 2 Save Editor.exe**, then click **Open Save Editor**. Keep the launch menu open while editing. Alternatively, use the browser-only option above.
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

Switching revisions, opening another backup or selecting **Discard changes** discards edits that have not been exported. Do not mix blobs from different revisions. Export before closing the browser tab.

## Features and testing status

| Feature | Available actions | Status |
| --- | --- | --- |
| XP | Edit stored XP while preserving the level field | User reported working |
| Garage | Add or replace with 334 eligible stock models; duplicate; select active car | Car editing reported working; not every model or action individually verified |
| Perks | Unlock all 25 known perks | User reported working |
| Other resources | Credits, wheelspins and available skill tokens | Structural tests passed; not separately confirmed in the latest user test |
| Event unlocks | 673 mainland regular events or individual entries from a 790-event catalog | Experimental; in-game testing pending |
| Other progression | Six destinations, map discoveries, existing boards, 45 solo bucket lists and 168 mainland championship history entries | Experimental; in-game testing pending |
| Advanced story | Existing boolean flags and numeric counters in CareerState and iestate | Experimental; story dependencies are not fully mapped |

**Direct level editing is disabled.** Editing XP does not rewrite the stored level or calculate rewards. The game determines progression behavior.

User reports describe tests on one local setup, not certification of every model, build or feature. A valid database and correct hashes do not guarantee valid story progression.

## Limitations

- Supports the observed Azimuth v2 revision manifests, `ssmc` wrappers and VersionFlags 6. Xbox 360 containers and encrypted console saves are not supported.
- There is no verified **complete everything** action. Championship history changes do not finish the active championship, run story scripts or grant rewards.
- Replacing a car resets its stock parts/settings and removes purchased parts. Duplicating keeps tuning and existing livery references; it does not create an independent livery.
- Special liveries, DLC, electric cars and other variants can require installed content and additional game initialization. Catalog presence does not install or license content.
- Bulk progression actions target the mainland. Island events are available individually but still depend on the installed content and career state.
- Backups are limited to 256 MB and 10,000 files. Edited database payloads must fit the original blob capacity. Exported ZIPs are uncompressed.
- This tool does not fix Azimuth startup errors such as failure to load the native static-TLS helper.

## Development

The browser editor has no build step. `save-core.js` contains the save transformations; `app.js` manages the UI; `catalog.js` contains derived vehicle/event metadata. `horizon_editor.py` provides the desktop launch menu and a loopback-only static asset server. No game executable or user save is included.

```powershell
# Launch from source
python horizon_editor.py

# Run core tests with a local compatible fixture
npm install --ignore-scripts
$env:FH2_SAMPLE = 'C:\path\to\player-1'
npm test

# Check the Python launch menu and packaged asset routes
python horizon_editor.py --self-test python-selftest.json

# Build the standalone Windows executable
python -m pip install pyinstaller==6.22.3
python build_windows.py
```

The executable is created at `dist/Horizon 2 Save Editor.exe`. Build it on Windows. The bundled resource layout follows the [PyInstaller runtime documentation](https://pyinstaller.org/en/stable/runtime-information.html).

Without `FH2_SAMPLE`, integration tests requiring a real save are skipped. A complete local run has 17 tests, including no-op preservation, hash rejection, XP editing without level mutation, garage identities and counters, 64-bit value preservation, rollback, progression records and source-file preservation. Do not commit test saves or personal backups.

The desktop self-test creates its widgets without showing the menu, validates all bundled routes and checks that unlisted paths cannot be accessed. Browser testing additionally checks folder loading and ZIP export. See [RESEARCH.md](RESEARCH.md) for format evidence and remaining uncertainties.

## Credits

SQLite runs locally through **sql.js 1.15.0**. Its license is included at [vendor/sql.js-LICENSE](vendor/sql.js-LICENSE). This is an unofficial project and is not affiliated with the game's developers or publisher.
