"""Regression tests using generated save data and an optional local backup."""
import hashlib
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_core import (SaveSession, XmlState, integer, load_catalog, read_folder, read_profile,
                         revisions, safe_path, validate_manifests, wrap, write_profile, write_zip)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT)


def synthetic_files():
    """Create a small compatible container from public schema metadata, not a user save."""
    car = next(c for c in CATALOG['cars'] if c['eligible'])
    entry = dict(car['template'], Id=1, Guid='synthetic-guid', OriginalOwner='Test player')
    connection = sqlite3.connect(':memory:')
    columns = ','.join('"' + k + '" ' + ('TEXT' if isinstance(v, str) else 'INTEGER') + (' PRIMARY KEY' if k == 'Id' else '') for k, v in entry.items())
    connection.execute('CREATE TABLE Career_Garage (' + columns + ')')
    connection.execute('INSERT INTO Career_Garage VALUES (' + ','.join('?' for _ in entry) + ')', list(entry.values()))
    connection.executescript('''
        CREATE TABLE Career_PurchasedParts (GarageId INTEGER, PartId INTEGER, PRIMARY KEY (GarageId, PartId));
        INSERT INTO Career_PurchasedParts VALUES (1, 10);
        CREATE TABLE LastUsedGarageId (LastUsedGarageId INTEGER);
        INSERT INTO LastUsedGarageId VALUES (1);
        CREATE TABLE Career_EventUnlock (UnlockId INTEGER PRIMARY KEY);
        CREATE TABLE Career_DestinationUnlock (UnlockId INTEGER PRIMARY KEY);
        CREATE TABLE PerkUnlock (UnlockId INTEGER PRIMARY KEY);
        CREATE TABLE Career_ChampionshipsCompleted (CampaignId INTEGER PRIMARY KEY, Won INTEGER, BestFinishPosition INTEGER);
        CREATE TABLE Career_ChampionshipsWon (CampaignId INTEGER PRIMARY KEY);
        CREATE TABLE Career_ChampionshipEventsCompleted (Id INTEGER);
        CREATE TABLE Career_EventResults (Id INTEGER);
        CREATE TABLE Career_RaceResults (Id INTEGER);
        CREATE TABLE BucketListProgress (ChallengeId INTEGER PRIMARY KEY, Completed INTEGER, Attempted INTEGER, Viewed INTEGER, CompletedCoop INTEGER, AttemptedCoop INTEGER, ViewedCoop INTEGER);
    ''')
    payload = connection.serialize()
    connection.close()
    fields = dict(Credits=10000, Level=190, XP=123677, CareerCar=1, CarsInGarage=1, GarageValue=car['price'], GaragePartsValue=0)
    profile = b''.join(struct.pack('<I', len(k)) + k.encode() + b'\x20\0\0\0\0' + struct.pack('<II', 3, v) for k, v in fields.items())
    xml = b'\xef\xbb\xbf<ObjectDictionary>\r\n<Object Id="TombolaState" Type="TombolaState"><Property Name="Spins" Value="3"/></Object>\r\n<Object Id="skills" Type="Skills"><Property Name="CurrentSkillTokensTotal" Value="4"/></Object>\r\n<Object Id="CareerState" Type="CareerState"><Property Name="CurrentCampaign" Value="-1"/><Property Name="RoadTripStarted" Value="false"/><Property Name="ActiveCareerLocation" Value="Mainland"/></Object>\r\n<Object Id="iestate" Type="IESaveState"><Property Name="IntroducedSkills" Value="false"/></Object>\r\n<Object Id="camera" Type="CameraState"><Property Name="Discovered" Value="false"/></Object>\r\n<Object Id="board" Type="DiscountBoardSaveState"><Property Name="State" Value="Undiscovered"/></Object>\r\n</ObjectDictionary>\r\n'
    blobs = {'ProfileData': b'ssmc' + struct.pack('<I', len(profile)) + profile + bytes(1024),
             'SaveState': xml, 'PlayerDatabase': b'ssmc' + struct.pack('<I', len(payload)) + payload + bytes(1024 * 1024),
             'BinarySaveState': b'untouched', 'VersionFlags': struct.pack('<I', 6)}
    prefix = 'player-1/User_test/revisions/0001/'
    manifest = 'Azimuth complete save revision v2\r\nblobs 5\r\n' + ''.join(f'{hashlib.sha256(b).hexdigest()} {len(b)} {n}\r\n' for n, b in blobs.items())
    return {**{prefix + 'data/' + n: b for n, b in blobs.items()}, prefix + 'commit': manifest.encode()}


