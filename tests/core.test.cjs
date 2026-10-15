'use strict';
const { test, before } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
global.DOMParser = new JSDOM('').window.DOMParser;
if (!global.crypto) Object.defineProperty(global, 'crypto', { value: require('node:crypto').webcrypto });
const core = require('../save-core.js');
const initSqlJs = require('../vendor/sql-wasm-inline.js');
require('../catalog.js');
const catalog = global.FH2_CATALOG, encoder = new TextEncoder();
let SQL, files, manifests, revision;
const sample = process.env.FH2_SAMPLE;
before(async () => {
  SQL = await initSqlJs();
  if (!sample) return;
  files = new Map();
  function read(dir, prefix) {
    for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
      const absolute = path.join(dir, item.name), name = prefix + '/' + item.name;
      if (item.isDirectory()) read(absolute, name);
      else if (item.isFile()) files.set(name, new Uint8Array(fs.readFileSync(absolute)));
      else throw new Error('Fixture must contain regular files only.');
    }
  }
  read(sample, path.basename(sample));
  manifests = await core.validateManifests(files); revision = core.revisions(manifests)[0];
});
function withSave(name, fn) {
  test(name, { skip: !sample && 'Set FH2_SAMPLE to an extracted player-1 backup.' }, async () => {
    const session = new core.SaveSession(SQL, files, revision, manifests, catalog);
    try { await fn(session); } finally { session.close(); }
  });
}
test('strict numeric input rejects empty, fraction, infinity, negative and overflow', () => {
  for (const value of ['', ' ', '12.5', '-1', 'Infinity', NaN, 2147483648, null]) assert.throws(() => core.integer(value, 'value'));
  assert.equal(core.integer('0', 'value'), 0); assert.equal(core.integer('2147483647', 'value'), 2147483647);
});
test('safe archive paths reject traversal and absolute paths', () => {
  for (const name of ['/x','C:/x','a/../b','a/./b','a//b','a\\b','a/\0b']) assert.throws(() => core.safePath(name));
});
test('manifest grammar rejects duplicate names and count mismatches', () => {
  const row='a'.repeat(64)+' 4 VersionFlags';
  for(const value of ['bad',`Azimuth complete save revision v2\nblobs 2\n${row}\n`,`Azimuth complete save revision v2\nblobs 2\n${row}\n${row}\n`])assert.throws(()=>core.parseManifest(encoder.encode(value)));
});
test('XML validates encoding, structure and scoped property edits', () => {
  assert.throws(()=>new core.XmlState(new Uint8Array([0xff])));
  assert.throws(()=>new core.XmlState(encoder.encode('<ObjectDictionary><Object>')));
  assert.throws(()=>new core.XmlState(encoder.encode('<!DOCTYPE x><ObjectDictionary/>')));
  const source='<ObjectDictionary>\r\n<Object Id="Other" Type="Test"><Property Name="Spins" Value="77"/></Object>\r\n<Object Type="TombolaState" Id="TombolaState"><Property Value="9" Name="Spins"/></Object>\r\n</ObjectDictionary>';
  const xml=new core.XmlState(encoder.encode(source)); xml.set('TombolaState','Spins',10);
  assert.equal(new TextDecoder().decode(xml.export()),source.replace('Value="9"','Value="10"'));
  assert.throws(()=>xml.get('Missing','Spins'));
});
withSave('no-op export preserves every file byte for byte', async s => {
  const result=await s.exportFiles(); assert.equal(result.size, files.size);
  for(const [name,bytes] of files)assert.deepEqual(result.get(name),bytes,name);
});
withSave('source checksum mismatch is rejected before editing', async () => {
  const damaged=new Map(files), name=revision.data+'PlayerDatabase', bytes=damaged.get(name).slice();bytes[100]^=1;damaged.set(name,bytes);
  await assert.rejects(core.validateManifests(damaged),/SHA-256/);
});
withSave('credits, XP, skills and spins preserve level, unrelated blobs and source', async s => {
  s.setProfile('Credits',8888888);s.setProfile('XP',456789);assert.throws(()=>s.setProfile('Level',42),/cannot be edited/);s.setSpins(123);s.setSkillTokens(25);
  const result=await s.exportFiles();await core.validateManifests(result);
  assert.equal(core.readProfile(result.get(revision.data+'ProfileData'),'Credits'),8888888);
  assert.equal(core.readProfile(result.get(revision.data+'ProfileData'),'XP'),456789);
  assert.equal(core.readProfile(result.get(revision.data+'ProfileData'),'Level'),s.initialProfile.Level);
  const xml=new core.XmlState(result.get(revision.data+'SaveState'));assert.equal(xml.get('TombolaState','Spins'),'123');assert.equal(xml.get('skills','CurrentSkillTokensTotal'),'25');
  for(const [name,bytes] of files)if(![revision.path,revision.data+'ProfileData',revision.data+'SaveState'].includes(name))assert.deepEqual(result.get(name),bytes,name);
  assert.equal(core.readProfile(files.get(revision.data+'ProfileData'),'Credits'),s.initialProfile.Credits);
});
withSave('add stock car updates identity, garage counters, wrapped size and hashes', async s => {
  const before=s.garage(), car=catalog.cars.find(c=>c.id===247), id=s.addStock(car.id), after=s.garage();
  assert.equal(after.length,before.length+1);const added=after.find(c=>c.Id===id);assert.equal(added.CarId,247);assert.equal(added.PartsValue,0);
  assert.ok(!before.some(c=>c.Guid===added.Guid));assert.equal(core.readProfile(s.profile,'CarsInGarage'),after.length);
  assert.equal(core.readProfile(s.profile,'GarageValue'),s.initialProfile.GarageValue+car.price);
  const result=await s.exportFiles();await core.validateManifests(result);
  const reopened=new core.SaveSession(SQL,result,revision,await core.validateManifests(result),catalog);
  try{assert.equal(reopened.garage().length,after.length);}finally{reopened.close();}
  if(process.env.FH2_TEST_ZIP) fs.writeFileSync(process.env.FH2_TEST_ZIP,new Uint8Array(await core.makeZip(result).arrayBuffer()));
});
withSave('replacement clears incompatible purchased parts and keeps active garage ID', async s => {
  const chosen=s.garage().find(c=>c.PartsValue>0);assert.ok(chosen);s.setCurrentCar(chosen.Id);
  const count=s.garage().length;s.addStock(247,chosen.Id);
  assert.equal(s.garage().length,count);assert.equal(core.readProfile(s.profile,'CareerCar'),chosen.Id);
  assert.equal(core.rows(s.db,'SELECT * FROM Career_PurchasedParts WHERE GarageId=?',[chosen.Id]).length,0);
  assert.equal(s.garage().find(c=>c.Id===chosen.Id).CarId,247);await s.exportFiles();
});
withSave('duplicate preserves BIGINT precision and copies purchased parts', async s => {
  const car=s.garage().find(c=>c.PartsValue>0);s.db.run("UPDATE Career_Garage SET VersionedTuneId=9223372036854775806 WHERE Id=?",[car.Id]);
  const count=core.rows(s.db,'SELECT COUNT(*) n FROM Career_PurchasedParts WHERE GarageId=?',[car.Id])[0].n;
  const id=s.duplicateCar(car.Id);
  assert.equal(core.rows(s.db,'SELECT CAST(VersionedTuneId AS TEXT) n FROM Career_Garage WHERE Id=?',[id])[0].n,'9223372036854775806');
  assert.equal(core.rows(s.db,'SELECT COUNT(*) n FROM Career_PurchasedParts WHERE GarageId=?',[id])[0].n,count);await s.exportFiles();
});
withSave('invalid garage action rolls back database, profile and action log', async s => {
  const before=s.db.export(),profile=s.profile.slice();assert.throws(()=>s.addStock(999999));
  assert.deepEqual(s.db.export(),before);assert.deepEqual(s.profile,profile);assert.deepEqual(s.log,[]);
});
withSave('failed action after SQL mutation restores previous state', async s => {
  const before=s.db.export(),profile=s.profile.slice(),old=s.catalog;
  // Force a malformed price only in this session after the SQL insertion.
  s.catalog={...old,cars:old.cars.map(c=>c.id===247?{...c,price:NaN}:c)};
  assert.throws(()=>s.addStock(247));assert.deepEqual(s.db.export(),before);assert.deepEqual(s.profile,profile);assert.equal(s.log.length,0);
});
withSave('regular-event unlock is idempotent and leaves current story and results untouched', async s => {
  const story=s.xml.export(),results=core.rows(s.db,'SELECT * FROM Career_EventResults');
  s.applyPreset('events');const once=s.count('Career_EventUnlock');s.applyPreset('events');assert.equal(s.count('Career_EventUnlock'),once);
  assert.equal(once,674); // 673 regular events plus the existing showcase 210.
  assert.deepEqual(s.xml.export(),story);assert.deepEqual(core.rows(s.db,'SELECT * FROM Career_EventResults'),results);await s.exportFiles();
});
withSave('championship history leaves active championship records unchanged', async s => {
  const current=core.rows(s.db,'SELECT * FROM Career_ChampionshipEventsCompleted'),story=s.xml.export();
  s.applyPreset('championships');assert.equal(s.count('Career_ChampionshipsWon'),168);
  assert.deepEqual(core.rows(s.db,'SELECT * FROM Career_ChampionshipEventsCompleted'),current);assert.deepEqual(s.xml.export(),story);await s.exportFiles();
});
withSave('remaining presets export valid SQLite and preserve co-op progress', async s => {
  s.db.run('UPDATE BucketListProgress SET CompletedCoop=1,AttemptedCoop=2,ViewedCoop=3,Viewed=7 WHERE ChallengeId=8');
  for(const name of ['destinations','perks','discover','boards','buckets'])s.applyPreset(name);
  const row=core.rows(s.db,'SELECT * FROM BucketListProgress WHERE ChallengeId=8')[0];assert.equal(row.CompletedCoop,1);assert.equal(row.AttemptedCoop,2);assert.equal(row.ViewedCoop,3);assert.equal(row.Viewed,7);
  assert.equal(s.count('PerkUnlock'),25);assert.equal(s.count('Career_DestinationUnlock'),6);
  await s.exportFiles();
});
withSave('advanced story edit uses existing properties and prevents invalid IDs', async s => {
  assert.throws(()=>s.setStoryProperty('CareerState','DestinationSelectMode','Random'));
  assert.throws(()=>s.setStoryProperty('CareerState','CurrentCampaign','999999'));
  s.setStoryProperty('CareerState','RoadTripCreatorUnlocked','true');assert.equal(s.xml.get('CareerState','RoadTripCreatorUnlocked'),'true');await s.exportFiles();
});
withSave('original fixture files remain unchanged on disk', async () => {
  for(const [name,bytes] of files)assert.deepEqual(new Uint8Array(fs.readFileSync(path.join(path.dirname(sample),...name.split('/')))),bytes,name);
});
