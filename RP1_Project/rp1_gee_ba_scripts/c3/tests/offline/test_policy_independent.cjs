'use strict';
// Runs independent assertions on the actual scientific core using the package's
// scalar/multi-pixel EE mock. This is not an Earth Engine integration test.
const fs = require('fs'), path = require('path'), vm = require('vm');
// The optional argument allows running the same file outside the package.
const base = process.argv[2] || path.resolve(__dirname, '../..');
const mock = fs.readFileSync(path.join(base, 'tests/offline/test_mock_ee.cjs'), 'utf8');
const cutoff = mock.indexOf('let r=row(image(100,3));');
if (cutoff < 0) throw Error('Mock setup marker not found');
const checks = String.raw`
const primary = ['modis_ba_km2','modis_burned_pixel_count','modis_ba_any',
 'modis_burnable_km2_union','modis_burned_frac_union','modis_burned_frac_annual'];
function withheld(r, why) {
 assert.strictEqual(r.ba_status, why);
 for (const key of primary) assert.strictEqual(r[key],null,why+' '+key);
}
function anomaly(b,q) {
 const r=row(image(b,q)); withheld(r,'SOURCE_PIXEL_ANOMALY');
 assert.strictEqual(r.ba_anomaly_area_km2,1);
 assert.strictEqual(r.ba_anomaly_pixel_count,1);
 assert.strictEqual(r.ba_state_accepted_km2,0);
 assert.strictEqual(r.ba_state_unsupported_km2,1);
 assert.strictEqual(r.ba_known_union_area_km2,1);
 assert.strictEqual(r.ba_state_closure_km2,0);
 return r;
}
let r;
for (const d of [1,366]) { r=row(image(d,3)); assert.strictEqual(r.ba_status,'ADMITTED'); assert.strictEqual(r.modis_ba_km2,1); }
r=row(image(366,7)); assert.strictEqual(r.ba_status,'ADMITTED');assert.strictEqual(r.ba_shortened_km2,1);
anomaly(367,3);
for(let c=1;c<=7;c++) anomaly(100,3+(c<<5));
r=anomaly(367,35);assert.strictEqual(r.ba_anomaly_pixel_count,1);
assert.strictEqual(r.ba_reason_positive_special_km2,1);assert.strictEqual(r.ba_reason_unexpected_burndate_km2,1);
anomaly(367,7);anomaly(100,39); // shortened does not bypass guard
for(const q of [0,1,2,3]) anomaly(367,q); // even when land/valid tests fail
for(const q of [32,33,34,35]) anomaly(100,q);
// The Z guard requires both source bands; neither absence can invent an anomaly.
r=row(image(367,3,true,false));assert.strictEqual(r.ba_status,'ADMITTED');assert.strictEqual(r.ba_anomaly_pixel_count,0);
r=row(image(367,35,false,true));assert.strictEqual(r.ba_status,'ADMITTED');assert.strictEqual(r.ba_anomaly_pixel_count,0);
r=row(image(0,35));assert.strictEqual(r.ba_status,'ADMITTED');assert.strictEqual(r.ba_anomaly_pixel_count,0);
// Anomalies outside the eligible union do not activate the guard.
sources={2001:annual(13,2),2002:annual(13,2)};
r=row(image(367,35));assert.strictEqual(r.ba_status,'ZERO_UNION_DENOMINATOR');assert.strictEqual(r.ba_anomaly_pixel_count,0);
// An unresolved eligibility takes priority over a detected anomaly in the same
// reporting unit; the known eligible pixel and anomaly diagnostic remain visible.
const originalStack=ctx.c3Stack;
function stackFor(a,b,burn,qa) {sources={2001:a,2002:b};return originalStack(ctx.c3Domain(profile,receipt),ctx.c3Evidence(image(burn,qa)),2002);}
function regionStack(stacks){let keys=Object.keys(stacks[0].b),out={};for(const k of keys)out[k]=mk(stacks.map(s=>s.b[k].v),stacks.map(s=>s.b[k].valid));return new I(out);}
function evalStack(stacks) {
 ctx.c3Stack=()=>regionStack(stacks);
 return unwrap(ctx.c3Row(unit,profile,date,{}, {},'src',['a'],'run').p);
}
// An anomalous cell outside a nonempty union must not withhold a good cell.
r=evalStack([stackFor(annual(9,2),annual(9,2),100,3),
 stackFor(annual(13,2),annual(13,2),367,35)]);
assert.strictEqual(r.ba_status,'ADMITTED');assert.strictEqual(r.modis_ba_km2,1);
assert.strictEqual(r.ba_anomaly_pixel_count,0);
// Accepted evidence remains diagnostic when another eligible cell is anomalous.
r=evalStack([stackFor(annual(9,2),annual(9,2),100,3),
 stackFor(annual(9,2),annual(9,2),367,35)]);
withheld(r,'SOURCE_PIXEL_ANOMALY');assert.strictEqual(r.ba_anomaly_pixel_count,1);
assert.strictEqual(r.ba_known_union_burned_km2,1);assert.strictEqual(r.ba_supported_fraction,1);
assert.strictEqual(r.ba_state_closure_km2,0);
let multi=regionStack([
 stackFor(annual(9,2),annual(9,2),367,3),
 stackFor(annual(9,2,false,true),annual(13,2),0,3)
]);
ctx.c3Stack=()=>multi;
r=unwrap(ctx.c3Row(unit,profile,date,{}, {},'src',['a'],'run').p);
withheld(r,'DOMAIN_UNRESOLVED'); assert.strictEqual(r.ba_anomaly_pixel_count,1);assert.strictEqual(r.ba_domain_unresolved_km2,1);
// An incomplete reducer masks primary and anomaly diagnostics and overrides both.
reducerMutation=o=>{delete o.union;return o;};
r=unwrap(ctx.c3Row(unit,profile,date,{}, {},'src',['a'],'run').p);withheld(r,'REDUCTION_INCOMPLETE');
assert.strictEqual(r.ba_anomaly_pixel_count,null);reducerMutation=null;
// Exercise the actual BA2012 window using synthetic annual source images.
ctx.c3Stack=originalStack;profile={id:'BA2012',start:2012,end:2024};date={year:2024,month:1};
sources={};receipt.lc_indexes=[];
for(let y=2012;y<=2024;y++){sources[y]=annual(9,2);receipt.lc_indexes.push(String(y));}
anomaly(367,3);
console.log('PASS independent actual-core EE-mock anomaly suite: admission, 7 codes, combined flags, shortened, missing bands, QA eligibility, outside union and status precedence');
`;
vm.runInNewContext(mock.slice(0, cutoff) + checks, {
 require, console, __dirname:path.join(base,'tests/offline'), __filename:__filename,
 process, Buffer, setTimeout, clearTimeout
}, {filename:'c3_independent_mock.cjs'});
