# Format evidence and validation boundaries

## Local source build

Analyzed build: `Anthem_1.0.0.64_x64__8wekyb3d8bbwe`, PE x64 `forza_durango_release_final.exe`, 58,204,160 bytes.

- Executable SHA-256: `3ec04c6163fb5614e3d351ba0570d39b846041a257715d6340eceb03ccb7f0a3`.
- `media/stripped/gamedbRC.slt` SHA-256: `4d50013dc7705de05a074e4421679e16a3a1eda0816841861b0b7139ecf45517`.
- Supporting files: `media/profileschema/ForzaProfile.sch`, GlobalRegistry.xml, GameTunableSettings.zip, UnlockRules.xml and RC archives. Displayed event names are resolved from the shipped `EN.zip` string tables using unique low-16-bit LSB2 keys.

The REA MCP connection opened the executable and detected Ghidra 12.1.4. A string search timed out after 300 seconds. No decompilation from that operation supports the implementation. The database, schema and save provide the direct evidence. Ghidra is not required to run the editor.

## Observed save format

The commit starts with `Azimuth complete save revision v2`, followed by `blobs N` and `SHA256 size name` records. Every input manifest is validated before editing and again on export. Only modified blobs in the selected revision and their commit are rewritten. Other revisions and files are preserved byte for byte.

PlayerDatabase and ProfileData use an `ssmc` header, a little-endian uint32 payload length, the payload and zero padding. The external blob size is preserved. The original sample's PlayerDatabase was 6,291,464 bytes with a 67,584-byte SQLite payload. ProfileData was 20,488 bytes with a 13,267-byte payload. VersionFlags was 6.

UInt32 profile fields are found by unique name/length/metadata/type-3 markers, then updated in place. SaveState is XML with an ObjectDictionary root; only the chosen object's property Value is patched, preserving unrelated text and line endings. BinarySaveState is preserved unchanged. Level remains read-only internally and is not exposed as an editable UI field.

## Garage evidence

Career_Garage has 124 columns. Stock templates use the game's tables, IsStock flags and the correct engine/drivetrain relations. Part IDs are not assumed to equal CarId multiplied by 1000.

A comparison of 43 part fields and 16 numeric fields matched two stock cars in the original sample: Audi RS6 (2180) and Mazda RX8 (1426). The catalog has 354 entries, with 334 eligible stock templates. Traffic/null entries and Ferrari IDs 326 and 1271 with ambiguous stock selections are excluded.

Adding allocates a new garage ID and GUID, copies the profile owner, and synchronizes garage counts/values. Replacing retains the row identity and removes incompatible purchased parts. Duplication uses SQLite INSERT SELECT to avoid JavaScript rounding of 64-bit tuning/livery IDs. Special liveries and variant initialization remain incompletely verified.

## Progression relationships

- Career_EventUnlock.UnlockId references AnthemEvents.AnthemEventId, not CampaignId or AnthemEventRaceId.
- RaceResults uses race IDs. The editor does not fabricate race results.
- ChampionshipEventsCompleted describes the active championship, not global history. The championship preset leaves this table and current story counters unchanged.
- Experimental championship history updates Career_ChampionshipsCompleted and Career_ChampionshipsWon for 168 mainland campaigns. Effects on scripts and rewards are unknown.
- Bulk regular-event unlocks use mainland CareerStage 1, EventType 0: 673 IDs. The complete event catalog contains 790 entries.
- Bulk destinations use IDs 3–8; ID 9 belongs to the island. There are 25 known perks and 45 eligible visible mainland solo bucket challenges. Existing co-op values are preserved.
- Map/board actions only update objects already present in SaveState. They do not create structures or award XP.

## Current verification status

The user reported working car edits, XP and perk unlocks. Other progression actions remain pending in-game testing. This report does not establish coverage of every car, every garage operation or all content variants. Direct level editing was removed at the user's request; XP edits preserve its stored value.

Automated coverage checks serialization, integrity, references, atomic rollback and original-file preservation. Invalid hashes, ambiguous fields, unsafe paths, out-of-range values and unsupported references are rejected. The current local integration fixture is an earlier exported copy derived from the supplied backup, kept outside the repository.

Further validation should load a narrowly edited copy, use the feature, save again, exit and reload. Comparing the game-resaved version with the exported version can identify normalization and missing dependencies. No verified full-campaign completion preset is claimed.
