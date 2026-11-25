'use strict';
/* Independent UI/controller test with a mock EE/Export boundary, not live EE.
 * Usage: node test_exporter_behavior.cjs SCIENTIFIC_LOGIC EE_CORE EXPORTER_UI */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const [logic,core,app]=process.argv.slice(2);if(!app)throw Error('Expected scientific_logic.js ee_core.js exporter.js');
let buttons=[],tasks=[],prints=[],root=[];
function widget(config){return {config:config||{},children:[],state:{},add(v){this.children.push(v);return this;},style(){const self=this;return{set(k,v){self.state[k]=v;}};},setValue(v){this.config.value=v;},getValue(){return this.config.value;},setDisabled(v){this.disabled=v;}};}
function Panel(c){return widget(c);} Panel.Layout={flow:()=>({})};
const ui={Panel,Label:(v,s)=>widget(typeof v==='object'?v:{value:v,style:s}),Select:widget,Textbox:widget,Checkbox:widget,Button:c=>{buttons.push(c);return widget(c);},root:{insert:(i,p)=>root.splice(i,0,p)}};
let throwAt=0;
const ctx={ui,Map:{setOptions(){}},print(...x){prints.push(x);},Export:{table:{toDrive(x){if(throwAt&&tasks.length===throwAt)throw Error('injected task failure');tasks.push(x);}},image:{toDrive(){throw Error('unexpected raster export');}}},
 ee:{Feature:(g,o)=>o,FeatureCollection:a=>a},console};
