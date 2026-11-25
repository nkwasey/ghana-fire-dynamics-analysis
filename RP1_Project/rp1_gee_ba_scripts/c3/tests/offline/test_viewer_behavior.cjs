'use strict';
/* Independent UI/controller mock; no network or Earth Engine execution.
 * node test_viewer_behavior.cjs SCIENCE CORE VIEWER LST FOOTER */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const inputs=process.argv.slice(2);if(inputs.length!==5)throw Error('Expected SCIENCE CORE VIEWER LST FOOTER');
let buttons=[],checks=[],task=[],prints=[],root=[],centered=[],added=[];
function widget(config){return {config:config||{},children:[],state:{},add(v){this.children.push(v);return this;},style(){const self=this;return {set(k,v){self.state[k]=v;}}},setValue(v){this.config.value=v;if(this.cb)this.cb(v);},getValue(){return this.config.value;},setDisabled(v){this.disabled=v;},onChange(fn){this.cb=fn;},items(){const self=this;return {reset(values){self.config.items=values;}}}};}
function Panel(c){return widget(c);}Panel.Layout={flow:()=>({})};
const ui={Panel,Label:(v,s)=>widget(typeof v==='object'?v:{value:v,style:s}),Select:widget,Textbox:widget,
 Checkbox:c=>{checks.push(c);return widget(c)},Button:c=>{buttons.push(c);return widget(c)},root:{insert:(i,p)=>root.splice(i,0,p)}};
const fc=arg=>({arg,geometry:()=>({type:'geometry',from:arg}),size:()=>1});
const ee={Feature:(g,props)=>({geometry:g,props}),FeatureCollection:fc,List:a=>({getInfo:()=>Array.from(a)}),Image:()=>({select:()=>({projection:()=>({getInfo:()=>({crs:'lst_crs',transform:[1,0,0,0,-1,0]})})})})};
const ctx={ui,ee,Map:{setOptions(){},centerObject(x,z){centered.push({x,z});},add(x){added.push(x);}},
 Export:{table:{toDrive(x){task.push(x)}},image:{toDrive(x){task.push(x)}}},print(...x){prints.push(x)},console};
