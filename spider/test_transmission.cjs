const {test} = require('node:test');
const assert = require('node:assert/strict');
const {Tracker, DURATION} = require('./web/transmission.js');
const hospital = (hospitalId, extra = {}) => ({hospitalId, zone: 1, status: 'pending', ...extra});
const scene = hospitals => ({caseId: 'one', zoneActive: [1], hospitals});
const origin = [126.978, 37.5665, 14], target = () => [127, 37.58, 500];
test('only current-zone hub targets receive information, excluding unavailable/full hospitals', () => {
 const c = scene([hospital('ok'),hospital('outer',{zone:2}),hospital('full',{availableBedCount:0,bedCountUnknown:false}),hospital('reject',{status:'rejected'}),hospital('excluded',{excluded:true}),hospital('blocked',{unavailableReason:'blocked'}),hospital('unknown',{availableBedCount:0,bedCountUnknown:true})]);
 const t=new Tracker();t.sync([c],0);
 assert.deepEqual(t.frame(c,origin,target,1000,false).map(x=>x.hospitalId),['ok','unknown']);
});
test('thread grows from ambulance, reaches exact hospital node and settles without replay on updates', () => {
 const c=scene([hospital('A')]), t=new Tracker();t.sync([c],0);
 const half=t.frame(c,origin,target,DURATION/2,false)[0];
 assert.deepEqual(half.path[0],origin);assert.equal(half.progress,.5);assert.ok(half.path.at(-1)[0]<target()[0]);
 t.sync([c],DURATION+100);
 const end=t.frame(c,origin,target,10000,false)[0];
 assert.deepEqual(end.path.at(-1),target());assert.equal(end.active,false);assert.equal(end.settled,true);
});
test('zone expansion animates only newly requested hospitals', () => {
 const a=scene([hospital('A'),hospital('B',{zone:2})]),t=new Tracker();t.sync([a],0);
 const expanded={...a,zoneActive:[1,2]};t.sync([expanded],10000);
 const beams=t.frame(expanded,origin,target,10500,false);
 assert.equal(beams.find(b=>b.hospitalId==='A').active,false);
 assert.ok(beams.find(b=>b.hospitalId==='B').progress<1);
});
test('confirmation and case closure remove all dissemination threads', () => {
 const c=scene([hospital('A')]),t=new Tracker();t.sync([c],0);
 const confirmed=scene([hospital('A',{status:'confirmed'})]);t.sync([confirmed],100);
 assert.equal(t.frame(confirmed,origin,target,500,false).length,0);
 t.sync([],600);assert.equal(t.cases.size,0);
});
test('reduced motion shows complete connections without travelling points or arrival waves', () => {
 const c=scene([hospital('A')]),t=new Tracker();t.sync([c],0);
 const b=t.frame(c,origin,target,100,true)[0];
 assert.deepEqual(b.path.at(-1),target());assert.equal(b.active,false);assert.equal(b.arrival,null);
});

test('patient KTAS cap blocks lower-capacity hospital threads even if a stale message lists them', () => {
 const t=new Tracker();
 const c={...scene([hospital('fit',{ktasSuitability:{hospitalKtas:2,requiredCapacity:3,effectiveCapacity:3,eligible:true}}),hospital('low',{ktasSuitability:{hospitalKtas:3,requiredCapacity:3,effectiveCapacity:2.8,eligible:false}})]),ktasLevel:2};
 t.sync([c],0);
 assert.deepEqual(t.frame(c,origin,target,1000,false).map(x=>x.hospitalId),['fit']);
});

test('exact KTAS excludes both higher and lower representative hospital levels', () => {
 const t=new Tracker(), c={...scene([1,2,3].map(k=>hospital('K'+k,{ktasSuitability:{hospitalKtas:k,patientKtas:2,requiredCapacity:3,effectiveCapacity:5-k,eligible:k===2}}))),ktasLevel:2};
 t.sync([c],0);assert.deepEqual(t.frame(c,origin,target,1000,false).map(x=>x.hospitalId),['K2']);
});

test('a single packet finishes once and does not repeat after two seconds', () => {
 const {packetProgress,DURATION}=require('./web/transmission.js');
 assert.ok(packetProgress(700)>0);
 assert.equal(packetProgress(DURATION+1),null);
 assert.equal(packetProgress(2700),null);
 assert.equal(packetProgress(10000),null);
});
