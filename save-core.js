/* Local-only Azimuth/FH2 save transformations. See RESEARCH.md for evidence boundaries. */
(function (root) {
  'use strict';
  const encoder = new TextEncoder();
  const decoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
  const fail = message => { throw new Error(message); };
  const bytesEqual = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
  const u32 = (b, o) => new DataView(b.buffer, b.byteOffset, b.byteLength).getUint32(o, true);
  const put32 = (b, o, v) => new DataView(b.buffer, b.byteOffset, b.byteLength).setUint32(o, v, true);
  const text = b => decoder.decode(b);
  function integer(value, label, max = 2147483647, min = 0) {
    if (typeof value !== 'number' && (typeof value !== 'string' || !/^\d+$/.test(value))) fail(`${label}: enter a whole number.`);
    const n = Number(value);
    if (!Number.isSafeInteger(n) || n < min || n > max) fail(`${label}: allowed range: ${min} to ${max}.`);
    return n;
  }
  async function sha256(bytes) {
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
  }
  function safePath(path) {
    if (typeof path !== 'string' || path.includes('\\') || path.includes('\0') || path.includes(':') || path.split('/').some(p => !p || p === '.' || p === '..')) fail('Invalid backup path.');
    return path;
  }
  function unwrap(bytes, label) {
    if (bytes.length < 8 || text(bytes.subarray(0, 4)) !== 'ssmc') fail(`${label}: unrecognized ssmc header.`);
    const size = u32(bytes, 4);
    if (!size || size > bytes.length - 8) fail(`${label}: invalid internal size.`);
    if (bytes.subarray(size + 8).some(b => b !== 0)) fail(`${label}: unrecognized extension after payload.`);
    return bytes.slice(8, size + 8);
  }
  function wrap(original, payload, label) {
    unwrap(original, label);
    if (payload.length > original.length - 8) fail(`${label}: edit exceeds the original container capacity.`);
    const out = new Uint8Array(original.length);
    out.set(original.subarray(0, 4)); put32(out, 4, payload.length); out.set(payload, 8);
    return out;
  }
  // PropertyBag records observed in ForzaProfile.sch/ProfileData: name length,
  // ASCII name, 0x20, four zero bytes, UInt32 type tag (3), LE uint32 value.
  function profileOffset(bytes, name) {
    const payload = unwrap(bytes, 'ProfileData');
    const key = encoder.encode(name);
    const marker = new Uint8Array(4 + key.length + 1 + 4 + 4);
    put32(marker, 0, key.length); marker.set(key, 4); marker[4 + key.length] = 32; put32(marker, marker.length - 4, 3);
    let offset = -1;
    for (let i = 0; i <= payload.length - marker.length; i++) {
      if (marker.every((v, j) => payload[i + j] === v)) {
        if (offset !== -1) fail(`ProfileData: ambiguous field ${name}.`);
        offset = i + marker.length + 8;
      }
    }
    if (offset < 0 || offset + 4 > payload.length + 8) fail(`ProfileData: UInt32 field ${name} is missing or truncated.`);
    return offset;
  }
  const readProfile = (bytes, name) => u32(bytes, profileOffset(bytes, name));
  function writeProfile(bytes, name, value) { put32(bytes, profileOffset(bytes, name), integer(value, name, 4294967295)); }

  function parseManifest(bytes) {
    const source = text(bytes);
    const lines = source.split(/\r?\n/);
    while (lines.length && lines.at(-1) === '') lines.pop();
    if (lines[0] !== 'Azimuth complete save revision v2' || !/^blobs \d+$/.test(lines[1] || '')) fail('Invalid Azimuth v2 manifest.');
    const count = Number(lines[1].slice(6)), entries = [], seen = new Set();
    if (count !== lines.length - 2 || count === 0) fail('Incorrect blob count in manifest.');
    for (const line of lines.slice(2)) {
      const m = /^([a-f0-9]{64}) (0|[1-9][0-9]*) ([A-Za-z0-9_.-]+)$/.exec(line);
      if (!m || m[3] === '.' || m[3] === '..' || seen.has(m[3]) || !Number.isSafeInteger(Number(m[2]))) fail('Invalid or duplicate manifest entry.');
      seen.add(m[3]); entries.push({ hash: m[1], size: Number(m[2]), name: m[3] });
    }
    return { source, entries };
  }
  async function validateManifests(files) {
    const manifests = new Map();
    for (const [path, bytes] of files) {
      safePath(path);
      if (!/\/revisions\/[0-9a-f]+\/commit$/i.test(path)) continue;
      const manifest = parseManifest(bytes), data = path.slice(0, -6) + 'data/';
      for (const entry of manifest.entries) {
        const blob = files.get(data + entry.name);
        if (!blob || blob.length !== entry.size || await sha256(blob) !== entry.hash) fail(`Invalid backup: size or SHA-256 mismatch for ${data + entry.name}.`);
      }
      manifests.set(path, manifest);
    }
    if (!manifests.size) fail('No Azimuth manifest found. Select the player-1 folder.');
    return manifests;
  }
  function revisions(manifests) {
    const found = [];
    for (const [path, m] of manifests) {
      const match = /^(.*\/User_[^/]+)\/revisions\/([0-9a-f]+)\/commit$/i.exec(path);
      if (match && ['ProfileData', 'SaveState', 'PlayerDatabase', 'BinarySaveState', 'VersionFlags'].every(n => m.entries.some(e => e.name === n))) found.push({ path, user: match[1], id: match[2], data: path.slice(0, -6) + 'data/' });
    }
    return found.sort((a, b) => a.user.localeCompare(b.user) || (BigInt('0x' + a.id) === BigInt('0x' + b.id) ? 0 : BigInt('0x' + a.id) > BigInt('0x' + b.id) ? -1 : 1));
  }
  class XmlState {
    constructor(bytes) {
      this.source = text(bytes);
      if (/<!DOCTYPE|<!ENTITY/i.test(this.source)) fail('SaveState: DTD/entities are not supported.');
      const doc = new DOMParser().parseFromString(this.source, 'application/xml');
      if (doc.getElementsByTagName('parsererror').length || doc.documentElement.tagName !== 'ObjectDictionary') fail('SaveState: Invalid XML.');
      this.objects = new Map(); this.edits = new Map();
      for (const node of doc.documentElement.children) {
        if (node.tagName !== 'Object') fail('SaveState: unknown element.');
        const id = node.getAttribute('Id'), type = node.getAttribute('Type'), props = new Map();
        if (!id || !type || this.objects.has(id)) fail('SaveState: invalid or duplicate object.');
        for (const prop of node.children) {
          const name = prop.getAttribute('Name'), value = prop.getAttribute('Value');
          if (prop.tagName !== 'Property' || !name || value === null || props.has(name)) fail('SaveState: invalid or duplicate property.');
          props.set(name, value);
        }
        this.objects.set(id, { id, type, props });
      }
    }
    get(id, name) {
      if (!this.objects.get(id)?.props.has(name)) fail(`SaveState: ${id}/${name} is missing.`);
      return this.edits.get(id + '\0' + name) ?? this.objects.get(id).props.get(name);
    }
    set(id, name, value) {
      this.get(id, name);
      this.edits.set(id + '\0' + name, String(value));
    }
    export() {
      if (!this.edits.size) return encoder.encode(this.source);
      let out = this.source;
      const escapeRE = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const xmlEscape = s => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      for (const [key, value] of this.edits) {
        const [id, name] = key.split('\0');
        if (value === this.objects.get(id).props.get(name)) continue;
        // Patch only the value; leave unrelated XML, whitespace and CRLF intact.
        const objectRE = new RegExp(`<Object\\b(?=[^>]*\\bId="${escapeRE(id)}")[^>]*>[\\s\\S]*?<\\/Object>`, 'g');
        let objectCount = 0, propertyCount = 0;
        out = out.replace(objectRE, objectText => {
          objectCount++;
          const propRE = new RegExp(`<Property\\b(?=[^>]*\\bName="${escapeRE(name)}")[^>]*\\/?>`, 'g');
          return objectText.replace(propRE, prop => { propertyCount++; return prop.replace(/\bValue="[^"]*"/, () => `Value="${xmlEscape(value)}"`); });
        });
        if (objectCount !== 1 || propertyCount !== 1) fail(`SaveState: could not update ${id}/${name} unambiguously.`);
      }
      const bytes = encoder.encode(out); new XmlState(bytes); return bytes;
    }
  }
  function rows(db, sql, params = []) {
    const statement = db.prepare(sql);
    try { statement.bind(params); const list = []; while (statement.step()) list.push(statement.getAsObject()); return list; }
    finally { statement.free(); }
  }
  const quote = s => '"' + s.replaceAll('"', '""') + '"';
  function integrity(db) {
    const result = rows(db, 'PRAGMA integrity_check');
    if (result.length !== 1 || Object.values(result[0])[0] !== 'ok') fail('PlayerDatabase: SQLite integrity_check failed.');
  }
  class SaveSession {
    constructor(SQL, files, revision, manifests, catalog) {
      this.SQL = SQL; this.files = files; this.revision = revision; this.manifests = manifests; this.catalog = catalog;
      this.profile = files.get(revision.data + 'ProfileData').slice(); unwrap(this.profile, 'ProfileData');
      const version = files.get(revision.data + 'VersionFlags');
      if (version.length !== 4 || u32(version, 0) !== 6) fail('Incompatible VersionFlags: this release supports format 6 from the analyzed backup.');
      this.xml = new XmlState(files.get(revision.data + 'SaveState'));
      this.db = new SQL.Database(unwrap(files.get(revision.data + 'PlayerDatabase'), 'PlayerDatabase'));
      try {
        integrity(this.db);
        const allowedTables = new Set(['Career_Garage','Career_PurchasedParts','LastUsedGarageId','Career_EventUnlock','Career_DestinationUnlock','Career_ChampionshipsCompleted','Career_ChampionshipsWon','Career_ChampionshipEventsCompleted','Career_EventResults','Career_RaceResults','BucketListProgress','PerkUnlock']);
        const names = new Set(rows(this.db, "SELECT name FROM sqlite_master WHERE type='table'").map(r => r.name));
        for (const table of allowedTables) if (!names.has(table)) fail(`PlayerDatabase: table ${table} is missing.`);
        if (rows(this.db, "SELECT name FROM sqlite_master WHERE type='trigger'").length) fail('PlayerDatabase: triggers are not supported.');
        this.initialProfile = Object.fromEntries(['Credits','Level','XP','CareerCar','CarsInGarage','GarageValue','GaragePartsValue'].map(n => [n, readProfile(this.profile, n)]));
        this.dbDirty = false; this.log = [];
      } catch (error) { this.db.close(); throw error; }
    }
    close() { this.db.close(); }
    garage() { return rows(this.db, 'SELECT * FROM Career_Garage ORDER BY Id'); }
    count(table) { return rows(this.db, `SELECT COUNT(*) n FROM ${quote(table)}`)[0].n; }
    setProfile(name, value) {
      if (!['Credits','XP'].includes(name)) fail('This profile field cannot be edited.');
      const n = integer(value, name, 2147483647);
      if (n !== readProfile(this.profile, name)) { writeProfile(this.profile, name, n); this.log.push(`${name}: ${n}`); }
    }
    setSpins(value) { this.xml.set('TombolaState', 'Spins', integer(value, 'Wheelspins')); }
    setSkillTokens(value) { this.xml.set('skills', 'CurrentSkillTokensTotal', integer(value, 'Skill tokens')); }
    transaction(fn) {
      this.db.run('BEGIN');
      try { const result = fn(); integrity(this.db); this.db.run('COMMIT'); this.dbDirty = true; return result; }
      catch (error) { this.db.run('ROLLBACK'); throw error; }
    }
    setCurrentCar(id) {
      id = integer(id, 'Garage ID');
      if (!rows(this.db, 'SELECT Id FROM Career_Garage WHERE Id=?', [id]).length) fail('Car not found in garage.');
      writeProfile(this.profile, 'CareerCar', id); this.log.push(`Active car: garage #${id}`);
    }
    addStock(carId, replaceId = null) {
      const car = this.catalog.cars.find(c => c.id === Number(carId));
      if (!car?.eligible || !car.template) fail('Model has no structurally validated stock configuration.');
      const garage = this.garage();
      const previous = replaceId === null ? null : garage.find(g => g.Id === Number(replaceId));
      if (replaceId !== null && !previous) fail('Replacement target car not found.');
      const last = rows(this.db, 'SELECT LastUsedGarageId FROM LastUsedGarageId');
      if (last.length !== 1) fail('Invalid garage counter.');
      const id = previous ? previous.Id : Math.max(last[0].LastUsedGarageId, ...garage.map(g => g.Id), 0) + 1;
      integer(id, 'New garage ID');
      const entry = { ...car.template, Id: id, Guid: crypto.randomUUID(), OriginalOwner: garage.find(g => g.Id === readProfile(this.profile, 'CareerCar'))?.OriginalOwner || garage[0]?.OriginalOwner || 'Player 1' };
      const schema = rows(this.db, 'PRAGMA table_info(Career_Garage)').map(r => r.name);
      if (schema.length !== Object.keys(entry).length || schema.some(c => !Object.hasOwn(entry, c))) fail('Garage schema does not match the catalog.');
      this.transaction(() => {
        if (previous) { this.db.run('DELETE FROM Career_PurchasedParts WHERE GarageId=?', [id]); this.db.run('DELETE FROM Career_Garage WHERE Id=?', [id]); }
        this.db.run(`INSERT INTO Career_Garage (${schema.map(quote).join(',')}) VALUES (${schema.map(() => '?').join(',')})`, schema.map(c => entry[c]));
        if (!previous) this.db.run('UPDATE LastUsedGarageId SET LastUsedGarageId=?', [id]);
      });
      writeProfile(this.profile, 'CarsInGarage', this.count('Career_Garage'));
      const beforeCost = previous ? (this.catalog.cars.find(c => c.id === previous.CarId)?.price ?? null) : 0;
      if (beforeCost === null) fail('Previous car price missing from catalog; reload the save.');
      const value = readProfile(this.profile, 'GarageValue') + car.price - beforeCost - (previous?.PartsValue || 0);
      writeProfile(this.profile, 'GarageValue', Math.max(0, Math.min(4294967295, value)));
      writeProfile(this.profile, 'GaragePartsValue', this.garage().reduce((sum, g) => sum + g.PartsValue, 0));
      this.log.push(`${previous ? 'Replaced' : 'Added'}: ${car.name} (garage #${id}, stock parts)`);
      return id;
    }
    duplicateCar(id) {
      const garage = this.garage(), original = garage.find(g => g.Id === Number(id));
      if (!original) fail('Car not found.');
      const last = rows(this.db, 'SELECT LastUsedGarageId FROM LastUsedGarageId');
      if (last.length !== 1) fail('Invalid garage counter.');
      const next = integer(Math.max(last[0].LastUsedGarageId, ...garage.map(g => g.Id)) + 1, 'ID');
      const cols = Object.keys(original);
      const partCols = rows(this.db, 'PRAGMA table_info(Career_PurchasedParts)').map(r => r.name);
      this.transaction(() => {
        // Keep 64-bit tuning/livery IDs inside SQLite; JS numbers lose precision.
        const values = [], expressions = cols.map(c => {
          if (c === 'Id') { values.push(next); return '?'; }
          if (c === 'Guid') { values.push(crypto.randomUUID()); return '?'; }
          return quote(c);
        });
        this.db.run(`INSERT INTO Career_Garage (${cols.map(quote)}) SELECT ${expressions} FROM Career_Garage WHERE Id=?`, [...values, original.Id]);
        this.db.run(`INSERT INTO Career_PurchasedParts (${partCols.map(quote)}) SELECT ${partCols.map(c => c === 'GarageId' ? '?' : quote(c))} FROM Career_PurchasedParts WHERE GarageId=?`, [next, original.Id]);
        this.db.run('UPDATE LastUsedGarageId SET LastUsedGarageId=?', [next]);
      });
      writeProfile(this.profile, 'CarsInGarage', this.count('Career_Garage'));
      const price = this.catalog.cars.find(c => c.id === original.CarId)?.price;
      if (price !== undefined) writeProfile(this.profile, 'GarageValue', Math.min(4294967295, readProfile(this.profile, 'GarageValue') + price + original.PartsValue));
      writeProfile(this.profile, 'GaragePartsValue', this.garage().reduce((sum, g) => sum + g.PartsValue, 0));
      this.log.push(`Duplicated garage car #${id} → #${next}`); return next;
    }
    applyPreset(name) {
      const p = this.catalog.progression;
      const insertIds = (table, col, ids) => { for (const id of ids) this.db.run(`INSERT OR IGNORE INTO ${quote(table)} (${quote(col)}) VALUES (?)`, [id]); };
      if (name === 'destinations') {
        this.transaction(() => insertIds('Career_DestinationUnlock', 'UnlockId', p.destinations));
      } else if (name === 'events') {
        this.transaction(() => insertIds('Career_EventUnlock', 'UnlockId', p.events.filter(e => e.region === 'mainland' && e.stage === 1 && e.type === 0).map(e => e.id)));
      } else if (name === 'perks') {
        this.transaction(() => insertIds('PerkUnlock', 'UnlockId', p.perks));
      } else if (name === 'championships') {
        this.transaction(() => {
          for (const id of p.campaigns) {
            this.db.run('INSERT OR REPLACE INTO Career_ChampionshipsCompleted (CampaignId,Won,BestFinishPosition) VALUES (?,1,0)', [id]);
            this.db.run('INSERT OR IGNORE INTO Career_ChampionshipsWon (CampaignId) VALUES (?)', [id]);
          }
        });
      } else if (name === 'buckets') {
        this.transaction(() => {
          for (const id of p.buckets) this.db.run('INSERT INTO BucketListProgress (ChallengeId,Completed,Attempted,Viewed,CompletedCoop,AttemptedCoop,ViewedCoop) VALUES (?,1,1,0,0,0,0) ON CONFLICT(ChallengeId) DO UPDATE SET Completed=1,Attempted=1', [id]);
        });
      } else if (name === 'discover') {
        for (const obj of this.xml.objects.values()) {
          if (obj.type === 'CameraState' || obj.type === 'BucketListSlotState') this.xml.set(obj.id, 'Discovered', 'true');
          if (obj.type === 'DiscountBoardSaveState' && this.xml.get(obj.id, 'State') === 'Undiscovered') this.xml.set(obj.id, 'State', 'Discovered');
        }
      } else if (name === 'boards') {
        for (const obj of this.xml.objects.values()) if (obj.type === 'DiscountBoardSaveState') this.xml.set(obj.id, 'State', 'Collected');
      } else fail('Unknown option.');
      this.log.push(`Applied: ${name}`);
    }
    unlockEvent(id) {
      id = integer(id, 'Event');
      if (!this.catalog.progression.events.some(e => e.id === id)) fail('Event is missing from the catalog.');
      this.transaction(() => this.db.run('INSERT OR IGNORE INTO Career_EventUnlock (UnlockId) VALUES (?)', [id]));
      this.log.push(`Event unlock record #${id}`);
    }
    setStoryProperty(id, name, value) {
      if (!['CareerState', 'iestate'].includes(id)) fail('This campaign object cannot be edited.');
      const old = this.xml.get(id, name);
      if (/^(true|false)$/.test(old)) {
        if (!/^(true|false)$/.test(String(value))) fail('Invalid boolean value.');
      } else if (/^-?\d+$/.test(old)) {
        if (!/^-?\d+$/.test(String(value)) || !Number.isSafeInteger(Number(value)) || Number(value) < -1 || Number(value) > 2147483647) fail('Invalid integer value.');
        const catalogs = { CurrentCampaign: this.catalog.progression.campaigns, RoadTripLocation: this.catalog.progression.destinations, BlockingEventId: this.catalog.progression.events.map(e => e.id) };
        if (catalogs[name] && Number(value) !== -1 && !catalogs[name].includes(Number(value))) fail('ID is missing from the mainland campaign catalog.');
      } else fail('Campaign enumeration is not mapped: this field is read-only.');
      this.xml.set(id, name, value); this.log.push(`${id}/${name}: ${value}`);
    }
    async exportFiles() {
      integrity(this.db);
      const garage = this.garage(), ids = new Set(garage.map(g => g.Id));
      if (!ids.has(readProfile(this.profile, 'CareerCar'))) fail('Active car does not exist in garage.');
      if (readProfile(this.profile, 'CarsInGarage') !== garage.length) fail('Profile car count does not match the garage.');
      if (new Set(garage.map(g => g.Guid)).size !== garage.length) fail('Duplicate garage GUID.');
      const result = new Map(this.files);
      const replacements = new Map([
        ['ProfileData', this.profile.slice()], ['SaveState', this.xml.export()]
      ]);
      if (this.dbDirty) replacements.set('PlayerDatabase', wrap(this.files.get(this.revision.data + 'PlayerDatabase'), this.db.export(), 'PlayerDatabase'));
      const manifest = this.manifests.get(this.revision.path);
      let commit = manifest.source;
      for (const [name, bytes] of replacements) {
        if (bytesEqual(bytes, this.files.get(this.revision.data + name))) continue;
        const old = manifest.entries.find(e => e.name === name);
        const line = `${old.hash} ${old.size} ${name}`;
        commit = commit.replace(line, `${await sha256(bytes)} ${bytes.length} ${name}`);
        result.set(this.revision.data + name, bytes);
      }
      result.set(this.revision.path, encoder.encode(commit));
      await validateManifests(result);
      return result;
    }
  }
  // Every user action either commits completely or restores its prior snapshot.
  for (const name of ['addStock', 'duplicateCar', 'applyPreset', 'unlockEvent', 'setStoryProperty']) {
    const action = SaveSession.prototype[name];
    SaveSession.prototype[name] = function (...args) {
      const before = { db: this.db.export(), profile: this.profile.slice(), edits: new Map(this.xml.edits), log: this.log.slice(), dirty: this.dbDirty };
      try { return action.apply(this, args); }
      catch (error) {
        this.db.close(); this.db = new this.SQL.Database(before.db); this.profile = before.profile;
        this.xml.edits = before.edits; this.log = before.log; this.dbDirty = before.dirty;
        throw error;
      }
    };
  }
  const crcTable = Array.from({length:256}, (_, n) => { let c=n; for(let k=0;k<8;k++) c=(c&1)?(0xedb88320^(c>>>1)):(c>>>1); return c>>>0; });
  function crc32(bytes) { let c=0xffffffff; for(const b of bytes)c=crcTable[(c^b)&255]^(c>>>8);return(c^0xffffffff)>>>0; }
  function makeZip(files) {
    if (files.size > 65535) fail('ZIP64 required: too many files.');
    const local=[], central=[];let offset=0;
    for(const [name,bytes] of files) {
      safePath(name);const filename=encoder.encode(name),size=bytes.length,crc=crc32(bytes);
      if(filename.length>65535 || offset+size+filename.length+30>0xffffffff)fail('ZIP exceeds the supported size limit.');
      const header=new Uint8Array(30+filename.length),v=new DataView(header.buffer);
      v.setUint32(0,0x04034b50,true);v.setUint16(4,20,true);v.setUint16(6,0x0800,true);v.setUint16(12,33,true);v.setUint32(14,crc,true);v.setUint32(18,size,true);v.setUint32(22,size,true);v.setUint16(26,filename.length,true);header.set(filename,30);local.push(header,bytes);
      const ch=new Uint8Array(46+filename.length),cv=new DataView(ch.buffer);
      cv.setUint32(0,0x02014b50,true);cv.setUint16(4,20,true);cv.setUint16(6,20,true);cv.setUint16(8,0x0800,true);cv.setUint16(14,33,true);cv.setUint32(16,crc,true);cv.setUint32(20,size,true);cv.setUint32(24,size,true);cv.setUint16(28,filename.length,true);cv.setUint32(42,offset,true);ch.set(filename,46);central.push(ch);offset+=header.length+size;
    }
    const centralSize=central.reduce((n,b)=>n+b.length,0);
    if(offset+centralSize+22>0xffffffff)fail('ZIP64 required.');
    const end=new Uint8Array(22),v=new DataView(end.buffer);v.setUint32(0,0x06054b50,true);v.setUint16(8,files.size,true);v.setUint16(10,files.size,true);v.setUint32(12,centralSize,true);v.setUint32(16,offset,true);return new Blob([...local,...central,end],{type:'application/zip'});
  }
  const api = { integer, sha256, safePath, unwrap, wrap, readProfile, writeProfile, parseManifest, validateManifests, revisions, XmlState, SaveSession, rows, makeZip, bytesEqual };
  root.FH2 = api;
  if (typeof module !== 'undefined') module.exports = api;
})(globalThis);
