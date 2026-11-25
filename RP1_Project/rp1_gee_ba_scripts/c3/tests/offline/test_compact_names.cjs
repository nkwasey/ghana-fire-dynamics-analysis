'use strict';
/* Independent naming-contract regression; mocks the EE and Drive boundaries.
 * Run: node test_compact_names.cjs SCIENTIFIC_LOGIC EE_CORE EXPORTER_UI */
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const [logic, core, app] = process.argv.slice(2);
if (!app) throw Error('Expected scientific_logic.js ee_core.js exporter.js');
const tasks = [], logs = [];
function widget(config) { return {config:config||{}, children:[], state:{}, add(v){this.children.push(v);return this;}, style(){const self=this;return {set(k,v){self.state[k]=v;}};}, setValue(v){this.config.value=v;}, getValue(){return this.config.value;}, setDisabled(v){this.disabled=v;}}; }
function Panel(c){return widget(c);} Panel.Layout={flow:()=>({})};
const ui={Panel,Label:(v,s)=>widget(typeof v==='object'?v:{value:v,style:s}),Select:widget,Textbox:widget,Checkbox:widget,Button:widget,root:{insert(){}}};
const ctx={ui,Map:{setOptions(){}},print(...x){logs.push(x);},Export:{table:{toDrive(x){tasks.push(x);}}},ee:{Feature:(g,o)=>o,FeatureCollection:a=>a},console};
vm.createContext(ctx);
for (const p of [logic,core,app]) vm.runInContext(fs.readFileSync(p,'utf8'),ctx,{filename:p});
const zones=['coastal_zone','forest_zone','guinea_savannah','sudan_savannah','transition_zone'];
const code={coastal_zone:'CZ',forest_zone:'FZ',guinea_savannah:'GS',sudan_savannah:'SS',transition_zone:'TZ',ALL_ACZ:'ALL_ACZ'};
// Compute the FNV-1a-style hash independently over the FULL original JS UTF-16 ID.
function tag(id){let h=2166136261;for(let i=0;i<id.length;i++)h=Math.imul(h^id.charCodeAt(i),16777619)>>>0;return id.replace(/[^A-Za-z0-9_-]/g,'_').slice(0,12)+'_'+h.toString(16).padStart(8,'0');}
function prefix(level,zone,domain,id=''){return ['rp1','ba',level,'monthly','c3',code[zone],domain].join('_')+(id?'_D_'+tag(id):'');}
function annual(level,zone,domain,year,id=''){return prefix(level,zone,domain,id)+'_'+year+'_ext';}
function qa(zone,domain,start,end,id=''){return prefix('district',zone,domain,id)+'_'+start+'-'+end+'_qa_by_acz';}
function boundary(zone,domain,start,end,id=''){return prefix('district',zone,domain,id)+'_'+start+'-'+end+'_boundary';}
function inspection(level,zone,domain,year,month,id=''){return ['rp1','ba','inspection','c3',level,code[zone],domain,String(year)+String(month).padStart(2,'0')].join('_')+(id?'_D_'+tag(id):'')+'_ext';}
function valid(n){assert.equal(typeof n,'string');assert(n.length>0&&n.length<=80,`invalid length ${n.length}: ${n}`);assert(/^[A-Za-z0-9_-]+$/.test(n),`invalid characters: ${n}`);}
function spec(domain,level,scope,zone,district,a,b,inventory){return {profile:ctx.c3Profile(domain),level,scope,zones:scope==='all'?zones:[zone],previewZone:zone,district,yearStart:a,yearEnd:b,includeInventory:inventory,date:{year:2024,month:1}};}
// Literal naming requested by user, independent from the generator helper.
for(const domain of ['BA2001','BA2012']){
 const s=spec(domain,'district','one','transition_zone','',2024,2024,false);
 assert.equal(ctx.c3xNames(s,'transition_zone',2024).ext,`rp1_ba_district_monthly_c3_TZ_${domain}_2024_ext`);
}
assert.equal(tag('Asutifi_North'),'Asutifi_Nort_5b76ed12');
const ids=['Asutifi_North','A/B : µ 🤝','long_district_identifier_'.repeat(20)+'A','long_district_identifier_'.repeat(20)+'B','___','a-b_c'];
for(const id of ids){
 assert.equal(ctx.c3xIdTag(id),tag(id),'hash must use full, unsanitized district ID');
 const s=spec('BA2012','district','one','transition_zone',id,2022,2024,true),n=ctx.c3xNames(s,'transition_zone',2024);
 assert.equal(n.ext,annual('district','transition_zone','BA2012',2024,id));assert.equal(n.qa,qa('transition_zone','BA2012',2022,2024,id));
 valid(n.ext);valid(n.qa);assert.notEqual(n.ext,annual('district','transition_zone','BA2012',2024),'filtered and unfiltered annual aliases');
}
assert.notEqual(ctx.c3xIdTag(ids[2]),ctx.c3xIdTag(ids[3]),'long IDs that differ after truncation were not distinguished');
// A 32-bit tag is not globally collision-free. Deliberately colliding IDs
// illustrate why the in-session prefix guard must block duplicate names and why
// full IDs and external task/file inventories remain necessary.
const collisionIds=['abcdefghijklu0evfp_glr','abcdefghijkldrbs3o_tt0'];
assert.notEqual(collisionIds[0],collisionIds[1]);assert.equal(tag(collisionIds[0]),tag(collisionIds[1]));
const collisionNames=collisionIds.map(id=>'folder/'+annual('district','transition_zone','BA2012',2024,id));
assert.throws(()=>ctx.c3xCheckUnused(collisionNames),/already created/);
// Collision preflight examines the full district asset before a filtered task,
// even when the two colliding records arrive in either order. Unfiltered plans
// remain allowed and a name collision across different ACZ codes is harmless.
const inventory=ctx.c3xBoundaryInventory, savedFeature=ctx.ee.Feature, savedCollection=ctx.ee.FeatureCollection;
function inventoryUnits(records){const items=records.map(r=>({props:{...r},get(k){return this.props[k];},set(k,x){this.props[k]=x&&x.getInfo?x.getInfo():x;return this;}}));const make=a=>({size:()=>a.length,aggregate_array:k=>a.map(x=>x.props[k]),map:f=>make(a.map(f))});return make(items);}
ctx.ee.Feature=(g,o)=>o===undefined?g:o;ctx.ee.Dictionary=x=>({getInfo:()=>x});
function districtRow(id,zone){return {dist_id:id,dist_name:id,zone_id:zone,zone_code:code[zone],zone_name:zone};}
const sameZone=collisionIds.map(id=>districtRow(id,'transition_zone'));
for(const rows of [sameZone,[...sameZone].reverse()]){
 ctx.ee.FeatureCollection=()=>inventoryUnits(rows);
 for(const id of collisionIds)assert.throws(()=>inventory('district',id,'transition_zone'),/tag collision.*no data tasks created/i);
 assert.doesNotThrow(()=>inventory('district','','transition_zone'),'unfiltered inventory must remain valid');
}
ctx.ee.FeatureCollection=()=>inventoryUnits([districtRow(collisionIds[0],'transition_zone'),districtRow(collisionIds[1],'forest_zone')]);
assert.doesNotThrow(()=>inventory('district',collisionIds[0],'transition_zone'),'different zone codes yield distinct task names');
assert.doesNotThrow(()=>inventory('district',collisionIds[1],'forest_zone'),'different zone codes yield distinct task names');
ctx.ee.Feature=savedFeature;ctx.ee.FeatureCollection=savedCollection;delete ctx.ee.Dictionary;
const names=[];
for(const [domain,start] of [['BA2001',2001],['BA2012',2012]]){
 for(const level of ['acz','district']) for(const zone of zones){
  const s=spec(domain,level,'one',zone,'',start,2024,true);
  const plan=ctx.c3xPlan(s), expectedCount=2025-start+(level==='district'?1:0);
  assert.equal(plan.length,expectedCount);
  for(let year=start;year<=2024;year++){
   const n=ctx.c3xNames(s,zone,year);assert.equal(n.ext,annual(level,zone,domain,year));valid(n.ext);names.push(n.ext);
  }
  if(level==='district'){
   const n=ctx.c3xNames(s,zone,start);assert.equal(n.qa,qa(zone,domain,start,2024));valid(n.qa);names.push(n.qa);
   const other=spec(domain,level,'one',zone,'',2024,2024,true);assert.notEqual(n.qa,ctx.c3xNames(other,zone,2024).qa);
  }
 }
 const combined=spec(domain,'acz','all','forest_zone','',2024,2024,false), p=ctx.c3xPlan(combined);
 assert.equal(p.length,1);assert.equal(p[0].name,annual('acz','ALL_ACZ',domain,2024));valid(p[0].name);names.push(p[0].name);
}
assert.equal(new Set(names).size,names.length,'scope/date/domain planned names collide');
assert.doesNotThrow(()=>ctx.c3xValidateName('x'.repeat(80)));
for(const n of ['', 'bad name', 'invalid.csv', 'x'.repeat(81)])assert.throws(()=>ctx.c3xValidateName(n),/nam|prefix|length|character/i);
assert.equal(qa('transition_zone','BA2012',2022,2024,ids[2]).length,80,'long filtered QA should fit the internal cap exactly');
assert.equal(ctx.C3_SELECTORS.length,69);assert.equal(new Set(Array.from(ctx.C3_SELECTORS)).size,69);assert(!Array.from(ctx.C3_SELECTORS).some(x=>x.startsWith('c3_')));
// Exercise real callbacks, with only Earth Engine and Drive mocked. Every task
// description must match the planned name and Drive prefix, for every path.
const counts=Object.fromEntries(zones.map(z=>[z,1]));
ctx.c3xBoundaryInventory=()=>({counts});ctx.c3xGeometryPreflight=()=>{};
ctx.c3xUnits=(level,zs,district)=>({level,zones:Array.from(zs),district,size:()=>zs.length});
ctx.c3SourcePreflight=(profile,dates)=>({lc_indexes:Array.from({length:profile.end-profile.start+1},(_,i)=>'lc'+i),ba_indexes:dates.map(()=>['image'])});
ctx.c3Rows=(units,profile,dates,receipt)=>({units,profile,dates,receipt});
// Real queue dispatcher with colliding asset IDs must stop BEFORE defining any
// Drive task, rather than only reporting the collision from a helper in isolation.
ctx.ee.Feature=(g,o)=>o===undefined?g:o;ctx.ee.Dictionary=x=>({getInfo:()=>x});ctx.ee.FeatureCollection=()=>inventoryUnits(sameZone);
ctx.c3xBoundaryInventory=inventory;
ctx.c3xProfile.setValue('BA2012');ctx.c3xLevel.setValue('district');ctx.c3xScope.setValue('Selected ACZ');ctx.c3xZoneSelect.setValue('transition_zone');ctx.c3xDistrict.setValue(collisionIds[0]);ctx.c3xPreviewYear.setValue('2024');ctx.c3xPreviewMonth.setValue('1');ctx.c3xRange.setValue('Selected year');ctx.c3xInventory.setValue(true);
ctx.c3xInspectPlan();ctx.c3xQueue();assert.equal(tasks.length,0,'colliding tag must block all task definitions');assert(/BLOCKED:.*tag collision/i.test(ctx.c3xStatus.getValue()));
ctx.ee.Feature=savedFeature;ctx.ee.FeatureCollection=savedCollection;delete ctx.ee.Dictionary;ctx.c3xBoundaryInventory=()=>({counts});
ctx.c3xProfile.setValue('BA2012');ctx.c3xLevel.setValue('district');ctx.c3xScope.setValue('Selected ACZ');ctx.c3xZoneSelect.setValue('transition_zone');ctx.c3xDistrict.setValue(ids[2]);ctx.c3xPreviewYear.setValue('2024');ctx.c3xPreviewMonth.setValue('1');ctx.c3xRange.setValue('Selected year');ctx.c3xInventory.setValue(true);
ctx.c3xInspectPlan();const plan=ctx.c3xPlan(ctx.c3xSettings());ctx.c3xQueue();
assert.equal(tasks.length,2);for(let i=0;i<2;i++){assert.equal(tasks[i].description,plan[i].name);assert.equal(tasks[i].fileNamePrefix,plan[i].name);valid(tasks[i].description);}
assert.equal(tasks[0].description,annual('district','transition_zone','BA2012',2024,ids[2]));assert.equal(tasks[0].selectors.length,69);assert.equal(tasks[1].description,qa('transition_zone','BA2012',2024,2024,ids[2]));assert.equal(tasks[1].selectors.length,14);
ctx.c3xQueue();assert.equal(tasks.length,2,'duplicate session tasks silently created');assert(/already created/.test(ctx.c3xStatus.getValue()));
ctx.c3xSelectedMonth();assert.equal(tasks.length,3);const inspect=inspection('district','transition_zone','BA2012',2024,1,ids[2]);assert.equal(tasks[2].description,inspect);assert.equal(tasks[2].fileNamePrefix,inspect);assert.equal(tasks[2].selectors.length,69);valid(inspect);
ctx.c3xBoundaryIssueSettings=ctx.c3xSettings();ctx.c3xBoundaryIssues=[{unit_id:ids[2],zone_id:'transition_zone',area_m2:0,reason:'ZERO_GHANA_CLIPPED_VECTOR_AREA'}];ctx.c3xExportBoundaryIssues();
assert.equal(tasks.length,4);const bound=boundary('transition_zone','BA2012',2024,2024,ids[2]);assert.equal(tasks[3].description,bound);assert.equal(tasks[3].fileNamePrefix,bound);valid(bound);assert.equal(tasks[3].collection[0].disposition,'BLOCKED_NOT_DROPPED');
assert.equal(new Set(tasks.map(t=>t.description)).size,tasks.length);
// A changed setting invalidates an inspected plan and cannot queue a task.
ctx.c3xCreatedPrefixes=Object.create(null);ctx.c3xLastPlan='';tasks.length=0;
ctx.c3xDistrict.setValue('');ctx.c3xInventory.setValue(false);ctx.c3xInspectPlan();ctx.c3xPreviewYear.setValue('2023');ctx.c3xQueue();assert.equal(tasks.length,0);assert(/Inspect the current export plan/.test(ctx.c3xStatus.getValue()));
// Combined ACZ remains exactly the old naming and retains its five-zone scope.
ctx.c3xPreviewYear.setValue('2024');ctx.c3xLevel.setValue('acz');ctx.c3xScope.setValue('All ACZs');ctx.c3xInspectPlan();const allPlan=ctx.c3xPlan(ctx.c3xSettings());ctx.c3xQueue();
assert.equal(tasks.length,1);assert.equal(tasks[0].description,annual('acz','ALL_ACZ','BA2012',2024));assert.equal(tasks[0].description,allPlan[0].name);assert.equal(tasks[0].fileNamePrefix,tasks[0].description);assert.equal(tasks[0].collection.units.zones.length,5);assert.equal(tasks[0].selectors.length,69);
ctx.c3xBoundaryIssueSettings=ctx.c3xSettings();ctx.c3xBoundaryIssues=[{unit_id:'forest_zone',zone_id:'forest_zone',area_m2:0,reason:'ZERO_GHANA_CLIPPED_VECTOR_AREA'}];ctx.c3xExportBoundaryIssues();
assert.equal(tasks.length,2);assert.equal(tasks[1].description,'rp1_ba_acz_monthly_c3_FZ_BA2012_boundary_issue_log_2024_to_2024');valid(tasks[1].description);assert.equal(tasks[1].fileNamePrefix,tasks[1].description);
console.log('PASS annual, QA, inspection and boundary naming: full-period scopes, Unicode/long IDs, 80 cap, plan/task/prefix agreement, duplicates, stale plan and 69-field selector');