vm.createContext(ctx);for(const p of [logic,core,app])vm.runInContext(fs.readFileSync(p,'utf8'),ctx,{filename:p});
assert.equal(root.length,1);assert.equal(tasks.length,0,'startup created a task');
const Z=['coastal_zone','forest_zone','guinea_savannah','sudan_savannah','transition_zone'];
function plan(profile,level,scope,a,b,includeInventory=false){return ctx.c3xPlan({profile:ctx.c3Profile(profile),level,scope,zones:scope==='all'?Z:['guinea_savannah'],district:'',yearStart:a,yearEnd:b,includeInventory});}
for(const [profile,a,countA,countD] of [['BA2001',2001,24,120],['BA2012',2012,13,65]]){
 let all=plan(profile,'acz','all',a,2024);assert.equal(all.length,countA);assert(all.every(x=>x.zone==='ALL_ACZ'));
 let district=plan(profile,'district','all',a,2024);assert.equal(district.length,countD);assert.equal(district.filter(x=>x.kind==='qa').length,0); assert.equal(plan(profile,'district','all',a,2024,true).filter(x=>x.kind==='qa').length,5);
 assert.equal(new Set(district.map(x=>x.name)).size,district.length,'duplicate planned names');
}
// Across every scope, a one-year default plan has one analytical task per file group.
assert.equal(plan('BA2012','acz','one',2024,2024).length,1);
assert.equal(plan('BA2012','acz','all',2024,2024).length,1);
assert.equal(plan('BA2012','district','one',2024,2024).length,1);
assert.equal(plan('BA2012','district','all',2024,2024).length,5);
assert.equal(plan('BA2012','district','one',2024,2024,true).length,2);
assert.equal(plan('BA2012','district','all',2024,2024,true).length,10);
assert.equal(plan('BA2012','acz','all',2024,2024,true).length,1);
assert.equal(ctx.C3_SELECTORS.length,69);assert(ctx.C3_SELECTORS.every(n=>!n.startsWith('c3_')));
assert(!/pilot/i.test(fs.readFileSync(app,'utf8')));assert(!('c3xBase' in ctx));
let acz=plan('BA2001','acz','one',2024,2024);
assert.deepEqual(Array.from(acz,x=>x.name),['rp1_ba_acz_monthly_c3_GS_BA2001_2024_ext']);
let dist=plan('BA2012','district','one',2024,2024,true);
assert.deepEqual(Array.from(dist,x=>x.name),['rp1_ba_district_monthly_c3_GS_BA2012_2024_ext','rp1_ba_district_monthly_c3_GS_BA2012_2024-2024_qa_by_acz']);
assert.equal(plan('BA2012','district','all',2024,2024).length,5);
assert.notEqual(plan('BA2012','district','one',2023,2023,true)[1].name,plan('BA2012','district','one',2024,2024,true)[1].name,'bounded QA filenames collide');
assert(plan('BA2012','district','one',2012,2024,true).slice(-1)[0].name.endsWith('_qa_by_acz'),'full-period QA naming drift');
assert.notEqual(plan('BA2001','acz','one',2024,2024)[0].name,plan('BA2012','acz','one',2024,2024)[0].name);
assert.equal(ctx.c3xDates(2024).length,12);assert.equal(ctx.c3xMonthList(2019,2020).length,24);
ctx.c3xProfile.setValue('BA2012');ctx.c3xPreviewYear.setValue('2011');assert.throws(()=>ctx.c3xSettings(),/inside/);
ctx.c3xPreviewYear.setValue('2024');ctx.c3xRange.setValue('Year range');ctx.c3xStart.setValue('2011');ctx.c3xEnd.setValue('2024');assert.throws(()=>ctx.c3xSettings(),/inside/);
ctx.c3xStart.setValue('2023');ctx.c3xEnd.setValue('2024');ctx.c3xLevel.setValue('district');ctx.c3xScope.setValue('All ACZs');ctx.c3xDistrict.setValue('some_id');assert.throws(()=>ctx.c3xSettings(),/district filter requires/i);ctx.c3xDistrict.setValue('');ctx.c3xInventory.setValue(true);
ctx.c3xInspectPlan();assert.equal(tasks.length,0,'plan creation emitted tasks');assert(/15 tasks planned/.test(ctx.c3xPlanText.getValue()));
// Mock only the EE-facing operations; execute the actual control and dispatcher.
const counts=Object.fromEntries(Z.map(z=>[z,1]));let sourceCalls=[];
const realBoundaryInventory=ctx.c3xBoundaryInventory;ctx.c3xBoundaryInventory=()=>({counts});const realGeometryPreflight=ctx.c3xGeometryPreflight;ctx.c3xGeometryPreflight=()=>{};ctx.c3xUnits=(level,zones,district)=>({level,zones:Array.from(zones),district,size:()=>zones.length});
ctx.c3SourcePreflight=(profile,dates,units,level)=>{sourceCalls.push({profile,dates,units,level});return {lc_indexes:Array.from({length:profile.end-profile.start+1},(_,i)=>'lc'+(i+profile.start)),ba_indexes:Array.from(dates,d=>[String(d.year)+'_'+String(d.month).padStart(2,'0')])};};
ctx.c3Rows=(units,profile,dates,receipt)=>({units,profile,dates,receipt});
// A stale plan must not dispatch after a setting changes.
ctx.c3xEnd.setValue('2023');ctx.c3xQueue();assert.equal(tasks.length,0);assert(/Inspect the current export plan/.test(ctx.c3xStatus.getValue()));ctx.c3xEnd.setValue('2024');ctx.c3xInspectPlan();
ctx.c3xQueue();assert.equal(tasks.length,15);assert.equal(sourceCalls.length,1);assert.equal(sourceCalls[0].dates.length,24);
const ext=tasks.filter(t=>t.description.endsWith('_ext'));assert.equal(ext.length,10);
for(const t of ext){assert.equal(t.selectors.length,69);assert.equal(t.collection.profile.start,2012);assert.equal(t.collection.profile.end,2024);assert.equal(t.collection.dates.length,12);assert.equal(t.collection.receipt.lc_indexes.length,13);assert.equal(t.collection.receipt.ba_indexes.length,12);for(let i=0;i<12;i++)assert(t.collection.receipt.ba_indexes[i][0].startsWith(String(t.collection.dates[i].year)+'_'));}
assert.equal(tasks.filter(t=>t.description.includes('_qa_by_acz')).length,5);assert(/NOT been submitted/.test(ctx.c3xStatus.getValue()));
ctx.c3xQueue();assert.equal(tasks.length,15,'duplicate plan silently emitted tasks');assert(/already created/.test(ctx.c3xStatus.getValue()));
// Missing/ambiguous source must block all exports before any task creation.
tasks=[];ctx.c3xLastPlan='';ctx.c3xCreatedPrefixes=Object.create(null);ctx.c3SourcePreflight=()=>{throw Error('A monthly MCD64A1 source is missing or ambiguous');};ctx.c3xQueue();assert.equal(tasks.length,0);assert(/BLOCKED/.test(ctx.c3xStatus.getValue()));
// Explicitly surface partial creation when a later task definition fails.
ctx.c3SourcePreflight=(p,dates)=>({lc_indexes:Array.from({length:13},(_,i)=>'lc'+i),ba_indexes:dates.map(()=>['x'])});throwAt=2;ctx.c3xQueue();assert.equal(tasks.length,2);assert(/PARTIAL/.test(ctx.c3xStatus.getValue()));throwAt=0;ctx.c3xQueue();assert.equal(tasks.length,2,'partial retry was not blocked');assert(/already created/.test(ctx.c3xStatus.getValue()));
// The all-ACZ scope combines five zone collections into each annual table.
tasks=[];ctx.c3xCreatedPrefixes=Object.create(null);ctx.c3xLastPlan='';ctx.c3xLevel.setValue('acz');ctx.c3xScope.setValue('All ACZs');ctx.c3xStart.setValue('2023');ctx.c3xEnd.setValue('2024');ctx.c3xInspectPlan();ctx.c3xQueue();assert.equal(tasks.length,2);
for(const t of tasks){assert.equal(t.collection.units.zones.length,5);assert(/ALL_ACZ/.test(t.description));assert.equal(t.collection.profile.start,2012);assert.equal(t.collection.dates.length,12);}
assert.equal(tasks.filter(t=>t.selectors.length===23).length,0);assert.equal(tasks.filter(t=>t.selectors.length===69).length,2);
// With the optional district inventory OFF, one district-zone year creates only one analytical task.
tasks=[];ctx.c3xCreatedPrefixes=Object.create(null);ctx.c3xLastPlan='';ctx.c3xLevel.setValue('district');ctx.c3xScope.setValue('Selected ACZ');ctx.c3xZoneSelect.setValue('forest_zone');ctx.c3xDistrict.setValue('');ctx.c3xRange.setValue('Selected year');ctx.c3xPreviewYear.setValue('2024');ctx.c3xInventory.setValue(false);
ctx.c3xInspectPlan();assert(/1 tasks planned/.test(ctx.c3xPlanText.getValue()));ctx.c3xQueue();assert.equal(tasks.length,1);assert.equal(tasks[0].selectors.length,69);assert(!/_qa_by_acz/.test(tasks[0].description));
// Opting into inventory changes the plan and adds exactly one separate QA task.
tasks=[];ctx.c3xCreatedPrefixes=Object.create(null);ctx.c3xLastPlan='';ctx.c3xInventory.setValue(true);ctx.c3xInspectPlan();assert(/2 tasks planned/.test(ctx.c3xPlanText.getValue()));ctx.c3xQueue();assert.equal(tasks.length,2);assert.equal(tasks.filter(t=>/_qa_by_acz/.test(t.description)).length,1);
// Selected-month inspection emits one extended table, retaining preview-zone scope.
tasks=[];ctx.c3xCreatedPrefixes=Object.create(null);ctx.c3xLevel.setValue('district');ctx.c3xScope.setValue('All ACZs');ctx.c3xZoneSelect.setValue('transition_zone');ctx.c3xDistrict.setValue('');ctx.c3xSelectedMonth();
assert.equal(tasks.length,1);assert.equal(tasks[0].selectors.length,69);assert.equal(tasks[0].collection.units.zones.length,1);assert.equal(tasks[0].collection.units.zones[0],'transition_zone');
assert(/^rp1_ba_inspection_c3_district_TZ_BA2012_202401_ext$/.test(tasks[0].description));assert(!/pilot/i.test(tasks[0].description));
// An inspection retry must not silently reuse the same session prefix.
ctx.c3xSelectedMonth();assert.equal(tasks.length,1);assert(/already created/.test(ctx.c3xStatus.getValue()));
// Verify actual geometry gate: bad polygons are BLOCKED, never dropped.
function geometryUnits(values){
 const units=values.map(v=>({props:{unit_id:v.id,parent_id:v.zone},get(k){return this.props[k];},geometry(){return{area(){return v.area}}},set(k,x){this.props[k]=x&&x.getInfo?x.getInfo():x;return this;}}));
 const collection=items=>({size:()=>items.length,aggregate_array:k=>items.map(x=>x.props[k]),map:f=>collection(items.map(f))});return collection(units);
}
ctx.ee.Feature=(g,o)=>o===undefined?g:o;ctx.ee.Dictionary=x=>({getInfo:()=>x});ctx.ee.FeatureCollection=x=>x;
function inventoryUnits(records){const items=records.map(r=>({props:{...r},get(k){return this.props[k]},set(k,x){this.props[k]=x&&x.getInfo?x.getInfo():x;return this;}})); const make=a=>({size:()=>a.length,aggregate_array:k=>a.map(x=>x.props[k]),map:f=>make(a.map(f))});return make(items);}
const codes=['CZ','FZ','GS','SS','TZ'];const goodRecords=Z.map((z,i)=>({zone_id:z,zone_name:z.toUpperCase(),zone_code:codes[i]}));
ctx.ee.FeatureCollection=()=>inventoryUnits(goodRecords);assert.equal(realBoundaryInventory('acz').total,5);
ctx.ee.FeatureCollection=()=>inventoryUnits([...goodRecords,{...goodRecords[0]}]);assert.throws(()=>realBoundaryInventory('acz'),/Duplicate unit ID/);
ctx.ee.FeatureCollection=()=>inventoryUnits(goodRecords.map((r,i)=>i===1?{...r,zone_code:'BAD'}:r));assert.throws(()=>realBoundaryInventory('acz'),/Incorrect zone_code/);
ctx.ee.FeatureCollection=()=>inventoryUnits(goodRecords.map((r,i)=>i===1?{...r,zone_name:''}:r));assert.throws(()=>realBoundaryInventory('acz'),/Blank boundary identity/);
ctx.ee.FeatureCollection=x=>x;
const bad=geometryUnits([{id:'good',zone:'guinea_savannah',area:10},{id:'bad',zone:'guinea_savannah',area:0}]);
ctx.c3xCreatedPrefixes=Object.create(null);tasks=[];const geometrySettings={profile:ctx.c3Profile('BA2012'),level:'district',scope:'one',zones:['guinea_savannah'],district:'',yearStart:2024,yearEnd:2024};
assert.throws(()=>realGeometryPreflight(bad,geometrySettings),/No data tasks created/);assert.equal(tasks.length,0);assert.equal(ctx.c3xBoundaryIssues.length,1);ctx.c3xExportBoundaryIssues();assert.equal(tasks.length,1);assert.equal(tasks[0].collection[0].disposition,'BLOCKED_NOT_DROPPED');assert(/_2024-2024_boundary$/.test(tasks[0].description));
const good=geometryUnits([{id:'good',zone:'guinea_savannah',area:10}]);realGeometryPreflight(good,geometrySettings);assert.equal(ctx.c3xBoundaryIssues.length,0);assert.equal(ctx.c3xBoundaryIssueSettings,null);
console.log('PASS exporter plans, names, batch scopes, pinned source slicing, 69 fields, duplicate warning, missing-source blocking and partial-task reporting');
ctx.C3.observationEndYear=2025;
ctx.c3xPreviewYear.setValue('2025');ctx.c3xRange.setValue('Selected year');
const futureSettings=ctx.c3xSettings();
assert.equal(futureSettings.yearStart,2025);
assert.equal(futureSettings.yearEnd,2025);
assert.equal(futureSettings.profile.end,2024,'future export changed fixed support');
assert.equal(ctx.c3Selectors(futureSettings.profile,2025).length,70);
ctx.c3xPreviewYear.setValue('2026');
assert.throws(()=>ctx.c3xSettings(),/configured observation/);
console.log('PASS configured future exporter year and fixed-union bounds');