def session_for(files):
    manifests = validate_manifests(files)
    return SaveSession(files, revisions(manifests)[0], manifests, CATALOG)


class NativeCoreTests(unittest.TestCase):
    def setUp(self):
        self.files = synthetic_files()
        self.session = session_for(self.files)
        self.addCleanup(self.session.close)

    def test_noop_preserves_every_byte(self):
        self.assertEqual(self.session.export_files(), self.files)

    def test_profile_export_preserves_level_and_source(self):
        self.session.apply_profile('20000', '456789', '12', '99')
        files = self.session.export_files()
        reopened = session_for(files)
        self.addCleanup(reopened.close)
        self.assertEqual(read_profile(reopened.profile, 'Level'), 190)
        self.assertEqual(read_profile(reopened.profile, 'XP'), 456789)
        self.assertEqual(reopened.xml.get('TombolaState', 'Spins'), '12')
        self.assertEqual(self.files, synthetic_files())
        with self.assertRaises(ValueError):
            self.session.set_profile('Level', 100)

    def test_profile_failure_rolls_back_all_fields(self):
        with self.assertRaises(ValueError):
            self.session.apply_profile('20000', '4000', '12', '-1')
        self.assertEqual(self.session.export_files(), self.files)
        self.assertEqual(self.session.log, [])

    def test_integer_rejects_ambiguous_and_out_of_range_values(self):
        for value in ('', '-1', '1.5', '1e5', ' 2', True, 1.2, 2147483648):
            with self.subTest(value=value), self.assertRaises(ValueError):
                integer(value, 'Value')

    def test_manifest_rejects_corruption(self):
        files = dict(self.files)
        key = next(k for k in files if k.endswith('/BinarySaveState'))
        files[key] += b'x'
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            validate_manifests(files)

    def test_xml_preserves_bom_crlf_and_unrelated_bytes(self):
        xml = self.session.xml
        xml.set('TombolaState', 'Spins', '99')
        self.assertEqual(xml.export(), xml.source.encode().replace(b'Name="Spins" Value="3"', b'Name="Spins" Value="99"'))
        for source in (b'<!DOCTYPE ObjectDictionary><ObjectDictionary/>', b'<ObjectDictionary><Object Id="x" Type="t"><Property Name="a" Value="1"/><Property Name="a" Value="2"/></Object></ObjectDictionary>'):
            with self.assertRaises(ValueError):
                XmlState(source)

    def test_add_replace_and_active_car(self):
        ident = self.session.add_stock(247)
        self.session.set_current_car(ident)
        self.assertEqual(len(self.session.garage()), 2)
        self.session.add_stock(247, ident)
        self.assertEqual(len(self.session.garage()), 2)
        self.assertEqual(read_profile(self.session.profile, 'CareerCar'), ident)
        validate_manifests(self.session.export_files())

    def test_duplicate_preserves_64_bit_values_and_purchased_parts(self):
        column = next(k for k in self.session.garage()[0] if 'Livery' in k and isinstance(self.session.garage()[0][k], int))
        self.session.db.execute(f'UPDATE Career_Garage SET "{column}"=?', (9223372036854775806,))
        ident = self.session.duplicate_car(1)
        duplicate = next(g for g in self.session.garage() if g['Id'] == ident)
        self.assertEqual(duplicate[column], 9223372036854775806)
        self.assertEqual(self.session.db.execute('SELECT PartId FROM Career_PurchasedParts WHERE GarageId=?', (ident,)).fetchone()[0], 10)
        self.assertEqual(len({g['Guid'] for g in self.session.garage()}), 2)
        validate_manifests(self.session.export_files())

    def test_database_action_rolls_back_after_post_write_failure(self):
        before = self.session.db.serialize()
        with patch.object(self.session, 'update_totals', side_effect=ValueError('test failure')):
            with self.assertRaises(ValueError):
                self.session.add_stock(247)
        self.assertEqual(self.session.db.serialize(), before)
        self.assertEqual(self.session.export_files(), self.files)
        self.assertFalse(self.session.db_dirty)

    def test_presets_and_event_are_idempotent(self):
        for name in ('perks', 'destinations', 'events', 'championships', 'buckets', 'discover', 'boards'):
            self.session.apply_preset(name)
            self.session.apply_preset(name)
        for table, count in (('PerkUnlock', 25), ('Career_DestinationUnlock', 6), ('Career_EventUnlock', 673), ('Career_ChampionshipsWon', 168), ('BucketListProgress', 45)):
            self.assertEqual(self.session.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], count)
        self.assertEqual(self.session.xml.get('board', 'State'), 'Collected')
        self.session.unlock_event(CATALOG['progression']['events'][0]['id'])
        validate_manifests(self.session.export_files())

    def test_story_validates_values_and_catalog_ids(self):
        self.session.set_story('CareerState', 'RoadTripStarted', 'true')
        self.session.set_story('CareerState', 'CurrentCampaign', str(CATALOG['progression']['campaigns'][0]))
        for name, value in (('CurrentCampaign', '999999'), ('RoadTripStarted', 'yes'), ('ActiveCareerLocation', 'Island')):
            with self.assertRaises(ValueError):
                self.session.set_story('CareerState', name, value)
        validate_manifests(self.session.export_files())

    def test_export_rejects_inconsistent_garage(self):
        write_profile(self.session.profile, 'CarsInGarage', 999)
        with self.assertRaisesRegex(ValueError, 'car count'):
            self.session.export_files()

    def test_zip_atomicity_and_source_folder_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'edited.zip'
            write_zip(destination, self.files)
            before = destination.read_bytes()
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual({n: archive.read(n) for n in archive.namelist()}, self.files)
            with self.assertRaises(ValueError):
                write_zip(destination, self.files, Path(directory))
            with patch('native_core.os.replace', side_effect=OSError('test write failure')):
                with self.assertRaises(OSError):
                    write_zip(destination, self.files)
            self.assertEqual(destination.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [destination])

    def test_folder_round_trip_and_path_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, data in self.files.items():
                path = Path(directory) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            self.assertEqual(read_folder(Path(directory) / 'player-1'), self.files)
        for name in ('../save', '/save', 'C:/save', 'save\\blob', 'save//blob'):
            with self.assertRaises(ValueError):
                safe_path(name)

    def test_container_capacity_is_enforced(self):
        with self.assertRaises(ValueError):
            wrap(b'ssmc' + struct.pack('<I', 1) + b'x', b'too large', 'Test')


@unittest.skipUnless(os.environ.get('FH2_SAMPLE'), 'Set FH2_SAMPLE to test a real local backup')
class RealBackupTests(unittest.TestCase):
    def test_real_noop_and_native_edits(self):
        original = read_folder(os.environ['FH2_SAMPLE'])
        session = session_for(original)
        self.addCleanup(session.close)
        self.assertEqual(session.export_files(), original)
        level = read_profile(session.profile, 'Level')
        session.apply_profile('30000000', '456789', '12', '99')
        session.add_stock(247)
        session.duplicate_car(session.garage()[0]['Id'])
        for name in ('perks', 'events', 'destinations', 'championships', 'buckets', 'discover', 'boards'):
            session.apply_preset(name)
        exported = session.export_files()
        reopened = session_for(exported)
        self.addCleanup(reopened.close)
        self.assertEqual(read_profile(reopened.profile, 'XP'), 456789)
        self.assertEqual(read_profile(reopened.profile, 'Level'), level)
        self.assertEqual(read_folder(os.environ['FH2_SAMPLE']), original)


if __name__ == '__main__':
    unittest.main()
