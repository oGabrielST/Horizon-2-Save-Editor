"""Native Azimuth save transformations. No network or third-party dependencies."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
import tempfile
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import zipfile

MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 10_000


def integer(value, label, maximum=2147483647, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError(f"{label}: enter a whole number.")
    number = int(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{label}: allowed range: {minimum} to {maximum}.")
    return number


def safe_path(name):
    if not name or any(c in name for c in "\\\0:") or any(p in ("", ".", "..") for p in name.split("/")):
        raise ValueError("Invalid backup path.")
    return name


def read_folder(folder):
    folder = Path(folder).absolute()
    if not folder.is_dir() or folder.is_symlink() or folder.is_junction():
        raise ValueError("Select an extracted player-1 backup folder, not a link.")
    files, total = {}, 0
    for directory, dirs, names in os.walk(folder, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError("Backup folders must not contain links or junctions.")
        for name in names:
            path = Path(directory) / name
            key = safe_path(folder.name + "/" + path.relative_to(folder).as_posix())
            if len(files) >= MAX_FILES or total + path.stat().st_size > MAX_BYTES:
                raise ValueError("Backup exceeds the 256 MB or 10,000 file limit.")
            with path.open("rb") as stream:
                data = stream.read(MAX_BYTES - total + 1)
            total += len(data)
            if total > MAX_BYTES:
                raise ValueError("Backup exceeds the 256 MB limit.")
            files[key] = data
    validate_manifests(files)
    return files


def unwrap(data, label):
    if len(data) < 8 or data[:4] != b"ssmc":
        raise ValueError(f"{label}: unrecognized ssmc header.")
    size = struct.unpack_from("<I", data, 4)[0]
    if not size or size > len(data) - 8 or any(data[size + 8:]):
        raise ValueError(f"{label}: invalid payload size or trailing data.")
    return data[8:size + 8]


def wrap(original, payload, label):
    unwrap(original, label)
    if len(payload) > len(original) - 8:
        raise ValueError(f"{label}: edit exceeds the original container capacity.")
    return b"ssmc" + struct.pack("<I", len(payload)) + payload + bytes(len(original) - len(payload) - 8)


def profile_offset(data, name):
    payload = unwrap(data, "ProfileData")
    key = name.encode("ascii")
    marker = struct.pack("<I", len(key)) + key + b"\x20\0\0\0\0" + struct.pack("<I", 3)
    offset = payload.find(marker)
    if offset < 0 or payload.find(marker, offset + 1) >= 0 or offset + len(marker) + 4 > len(payload):
        raise ValueError(f"ProfileData: missing, ambiguous or truncated field {name}.")
    return offset + len(marker) + 8


def read_profile(data, name):
    return struct.unpack_from("<I", data, profile_offset(data, name))[0]


def write_profile(data, name, value):
    struct.pack_into("<I", data, profile_offset(data, name), integer(value, name, 4294967295))


def validate_manifests(files):
    manifests = {}
    for path, data in files.items():
        safe_path(path)
        if not re.search(r"/revisions/[0-9a-f]+/commit$", path, re.I):
            continue
        source = data.decode("utf-8")
        lines = source.splitlines()
        while lines and not lines[-1]:
            lines.pop()
        if len(lines) < 3 or lines[0] != "Azimuth complete save revision v2" or not re.fullmatch(r"blobs [0-9]+", lines[1]):
            raise ValueError("Invalid Azimuth v2 manifest.")
        if int(lines[1][6:]) != len(lines) - 2:
            raise ValueError("Incorrect blob count in manifest.")
        entries = {}
        for line in lines[2:]:
            match = re.fullmatch(r"([a-f0-9]{64}) (0|[1-9][0-9]*) ([A-Za-z0-9_.-]+)", line)
            if not match:
                raise ValueError("Invalid manifest entry.")
            digest, size, name = match.groups()
            if name in (".", "..") or name in entries:
                raise ValueError("Invalid or duplicate manifest entry.")
            blob_path = path[:-6] + "data/" + name
            blob = files.get(blob_path)
            if blob is None or len(blob) != int(size) or hashlib.sha256(blob).hexdigest() != digest:
                raise ValueError(f"Invalid backup: size or SHA-256 mismatch for {blob_path}.")
            entries[name] = line
        manifests[path] = {"source": source, "entries": entries}
    if not manifests:
        raise ValueError("No Azimuth manifest found. Select the player-1 folder.")
    return manifests


def revisions(manifests):
    found = []
    for path, manifest in manifests.items():
        match = re.fullmatch(r"(.*?/User_[^/]+)/revisions/([0-9a-f]+)/commit", path, re.I)
        if match and set(("ProfileData", "SaveState", "PlayerDatabase", "BinarySaveState", "VersionFlags")) <= manifest["entries"].keys():
            found.append({"path": path, "user": match[1], "id": match[2], "data": path[:-6] + "data/"})
    if not found or len({r["user"] for r in found}) != 1:
        raise ValueError("Select a backup containing exactly one complete User_ profile.")
    return sorted(found, key=lambda r: int(r["id"], 16), reverse=True)


class XmlState:
    def __init__(self, data):
        self.source = data.decode("utf-8")
        if re.search(r"<!DOCTYPE|<!ENTITY", self.source, re.I):
            raise ValueError("SaveState: DTD/entities are not supported.")
        root = ET.fromstring(self.source)
        if root.tag != "ObjectDictionary":
            raise ValueError("SaveState: invalid root element.")
        self.objects, self.edits = {}, {}
        for node in root:
            ident, kind = node.get("Id"), node.get("Type")
            if node.tag != "Object" or not ident or not kind or ident in self.objects:
                raise ValueError("SaveState: invalid or duplicate object.")
            props = {}
            for prop in node:
                name, value = prop.get("Name"), prop.get("Value")
                if prop.tag != "Property" or not name or value is None or name in props:
                    raise ValueError("SaveState: invalid or duplicate property.")
                props[name] = value
            self.objects[ident] = {"type": kind, "props": props}

    def get(self, ident, name):
        try:
            original = self.objects[ident]["props"][name]
        except KeyError:
            raise ValueError(f"SaveState: {ident}/{name} is missing.") from None
        return self.edits.get((ident, name), original)

    def set(self, ident, name, value):
        self.get(ident, name)
        self.edits[ident, name] = str(value)

    def export(self):
        source = self.source
        for (ident, name), value in self.edits.items():
            if value == self.objects[ident]["props"][name]:
                continue
            object_re = rf'<Object\b(?=[^>]*\bId="{re.escape(ident)}")[^>]*>[\s\S]*?</Object>'
            matches = list(re.finditer(object_re, source))
            if len(matches) != 1:
                raise ValueError(f"SaveState: ambiguous object {ident}.")
            match = matches[0]
            property_re = rf'<Property\b(?=[^>]*\bName="{re.escape(name)}")[^>]*\/?>'
            properties = list(re.finditer(property_re, match[0]))
            if len(properties) != 1:
                raise ValueError(f"SaveState: ambiguous property {name}.")
            prop = properties[0]
            escaped = escape(value, {'"': '&quot;'})
            changed, count = re.subn(r'\bValue="[^"]*"', lambda _: f'Value="{escaped}"', prop[0])
            if count != 1:
                raise ValueError("SaveState: missing or ambiguous Value attribute.")
            start, end = match.start() + prop.start(), match.start() + prop.end()
            source = source[:start] + changed + source[end:]
        result = source.encode("utf-8")
        XmlState(result)
        return result


def load_catalog(directory):
    # The shared catalog is a JSON literal, never executed as JavaScript.
    source = (Path(directory) / "catalog.js").read_text(encoding="utf-8-sig").strip()
    prefix = "globalThis.FH2_CATALOG = "
    if not source.startswith(prefix):
        raise ValueError("Unsupported catalog format.")
    return json.loads(source[len(prefix):].removesuffix(";"))


def quote(name):
    return '"' + name.replace('"', '""') + '"'


class SaveSession:
    REQUIRED_TABLES = ("Career_Garage", "Career_PurchasedParts", "LastUsedGarageId", "Career_EventUnlock",
                       "Career_DestinationUnlock", "Career_ChampionshipsCompleted", "Career_ChampionshipsWon",
                       "Career_ChampionshipEventsCompleted", "Career_EventResults", "Career_RaceResults",
                       "BucketListProgress", "PerkUnlock")

    def __init__(self, files, revision, manifests, catalog):
        self.files, self.revision, self.manifests, self.catalog = files, revision, manifests, catalog
        prefix = revision["data"]
        if files[prefix + "VersionFlags"] != struct.pack("<I", 6):
            raise ValueError("Incompatible VersionFlags: only the observed format 6 is supported.")
        self.profile = bytearray(files[prefix + "ProfileData"])
        self.xml = XmlState(files[prefix + "SaveState"])
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        try:
            self.db.deserialize(unwrap(files[prefix + "PlayerDatabase"], "PlayerDatabase"))
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA trusted_schema=OFF")
            self.integrity()
            names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not set(self.REQUIRED_TABLES) <= names:
                raise ValueError("PlayerDatabase: required tables are missing.")
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger'").fetchone():
                raise ValueError("PlayerDatabase: triggers are not supported.")
            self.initial_profile = {n: read_profile(self.profile, n) for n in
                                    ("Credits", "Level", "XP", "CareerCar", "CarsInGarage", "GarageValue", "GaragePartsValue")}
        except Exception:
            self.close()
            raise
        self.db_dirty, self.log = False, []

    def close(self):
        self.db.close()

    def integrity(self):
        if [tuple(r) for r in self.db.execute("PRAGMA integrity_check")] != [("ok",)]:
            raise ValueError("PlayerDatabase: SQLite integrity_check failed.")

    def garage(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM Career_Garage ORDER BY Id")]

    @contextmanager
    def action(self):
        snapshot = (self.db.serialize(), self.profile[:], self.xml.edits.copy(), self.log[:], self.db_dirty)
        try:
            yield
            self.integrity()
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            self.db.deserialize(snapshot[0])
            self.profile, self.xml.edits, self.log, self.db_dirty = snapshot[1:]
            raise

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN")
        try:
            yield
            self.integrity()
            self.db.execute("COMMIT")
            self.db_dirty = True
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def set_profile(self, name, value):
        if name not in ("Credits", "XP"):
            raise ValueError("This profile field cannot be edited.")
        value = integer(value, name)
        if read_profile(self.profile, name) != value:
            write_profile(self.profile, name, value)
            self.log.append(f"{name}: {value}")

    def apply_profile(self, credits, xp, spins, tokens):
        with self.action():
            self.set_profile("Credits", credits)
            self.set_profile("XP", xp)
            for ident, name, value, label in (("TombolaState", "Spins", spins, "Wheelspins"),
                                             ("skills", "CurrentSkillTokensTotal", tokens, "Skill tokens")):
                number = integer(value, label)
                if self.xml.get(ident, name) != str(number):
                    self.xml.set(ident, name, number)
                    self.log.append(f"{label}: {number}")

    def set_current_car(self, ident):
        ident = integer(ident, "Garage ID")
        if not self.db.execute("SELECT 1 FROM Career_Garage WHERE Id=?", (ident,)).fetchone():
            raise ValueError("Car not found in garage.")
        write_profile(self.profile, "CareerCar", ident)
        self.log.append(f"Active car: garage #{ident}")

    def next_id(self):
        counter = list(self.db.execute("SELECT LastUsedGarageId FROM LastUsedGarageId"))
        if len(counter) != 1:
            raise ValueError("Invalid garage counter.")
        return integer(max(counter[0][0], *(g["Id"] for g in self.garage()), 0) + 1, "New garage ID")

    def update_totals(self, delta):
        garage = self.garage()
        write_profile(self.profile, "CarsInGarage", len(garage))
        write_profile(self.profile, "GarageValue", max(0, min(4294967295, read_profile(self.profile, "GarageValue") + delta)))
        write_profile(self.profile, "GaragePartsValue", sum(g["PartsValue"] for g in garage))

    def add_stock(self, car_id, replace_id=None):
        car = next((c for c in self.catalog["cars"] if c["id"] == car_id), None)
        if not car or not car.get("eligible") or not car.get("template"):
            raise ValueError("Model has no structurally validated stock configuration.")
        with self.action():
            garage = self.garage()
            previous = next((g for g in garage if g["Id"] == replace_id), None)
            if replace_id is not None and previous is None:
                raise ValueError("Replacement target car not found.")
            ident = previous["Id"] if previous else self.next_id()
            owner = next((g["OriginalOwner"] for g in garage if g["Id"] == read_profile(self.profile, "CareerCar")), None)
            entry = dict(car["template"], Id=ident, Guid=str(uuid.uuid4()), OriginalOwner=owner or (garage[0]["OriginalOwner"] if garage else "Player 1"))
            columns = [r[1] for r in self.db.execute("PRAGMA table_info(Career_Garage)")]
            if set(columns) != entry.keys():
                raise ValueError("Garage schema does not match the catalog.")
            old_price = 0
            if previous:
                old_car = next((c for c in self.catalog["cars"] if c["id"] == previous["CarId"]), None)
                if old_car is None:
                    raise ValueError("Previous car price missing from catalog.")
                old_price = old_car["price"] + previous["PartsValue"]
            with self.transaction():
                if previous:
                    self.db.execute("DELETE FROM Career_PurchasedParts WHERE GarageId=?", (ident,))
                    self.db.execute("DELETE FROM Career_Garage WHERE Id=?", (ident,))
                self.db.execute(f"INSERT INTO Career_Garage ({','.join(map(quote, columns))}) VALUES ({','.join('?' for _ in columns)})",
                                [entry[c] for c in columns])
                if not previous:
                    self.db.execute("UPDATE LastUsedGarageId SET LastUsedGarageId=?", (ident,))
            self.update_totals(car["price"] - old_price)
            self.log.append(f"{'Replaced' if previous else 'Added'}: {car['name']} (garage #{ident}, stock parts)")
            return ident

    def duplicate_car(self, ident):
        with self.action():
            original = next((g for g in self.garage() if g["Id"] == ident), None)
            if original is None:
                raise ValueError("Car not found.")
            new_id = self.next_id()
            # Python and SQLite preserve 64-bit IDs without floating-point conversion.
            entry = dict(original, Id=new_id, Guid=str(uuid.uuid4()))
            columns = list(entry)
            parts = [r[1] for r in self.db.execute("PRAGMA table_info(Career_PurchasedParts)")]
            price = next((c["price"] for c in self.catalog["cars"] if c["id"] == original["CarId"]), None)
            if price is None:
                raise ValueError("Car price missing from catalog.")
            with self.transaction():
                self.db.execute(f"INSERT INTO Career_Garage ({','.join(map(quote, columns))}) VALUES ({','.join('?' for _ in columns)})", list(entry.values()))
                expressions = ','.join('?' if c == 'GarageId' else quote(c) for c in parts)
                self.db.execute(f"INSERT INTO Career_PurchasedParts ({','.join(map(quote, parts))}) SELECT {expressions} FROM Career_PurchasedParts WHERE GarageId=?", (new_id, ident))
                self.db.execute("UPDATE LastUsedGarageId SET LastUsedGarageId=?", (new_id,))
            self.update_totals(price + original["PartsValue"])
            self.log.append(f"Duplicated garage car #{ident} to #{new_id}")
            return new_id

    def apply_preset(self, name):
        progression = self.catalog["progression"]
        with self.action():
            if name in ("discover", "boards"):
                for ident, obj in self.xml.objects.items():
                    if name == "discover" and obj["type"] in ("CameraState", "BucketListSlotState"):
                        self.xml.set(ident, "Discovered", "true")
                    if obj["type"] == "DiscountBoardSaveState":
                        if name == "boards":
                            self.xml.set(ident, "State", "Collected")
                        elif self.xml.get(ident, "State") == "Undiscovered":
                            self.xml.set(ident, "State", "Discovered")
            else:
                with self.transaction():
                    basic = {"destinations": ("Career_DestinationUnlock", progression["destinations"]),
                             "perks": ("PerkUnlock", progression["perks"]),
                             "events": ("Career_EventUnlock", [e["id"] for e in progression["events"] if e["region"] == "mainland" and e["stage"] == 1 and e["type"] == 0])}
                    if name in basic:
                        table, ids = basic[name]
                        self.db.executemany(f"INSERT OR IGNORE INTO {quote(table)} (UnlockId) VALUES (?)", [(i,) for i in ids])
                    elif name == "championships":
                        for ident in progression["campaigns"]:
                            self.db.execute("INSERT OR REPLACE INTO Career_ChampionshipsCompleted (CampaignId,Won,BestFinishPosition) VALUES (?,1,0)", (ident,))
                            self.db.execute("INSERT OR IGNORE INTO Career_ChampionshipsWon (CampaignId) VALUES (?)", (ident,))
                    elif name == "buckets":
                        self.db.executemany("INSERT INTO BucketListProgress (ChallengeId,Completed,Attempted,Viewed,CompletedCoop,AttemptedCoop,ViewedCoop) VALUES (?,1,1,0,0,0,0) ON CONFLICT(ChallengeId) DO UPDATE SET Completed=1,Attempted=1", [(i,) for i in progression["buckets"]])
                    else:
                        raise ValueError("Unknown option.")
            self.log.append(f"Applied: {name}")

    def unlock_event(self, ident):
        ident = integer(ident, "Event")
        if not any(e["id"] == ident for e in self.catalog["progression"]["events"]):
            raise ValueError("Event is missing from the catalog.")
        with self.action(), self.transaction():
            self.db.execute("INSERT OR IGNORE INTO Career_EventUnlock (UnlockId) VALUES (?)", (ident,))
            self.log.append(f"Event unlock record #{ident}")

    def set_story(self, ident, name, value):
        if ident not in ("CareerState", "iestate"):
            raise ValueError("This campaign object cannot be edited.")
        old = self.xml.get(ident, name)
        if old in ("true", "false"):
            if value not in ("true", "false"):
                raise ValueError("Enter true or false.")
        elif re.fullmatch(r"-?[0-9]+", old):
            if not re.fullmatch(r"-?[0-9]+", value) or not -1 <= int(value) <= 2147483647:
                raise ValueError("Enter an integer from -1 to 2147483647.")
            progression = self.catalog["progression"]
            allowed = {"CurrentCampaign": progression["campaigns"], "RoadTripLocation": progression["destinations"],
                       "BlockingEventId": [e["id"] for e in progression["events"]]}
            if name in allowed and int(value) != -1 and int(value) not in allowed[name]:
                raise ValueError("ID is missing from the mainland campaign catalog.")
        else:
            raise ValueError("Campaign enumeration is not mapped: this field is read-only.")
        self.xml.set(ident, name, value)
        self.log.append(f"{ident}/{name}: {value}")

    def export_files(self):
        self.integrity()
        garage = self.garage()
        if read_profile(self.profile, "CareerCar") not in {g["Id"] for g in garage}:
            raise ValueError("Active car does not exist in garage.")
        if read_profile(self.profile, "CarsInGarage") != len(garage):
            raise ValueError("Profile car count does not match the garage.")
        if len({g["Guid"] for g in garage}) != len(garage):
            raise ValueError("Duplicate garage GUID.")
        result = dict(self.files)
        prefix = self.revision["data"]
        replacements = {"ProfileData": bytes(self.profile), "SaveState": self.xml.export()}
        if self.db_dirty:
            replacements["PlayerDatabase"] = wrap(self.files[prefix + "PlayerDatabase"], self.db.serialize(), "PlayerDatabase")
        manifest = self.manifests[self.revision["path"]]
        commit = manifest["source"]
        for name, data in replacements.items():
            if data != self.files[prefix + name]:
                line = f"{hashlib.sha256(data).hexdigest()} {len(data)} {name}"
                commit = commit.replace(manifest["entries"][name], line)
                result[prefix + name] = data
        result[self.revision["path"]] = commit.encode("utf-8")
        validate_manifests(result)
        return result


def write_zip(destination, files, source_folder=None):
    destination = Path(destination).resolve()
    if source_folder and destination.is_relative_to(Path(source_folder).resolve()):
        raise ValueError("Export outside the source backup folder.")
    validate_manifests(files)
    handle, temporary = tempfile.mkstemp(prefix=".fh2-export-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
                for name, data in files.items():
                    archive.writestr(zipfile.ZipInfo(safe_path(name)), data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