vm.createContext(ctx);for(const p of inputs)vm.runInContext(fs.readFileSync(p,'utf8'),ctx,{filename:p});
assert.equal(root.length,1);assert.equal(task.length,0,'viewer created startup tasks');assert.equal(ctx.levelSelect.getValue(),'ghana');
assert(centered.some(x=>x.x.arg===ctx.C3.ghanaAsset),'Ghana was not selected as startup extent');
let s=ctx.c3Settings();assert.equal(s.level,'ghana');assert.equal(s.units.arg[0].props.unit_id,'GHA');assert.equal(s.units.arg[0].geometry.from,ctx.C3.ghanaAsset);
ctx.levelSelect.setValue('district');assert.throws(()=>ctx.c3Settings(),/exact dist_id/);ctx.levelSelect.setValue('ghana');
let union=checks.find(c=>c.label==='Selected period fixed union');assert(union);union.onChange(true);assert.equal(ctx.show.union,true,'checkbox state lost before preview');
let toggle=null;ctx.previewReady=true;ctx.previewLayers.union={setShown(v){toggle=v;}};union.onChange(false);assert.equal(ctx.show.union,false);assert.equal(toggle,false);
ctx.profileSelect.setValue('BA2001');ctx.yearBox.setValue('2001');ctx.profileSelect.setValue('BA2012');assert.equal(ctx.yearBox.getValue(),'2012','domain switch leaves invalid year');
ctx.yearBox.setValue('2024');s=ctx.c3Settings();assert.equal(ctx.c3ScopeTag(s),'GHA');assert.equal(ctx.c3DatesForYear(2024).length,12);
ctx.c3ViewPlan(false);assert.equal(task.length,0);assert(/Plan: 2 tasks/.test(ctx.status.getValue()));ctx.c3ViewPlan(true);assert.equal(task.length,0);assert(/Plan: 25 tasks/.test(ctx.status.getValue()));
let annualPlan=prints.filter(x=>String(x[0]).includes('VIEWER PRODUCT PLAN')).slice(-1)[0][1];
assert.equal(annualPlan.count,25);assert.equal(new Set(Array.from(annualPlan.prefixes)).size,25);
assert(annualPlan.prefixes.some(x=>x==='MCD64A1_061_Burn_c3_BA2012_GHA_2024_01'));assert(annualPlan.prefixes.some(x=>x==='MOD11A1_061_DN_c3_GHA_2024_01'));
// Execute the real controller; guard against creation of a national CSV row.
let rowCalls=0;ctx.c3SourcePreflight=(profile,dates)=>({lc_indexes:Array.from({length:13},(_,i)=>String(2012+i)),ba_indexes:dates.map(()=>['2024_01_01'])});ctx.c3Domain=()=>({});ctx.c3BaImage=()=>({});ctx.c3Evidence=()=>({});ctx.c3ShowMap=()=>{};ctx.c3Rows=()=>{rowCalls++;return {};};
ctx.c3Do('inspect');assert.equal(rowCalls,0,'Ghana display attempted national reporting row');ctx.c3Do('csv_month');assert.equal(task.length,0);assert(/National reporting rows are not defined/.test(ctx.status.getValue()));
// Preflight failure blocks map and any raster task.
ctx.c3SourcePreflight=()=>{throw Error('missing source')};ctx.c3Do('ba_month');assert.equal(task.length,0);assert(/BLOCKED/.test(ctx.status.getValue()));
// Exercise standard bundle orchestration with mocked source probes and output calls.
ctx.c3SourcePreflight=(profile,dates)=>({lc_indexes:Array.from({length:13},(_,i)=>String(2012+i)),ba_indexes:dates.map(()=>['2024_01_01'])});
ctx.c3LstSource=()=>({size:()=>10,first:()=>({})});ctx.c3Domain=()=>({});
ctx.c3QueueBa=(s,d,date)=>task.push({description:ctx.c3BaName(s,date)});ctx.c3QueueLstKnown=(s,date)=>task.push({description:ctx.c3LstName(s,date)});ctx.c3QueueLcKnown=s=>task.push({description:ctx.c3LcName(s)});
ctx.c3ViewPlan(false);ctx.c3QueueStandard(false);assert.equal(task.length,2);task=[];ctx.c3ViewPlan(true);ctx.c3QueueStandard(true);assert.equal(task.length,25);
assert.deepEqual(Array.from(task,x=>x.description),Array.from(annualPlan.prefixes),'planned and dispatched annual names differ');
// A plan no longer matches after date changes. A later task-definition failure
// must honestly report the number already created, without claiming success.
task=[];ctx.yearBox.setValue('2023');ctx.c3QueueStandard(true);assert.equal(task.length,0);assert(/matching export plan/.test(ctx.status.getValue()));ctx.yearBox.setValue('2024');ctx.c3ViewPlan(false);
ctx.c3QueueBa=(s,d,date)=>{const name=ctx.c3BaName(s,date);task.push({description:name});return name;};ctx.c3QueueLstKnown=()=>{throw Error('injected task failure');};ctx.c3QueueStandard(false);assert.equal(task.length,1);assert(/PARTIAL: 1/.test(ctx.status.getValue()));
console.log('PASS viewer Ghana default, control state, no startup tasks, domain switching, national-row guard, plans and mocked batch wiring');
// Selected-month CSV must expose the new public schema, use a neutral filename,
// and request all 69 extended fields. This uses mocks; EE serialization is separate.
task=[];
ctx.c3Settings=()=>({profile:{id:'BA2012',start:2012,end:2024},level:'district',zone:'transition_zone',district:'Asutifi_North',date:{year:2024,month:1},units:{selected:'one'}});
ctx.c3SourcePreflight=(profile,dates)=>({lc_indexes:Array.from({length:13},(_,i)=>String(2012+i)),ba_indexes:dates.map(()=>['2024_01_01'])});
ctx.c3Rows=(units,profile,dates,receipt)=>({marker:'extended',units,profile,dates,receipt});
ctx.c3Do('csv_month');
assert.equal(task.length,1,ctx.status.getValue());
const csvTask=task[0];
assert.equal(csvTask.fileFormat,'CSV');assert.equal(csvTask.selectors.length,69);
assert.equal(csvTask.collection.marker,'extended');
assert.equal(csvTask.folder,'RP1_C3_Viewer');
assert(csvTask.selectors.includes('ba_domain'));assert(csvTask.selectors.includes('ba_status'));
assert(csvTask.selectors.includes('ba_anomaly_pixel_count'));
assert(!Array.from(csvTask.selectors).some(x=>x.startsWith('c3_')));
assert(/^rp1_ba_viewer_inspection_c3_BA2012_district_transition_zone_/.test(csvTask.description));
assert(/_202401_ext$/.test(csvTask.description));
assert.equal(csvTask.description,csvTask.fileNamePrefix);
assert(!/pilot/i.test(csvTask.description));
assert(buttons.some(x=>x.label==='Create selected unit-month CSV (1)'));
assert(!buttons.some(x=>/pilot/i.test(x.label||'')));
console.log('PASS viewer selected-month CSV uses the 69 renamed selectors, neutral filename and extended output');
ctx.C3.observationEndYear=2025;
ctx.profileSelect.setValue('BA2012');
assert(ctx.yearBox.config.items.includes('2025'),'configured observation year absent from viewer');
ctx.c3Settings=()=>({profile:ctx.c3Profile('BA2012'),level:'district',zone:'transition_zone',district:'Asutifi_North',date:{year:2025,month:1},units:{selected:'one'}});
task=[];ctx.c3Do('csv_month');
assert.equal(task.length,1,ctx.status.getValue());
assert.equal(task[0].selectors.length,70);
assert.equal(task[0].selectors[69],'ba_annual_lc_source_index');
assert.equal(task[0].collection.profile.end,2024,'future viewer changed fixed union');
console.log('PASS configured future year in viewer controls and annual source selector');
