'use strict';
/* Check the current 69-field schema across independently specified mock cases. */
const assert=require('assert'), fs=require('fs'), path=require('path'), vm=require('vm');
const root=path.resolve(__dirname,'../..');
const mock=fs.readFileSync(path.join(__dirname,'test_mock_ee.cjs'),'utf8');
const marker='let r=row(image(100,3));';
assert(mock.includes(marker),'Mock setup marker not found');
const setup=mock.slice(0,mock.indexOf(marker));
const cases=String.raw`
let results=[];function record(x){results.push(x);}
record(row(image(100,3)));
record(row(image(100,7)));
record(row(image(0,3,false)));
record(row(image(0,3,true)));
record(row(image(0,3,false,false)));
record(row(image(100,35)));
record(row(image(367,3)));
sources={2001:annual(9,2,false,true),2002:annual(13,2)};record(row(image(100,3)));
sources={2001:annual(255,2),2002:annual(13,2)};record(row(image(100,3)));
sources={2001:annual(13,2),2002:annual(13,2)};record(row(image(100,3)));
results;
`;
const rows=vm.runInNewContext(setup+cases,{require,console,__dirname,process,Buffer});
const lines=fs.readFileSync(path.join(root,'docs','HEADER_MAP_ALL.csv'),'utf8').trim().split(/\r?\n/);
assert.strictEqual(lines.shift(),'field_name');
const fields=lines;
assert.strictEqual(fields.length,69);
assert.strictEqual(new Set(fields).size,69);
for(const row of rows){
 assert.strictEqual(row.schema_version,'rp1_ba_c3_extended_v2');
 assert.deepStrictEqual(Object.keys(row).sort(),fields.slice().sort());
}
assert.strictEqual(rows[0].modis_ba_km2,1);
assert.strictEqual(rows[1].ba_shortened_km2,1);
assert.strictEqual(rows[2].ba_state_burndate_masked_km2,1);
assert.strictEqual(rows[3].ba_state_explicit_zero_km2,1);
assert.strictEqual(rows[4].ba_state_qa_missing_km2,1);
assert.strictEqual(rows[5].ba_status,'SOURCE_PIXEL_ANOMALY');
assert.strictEqual(rows[6].ba_status,'SOURCE_PIXEL_ANOMALY');
assert.strictEqual(rows[7].ba_status,'DOMAIN_UNRESOLVED');
assert.strictEqual(rows[8].ba_status,'DOMAIN_UNRESOLVED');
assert.strictEqual(rows[9].ba_status,'ZERO_UNION_DENOMINATOR');
console.log('PASS 69-field current schema across ten independently specified mock cases');
