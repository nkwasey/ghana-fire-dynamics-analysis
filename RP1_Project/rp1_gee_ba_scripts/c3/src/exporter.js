// =============================================================================
// RP1 — Monthly Burned-Area CSV Exporter
// Earth Engine Code Editor: ACZ and district monthly extended CSVs
//
// The selected BA2001 or BA2012 fixed union is used for both the accepted
// burned-area numerator and primary denominator.  Each annual task exports
// all 69 analytical, evidence-state, quality and provenance fields.  Export
// year selection never changes the fixed union's period.  The shared c3 core
// provides source admission, native-grid reduction, anomaly withholding and
// accounting rules.  Selected-month exports support focused inspection.
//
// Choose reporting level, zone scope, fixed union and years in Controls; use
// Exports to inspect the task plan and create the requested tasks.  Tasks are
// created but never started by the script.  Optional district QA and boundary
// exception records are operational records, not alternative BA tables.
// =============================================================================

// ========================== 01. EXPORT CONFIGURATION ==========================
var C3X_ZONES=[{id:'coastal_zone',code:'CZ',name:'Coastal Zone'},
  {id:'forest_zone',code:'FZ',name:'Forest Zone'},
  {id:'guinea_savannah',code:'GS',name:'Guinea Savannah'},
  {id:'sudan_savannah',code:'SS',name:'Sudan Savannah'},
  {id:'transition_zone',code:'TZ',name:'Transition Zone'}];
function c3xZone(id) {
  for(var i=0;i<C3X_ZONES.length;i++) if(C3X_ZONES[i].id===id) return C3X_ZONES[i];
  throw new Error('Unrecognised ACZ: '+id);
}
function c3xIdTag(id) {
  var hash=2166136261;
  for(var i=0;i<id.length;i++){var v=hash^id.charCodeAt(i);hash=(v+(v<<1)+(v<<4)+(v<<7)+(v<<8)+(v<<24))|0;}
  return id.replace(/[^A-Za-z0-9_-]/g,'_').slice(0,12)+'_'+('00000000'+(hash>>>0).toString(16)).slice(-8);
}
function c3xFolder(profile) { return profile.id==='BA2001'?'RP1_Project_MODIS_BA_c3_2001':'RP1_Project_MODIS_BA_c3_2012'; }
function c3xDates(year) {var dates=[];for(var m=1;m<=12;m++)dates.push({year:year,month:m});return dates;}
function c3xMonthList(start,end){var dates=[];for(var y=start;y<=end;y++)dates=dates.concat(c3xDates(y));return dates;}
// 80 characters is a conservative project rule for the generated prefix,
// not a published Earth Engine maximum. It excludes the added .csv extension.
function c3xValidateName(name) {
  if(typeof name!=='string'||name.length<1||name.length>80||!/^[A-Za-z0-9_-]+$/.test(name))
    throw new Error('Generated task/CSV prefix violates the project naming rule (1–80 ASCII letters, numbers, hyphens or underscores): '+name);
  return name;
}
function c3xPrefix(spec,zone) {
  var zoneCode=zone==='ALL_ACZ'?'ALL_ACZ':c3xZone(zone).code;
  var prefix='rp1_ba_'+spec.level+'_monthly_c3_'+zoneCode+'_'+spec.profile.id;
  if(spec.district) prefix+='_D_'+c3xIdTag(spec.district);
  return prefix;
}
function c3xNames(spec,zone,year) {
  var p=c3xPrefix(spec,zone);
  var ext=c3xValidateName(p+'_'+year+'_ext');
  if(spec.level==='acz')return {ext:ext};
  return {ext:ext,qa:c3xValidateName(p+'_'+spec.yearStart+'-'+spec.yearEnd+'_qa_by_acz')};
}
function c3xBoundaryName(spec,zone) {
  var p=c3xPrefix(spec,zone);
  if(spec.level==='district') return c3xValidateName(p+'_'+spec.yearStart+'-'+spec.yearEnd+'_boundary');
  var n=p+'_boundary_issue_log';
  if(spec.yearStart!==spec.profile.start||spec.yearEnd!==spec.profile.end)n+='_'+spec.yearStart+'_to_'+spec.yearEnd;
  return c3xValidateName(n);
}
/* Pure plan. ACZ all is one combined table/year; district all is per-zone/year. */
function c3xPlan(spec) {
  var groups=spec.level==='acz'&&spec.scope==='all'?['ALL_ACZ']:spec.zones.slice();
  var out=[],i,y,n;
  for(i=0;i<groups.length;i++){
    for(y=spec.yearStart;y<=spec.yearEnd;y++){
      n=c3xNames(spec,groups[i],y);
      out.push({kind:'ext',zone:groups[i],year:y,name:n.ext});
    }
    if(spec.level==='district'&&spec.includeInventory)out.push({kind:'qa',zone:groups[i],year:null,name:c3xNames(spec,groups[i],spec.yearStart).qa});
  }
  return out;
}
function c3xUnits(level,zones,district) {
  var fc=ee.FeatureCollection([]);
  zones.forEach(function(zone){fc=fc.merge(c3Units(level,zone,district));});
  return fc;
}
/* Validate the full asset BEFORE zone filtering; unassigned units cannot vanish silently.
 * Geometry checks below block zero-area units without dropping them. */
// ========================= 02. BOUNDARY VALIDATION =========================
function c3xBoundaryInventory(level, districtFilter, filterZone) {
  c3xBoundaryIssues=[];c3xBoundaryIssueSettings=null;
  var raw=ee.FeatureCollection(level==='acz'?C3.zoneAsset:C3.districtAsset);
  var ids=level==='acz'?'zone_id':'dist_id',names=level==='acz'?'zone_name':'dist_name';
  var annotated=raw.map(function(f){f=ee.Feature(f);return f.set('c3x_inventory_row',ee.Dictionary({
    id:f.get(ids),name:f.get(names),zone:f.get('zone_id'),code:f.get('zone_code'),zoneName:f.get('zone_name')}));});
  var x=ee.Dictionary({count:raw.size(),rows:annotated.aggregate_array('c3x_inventory_row')}).getInfo();
  if(!x||!x.count)throw new Error('Boundary asset is empty or inaccessible.');
  if(!x.rows||x.rows.length!==x.count)throw new Error('Could not inventory every boundary feature.');
  var seen=Object.create(null),counts={}; C3X_ZONES.forEach(function(z){counts[z.id]=0;});
  // A compact district tag is not globally unique. When filtering one
  // district, reject a colliding tag within its zone using this same asset
  // inventory; this cannot discover earlier tasks or files in other sessions.
  var filterTag=level==='district'&&districtFilter?c3xIdTag(String(districtFilter)):null;
  for(var i=0;i<x.count;i++){
    var row=x.rows[i]||{},id=row.id,name=row.name,z=row.zone,code=row.code,zn=row.zoneName;
    if(id===null||id===undefined||String(id).trim()===''||name===null||name===undefined||String(name).trim()===''||
       zn===null||zn===undefined||String(zn).trim()==='')throw new Error('Blank boundary identity or name at row '+i+'.');
    var key=String(id);if(seen[key])throw new Error('Duplicate unit ID in boundary asset: '+key);seen[key]=true;
    var zone=c3xZone(String(z));if(String(code)!==zone.code)throw new Error('Incorrect zone_code for '+key+': '+code);
    if(filterTag&&zone.id===filterZone&&key!==String(districtFilter)&&c3xIdTag(key)===filterTag)
      throw new Error('District filename tag collision in selected zone between '+districtFilter+' and '+key+'; no data tasks created.');
    counts[zone.id]++;
  }
  if(level==='acz')C3X_ZONES.forEach(function(z){if(counts[z.id]!==1)throw new Error('ACZ asset must contain exactly one feature for '+z.id);});
  print('c3 exporter unfiltered boundary ID/parent inventory (not a geometry equivalence check)',{asset:level==='acz'?C3.zoneAsset:C3.districtAsset,count:x.count,counts_by_zone:counts});
  return {total:x.count,counts:counts};
}
var c3xBoundaryIssues=[],c3xBoundaryIssueSettings=null;
/* Check the same Ghana-clipped geometries the core will reduce. Zero-area units
 * block the batch; they are never silently removed. This is not an equivalence test. */
function c3xGeometryPreflight(units,s) {
  c3xBoundaryIssues=[];c3xBoundaryIssueSettings=null;
  var annotated=units.map(function(f){f=ee.Feature(f);return f.set('c3x_geometry_row',ee.Dictionary({
    id:f.get('unit_id'),zone:f.get(s.level==='district'?'parent_id':'unit_id'),area:f.geometry().area(1)}));});
  var obj=ee.Dictionary({count:units.size(),rows:annotated.aggregate_array('c3x_geometry_row')}).getInfo();
  if(!obj||!obj.count||!obj.rows||obj.rows.length!==obj.count)
    throw new Error('Could not verify every selected Ghana-clipped unit geometry.');
  for(var i=0;i<obj.count;i++){
    var item=obj.rows[i]||{};
    if(typeof item.area!=='number'||!isFinite(item.area))throw new Error('Could not evaluate clipped unit area: '+item.id);
    if(item.area<=0)c3xBoundaryIssues.push({unit_id:item.id,zone_id:item.zone,reason:'ZERO_GHANA_CLIPPED_VECTOR_AREA',area_m2:item.area});
  }
  print('c3 selected-unit Ghana-clipped area preflight (not geometry-equivalence validation)',{count:obj.count,zero_area_count:c3xBoundaryIssues.length});
  if(c3xBoundaryIssues.length){c3xBoundaryIssueSettings=s;print('Blocked unit exceptions, no units dropped',c3xBoundaryIssues);
    throw new Error('Zero Ghana-clipped geometry area in '+c3xBoundaryIssues.length+' selected unit(s). No data tasks created; see Console and optional boundary exception log.');}
}
function c3xAnnualReceipt(receipt,offset) {
  return {lc_indexes:receipt.lc_indexes,annual_lc_indexes:receipt.annual_lc_indexes,ba_indexes:receipt.ba_indexes.slice(offset,offset+12)};
}
// ========================== 03. EXPORTER INTERFACE ==========================
var c3xPanel=ui.Panel({style:{width:'400px',padding:'9px'}});
c3xPanel.add(ui.Label('RP1 c3 | Monthly BA CSV exporter',{fontWeight:'bold',fontSize:'17px'}));
c3xPanel.add(ui.Label('No source checks or export tasks run on startup.',{fontSize:'11px',color:'#8b4d00'}));
var c3xStatus=ui.Label('Ready. Choose settings and inspect the export plan.',{whiteSpace:'normal',color:'#245672'});c3xPanel.add(c3xStatus);
var c3xControls=ui.Panel(),c3xLayers=ui.Panel(),c3xExports=ui.Panel(),c3xAbout=ui.Panel();
function c3xTab(t){c3xControls.style().set('shown',t==='controls');c3xLayers.style().set('shown',t==='layers');c3xExports.style().set('shown',t==='exports');c3xAbout.style().set('shown',t==='about');}
var c3xNav=ui.Panel({layout:ui.Panel.Layout.flow('horizontal')});
['controls','layers','exports','about'].forEach(function(t){c3xNav.add(ui.Button({label:t.charAt(0).toUpperCase()+t.slice(1),onClick:function(){c3xTab(t);}}));});
c3xPanel.add(c3xNav);c3xPanel.add(c3xControls);c3xPanel.add(c3xLayers);c3xPanel.add(c3xExports);c3xPanel.add(c3xAbout);
var c3xProfile=ui.Select({items:['BA2001','BA2012'],value:'BA2001'});
var c3xLevel=ui.Select({items:['acz','district'],value:'acz'});
var c3xScope=ui.Select({items:['Selected ACZ','All ACZs'],value:'Selected ACZ'});
var c3xZoneSelect=ui.Select({items:C3X_ZONES.map(function(z){return z.id;}),value:'forest_zone'});
var c3xDistrict=ui.Textbox({placeholder:'Optional exact dist_id; one ACZ only',value:''});
var c3xPreviewYear=ui.Textbox({value:String(C3.observationEndYear)}),c3xPreviewMonth=ui.Textbox({value:'1'});
var c3xRange=ui.Select({items:['Selected year','Year range','Full domain period'],value:'Selected year'});
var c3xStart=ui.Textbox({value:String(C3.observationEndYear)}),c3xEnd=ui.Textbox({value:String(C3.observationEndYear)});
var c3xInventory=ui.Checkbox({label:'Also create district unit-inventory QA receipt(s)',value:false});
function c3xControl(label,widget){c3xControls.add(ui.Label(label,{fontWeight:'bold',margin:'5px 0 1px 0'}));c3xControls.add(widget);}
c3xControl('Fixed union domain',c3xProfile);c3xControl('Reporting level',c3xLevel);
c3xControl('Export geography',c3xScope);c3xControl('Selected ACZ (also used for preview)',c3xZoneSelect);
c3xControl('District filter: export and preview (blank = all districts)',c3xDistrict);
c3xControl('Preview year',c3xPreviewYear);c3xControl('Preview month (1–12)',c3xPreviewMonth);
c3xControl('Export year mode',c3xRange);c3xControl('First year for range',c3xStart);c3xControl('Last year for range',c3xEnd);
c3xControls.add(c3xInventory);
function c3xSettings() {
  var profile=c3Profile(c3xProfile.getValue()),level=c3xLevel.getValue();
  var scope=c3xScope.getValue()==='All ACZs'?'all':'one',zone=c3xZoneSelect.getValue();
  var district=(c3xDistrict.getValue()||'').trim();
  if(level==='acz'&&district)throw new Error('Clear the district filter for ACZ exports.');
  if(scope==='all'&&district)throw new Error('A district filter requires Selected ACZ.');
  var date=c3ParseDate(profile,c3xPreviewYear.getValue(),c3xPreviewMonth.getValue());
  var mode=c3xRange.getValue(),a,b;
  var window=c3ObservationWindow(profile);
  if(mode==='Full domain period'){a=window.start;b=window.end;}
  else if(mode==='Selected year'){a=date.year;b=date.year;}
  else {a=Number(c3xStart.getValue());b=Number(c3xEnd.getValue());
    if(!isFinite(a)||!isFinite(b)||Math.floor(a)!==a||Math.floor(b)!==b||a<window.start||b>window.end||a>b)
      throw new Error('Year range must be ordered whole years inside configured observation coverage.');}
  return {profile:profile,level:level,scope:scope,zones:scope==='all'?C3X_ZONES.map(function(z){return z.id;}):[zone],
    previewZone:zone,district:district,date:date,yearStart:a,yearEnd:b,includeInventory:c3xInventory.getValue()};
}
var c3xPlanText=ui.Label('No plan inspected.',{whiteSpace:'normal',fontSize:'11px'});c3xExports.add(c3xPlanText);
function c3xDescribe(s,plan){
  return 'For full-period plans, source preflight checks every month and may be slow; use bounded year batches when needed. Prior Drive/Tasks names from other sessions cannot be detected.\nDomain: '+s.profile.id+' ('+s.profile.start+'–'+s.profile.end+' union)\nLevel: '+s.level+'; zones: '+s.zones.join(', ')+
    '\nDistrict filter: '+(s.district||'all selected-zone districts')+'\nExport years: '+s.yearStart+'–'+s.yearEnd+
    '\nFolder: '+c3xFolder(s.profile)+'\n'+plan.length+' tasks planned; none created by plan.\n'+
    plan.slice(0,15).map(function(x){return x.name+'.csv';}).join('\n')+
    (plan.length>15?'\n... '+(plan.length-15)+' more; full name list printed to Console.':'');
}
var c3xInspectedSignature='';
function c3xSignature(s,p){return JSON.stringify({folder:c3xFolder(s.profile),tasks:p});}
function c3xInspectPlan(){try{var s=c3xSettings(),p=c3xPlan(s);c3xInspectedSignature=c3xSignature(s,p);c3xPlanText.setValue(c3xDescribe(s,p));print('c3 CSV export plan (not tasks)',p);c3xStatus.setValue('Plan inspected. Source and boundary checks occur before task creation.');}catch(e){c3xFail(e);}}
function c3xFail(e){var msg=String((e&&e.message)||e);c3xStatus.setValue('BLOCKED: '+msg);print('c3 exporter blocked: '+msg);}
// ======================== 04. SELECTED-MONTH PREVIEW ========================
function c3xPreview(){try{
  var s=c3xSettings(),u=c3xUnits(s.level,[s.previewZone],s.district);
  c3xStatus.setValue('Checking identities and source metadata for selected-month preview...');
  c3xBoundaryInventory(s.level,s.district,s.previewZone);c3xGeometryPreflight(u,s);var receipt=c3SourcePreflight(s.profile,[s.date],u,s.level);
  var dom=c3Domain(s.profile,receipt),ev=c3Evidence(c3BaImage(receipt.ba_indexes[0][0]));
  Map.layers().reset();Map.addLayer(ee.Image().byte().paint(u,1,2),{palette:['111111']},'Selected reporting units',true);
  Map.addLayer(dom.eligible.selfMask().clip(u.geometry()),{palette:['e6c442']},'Fixed union eligible',false);
  Map.addLayer(dom.unresolved.selfMask().clip(u.geometry()),{palette:['a354d5']},'Unresolved union',true);
  Map.addLayer(dom.eligible.and(ev.accepted).selfMask().clip(u.geometry()),{palette:['d7191c']},'Accepted pixel evidence; inspect unit status',true);
  Map.addLayer(dom.eligible.and(ev.anomaly).selfMask().clip(u.geometry()),{palette:['00d0d0']},'Anomalous source pixels',true);
  Map.centerObject(u,s.level==='district'?9:7);
  print('c3 exporter selected-month preview; reporting status controls usability',c3Rows(u,s.profile,[s.date],receipt));
  c3xStatus.setValue('Preview source admitted. Inspect Console rows and status; pixel evidence is not a unit admission.');
}catch(e){c3xFail(e);}}
// ========================== 05. EXPORT TASK CREATION ==========================
var c3xCreatedPrefixes=Object.create(null);
function c3xCheckUnused(names){
  var seen=Object.create(null); names.forEach(function(n){
    if(seen[n]||c3xCreatedPrefixes[n])throw new Error('Task prefix already created in this session: '+n+'; inspect Tasks before retrying.');
    seen[n]=true;
  });
}
function c3xSelectedMonth(){try{
  var s=c3xSettings(),u=c3xUnits(s.level,[s.previewZone],s.district);
  c3xStatus.setValue('Checking selected-month inputs...');c3xBoundaryInventory(s.level,s.district,s.previewZone);c3xGeometryPreflight(u,s);
  var receipt=c3SourcePreflight(s.profile,[s.date],u,s.level);
  var name=c3xValidateName('rp1_ba_inspection_c3_'+s.level+'_'+c3xZone(s.previewZone).code+'_'+s.profile.id+'_'+s.date.year+c3Pad(s.date.month)+(s.district?'_D_'+c3xIdTag(s.district):'')+'_ext');
  c3xCheckUnused([c3xFolder(s.profile)+'/'+name]);
  Export.table.toDrive({collection:c3Rows(u,s.profile,[s.date],receipt),description:name,folder:c3xFolder(s.profile),fileNamePrefix:name,fileFormat:'CSV',selectors:c3Selectors(s.profile,s.date.year)});
  c3xCreatedPrefixes[c3xFolder(s.profile)+'/'+name]=true;
  c3xStatus.setValue('One selected-month CSV task created; run it manually in Tasks.');
}catch(e){c3xFail(e);}}
var c3xLastPlan='';
function c3xQueue(){
  var created=[],s,plan;
  try {
    s=c3xSettings();plan=c3xPlan(s);var signature=c3xSignature(s,plan);
    if(signature!==c3xInspectedSignature)throw new Error('Inspect the current export plan first; settings changed or plan has not been inspected.');
    if(signature===c3xLastPlan)throw new Error('This exact plan was already created in this session; change selection or reload after reviewing Tasks.');
    c3xCheckUnused(plan.map(function(t){return c3xFolder(s.profile)+'/'+t.name;}));
    if(plan.length>260)throw new Error('Plan exceeds the 260-task session cap; use a shorter year range.');
    c3xStatus.setValue('Checking full unfiltered boundary inventory and all requested source months. Full-period preflight may take time...');
    var inv=c3xBoundaryInventory(s.level,s.district,s.previewZone),units=c3xUnits(s.level,s.zones,s.district),dates=c3xMonthList(s.yearStart,s.yearEnd);
    c3xGeometryPreflight(units,s);
    var receipt=c3SourcePreflight(s.profile,dates,units,s.level);
    // Ensure every selected zone has units, before any task is created.
    for(var zi=0;zi<s.zones.length;zi++){
      if(!inv.counts[s.zones[zi]])throw new Error('Selected zone has no units: '+s.zones[zi]);
    }
    // Preflight above certifies all selected units and all selected months as one scope.
    var groups=s.level==='acz'&&s.scope==='all'?['ALL_ACZ']:s.zones;
    for(var i=0;i<groups.length;i++){
      var z=groups[i],groupZones=z==='ALL_ACZ'?s.zones:[z],groupUnits=c3xUnits(s.level,groupZones,s.district);
      for(var y=s.yearStart;y<=s.yearEnd;y++){
        var yr=c3xDates(y),yrReceipt=c3xAnnualReceipt(receipt,(y-s.yearStart)*12),rows=c3Rows(groupUnits,s.profile,yr,yrReceipt),names=c3xNames(s,z,y);
        Export.table.toDrive({collection:rows,description:names.ext,folder:c3xFolder(s.profile),fileNamePrefix:names.ext,fileFormat:'CSV',selectors:c3Selectors(s.profile,y)});created.push(names.ext);c3xCreatedPrefixes[c3xFolder(s.profile)+'/'+names.ext]=true;
      }
      if(s.level==='district'&&s.includeInventory){
        var qname=c3xNames(s,z,s.yearStart).qa;
        var q=ee.FeatureCollection([ee.Feature(null,{schema_version:'c3_unit_inventory_v1',domain:s.profile.id,zone_id:z,zone_code:c3xZone(z).code,
          district_filter:s.district||'',selected_unit_count:groupUnits.size(),raw_asset_zone_count:inv.counts[z],
          identity_preflight:'PASSED',geometry_preflight:'CLIPPED_NONZERO_AREA_ONLY',source_preflight:'PASSED',
          start_year:s.yearStart,end_year:s.yearEnd,boundary_asset:C3.districtAsset,ghana_asset:C3.ghanaAsset})]);
        Export.table.toDrive({collection:q,description:qname,folder:c3xFolder(s.profile),fileNamePrefix:qname,fileFormat:'CSV',
          selectors:['schema_version','domain','zone_id','zone_code','district_filter','selected_unit_count','raw_asset_zone_count','identity_preflight','geometry_preflight','source_preflight','start_year','end_year','boundary_asset','ghana_asset']});created.push(qname);c3xCreatedPrefixes[c3xFolder(s.profile)+'/'+qname]=true;
      }
    }
    c3xLastPlan=signature;print('c3 tasks created; manual Run required',created);
    c3xStatus.setValue(created.length+' tasks created. They have NOT been submitted; review and run them manually.');
  }catch(e){
    if(created.length){print('PARTIAL TASK CREATION; inspect and remove duplicates manually before retry',created);c3xStatus.setValue('PARTIAL: '+created.length+' tasks created before error. Review Tasks before retrying. '+String((e&&e.message)||e));}
    else c3xFail(e);
  }
}
function c3xExportBoundaryIssues(){
  var created=[];
  try {
    if(!c3xBoundaryIssueSettings||!c3xBoundaryIssues.length)throw new Error('No recorded zero-area boundary issues from the latest preflight.');
    var s=c3xBoundaryIssueSettings,zones=[];
    c3xBoundaryIssues.forEach(function(issue){if(zones.indexOf(String(issue.zone_id))<0)zones.push(String(issue.zone_id));});
    var names=zones.map(function(z){return c3xBoundaryName(s,z);});
    c3xCheckUnused(names.map(function(n){return c3xFolder(s.profile)+'/'+n;}));
    zones.forEach(function(z,i){var features=c3xBoundaryIssues.filter(function(x){return String(x.zone_id)===z;}).map(function(x){
      return ee.Feature(null,{domain:s.profile.id,level:s.level,unit_id:x.unit_id,zone_id:x.zone_id,
        reason:x.reason,clipped_area_m2:x.area_m2,disposition:'BLOCKED_NOT_DROPPED',boundary_asset:s.level==='acz'?C3.zoneAsset:C3.districtAsset,ghana_asset:C3.ghanaAsset});});
      var n=names[i];Export.table.toDrive({collection:ee.FeatureCollection(features),description:n,folder:c3xFolder(s.profile),fileNamePrefix:n,fileFormat:'CSV',
        selectors:['domain','level','unit_id','zone_id','reason','clipped_area_m2','disposition','boundary_asset','ghana_asset']});
      created.push(n);c3xCreatedPrefixes[c3xFolder(s.profile)+'/'+n]=true;
    });
    print('Boundary exception log tasks created; no units were dropped',created);
    c3xStatus.setValue(created.length+' exception log task(s) created; data exports remain blocked until resolved.');
  } catch(e){if(created.length){print('PARTIAL exception log tasks created',created);c3xStatus.setValue('PARTIAL: '+created.length+' log tasks created. Review Tasks: '+String((e&&e.message)||e));}else c3xFail(e);}
}
// ======================= 06. CONTROLS AND INITIALIZATION =======================
c3xControls.add(ui.Button({label:'Inspect selected-month preview',onClick:c3xPreview,style:{stretch:'horizontal'}}));
c3xLayers.add(ui.Label('Preview creates boundary, fixed-union, unresolved, accepted evidence and anomaly layers. Use the map Layers control for visibility.',{whiteSpace:'normal'}));
c3xLayers.add(ui.Button({label:'Refresh selected-month preview',onClick:c3xPreview,style:{stretch:'horizontal'}}));
c3xExports.add(ui.Button({label:'Inspect export plan (no tasks)',onClick:c3xInspectPlan,style:{stretch:'horizontal'}}));
c3xExports.add(ui.Button({label:'Create selected-month CSV task',onClick:c3xSelectedMonth,style:{stretch:'horizontal'}}));
c3xExports.add(ui.Button({label:'Create planned annual CSV tasks',onClick:c3xQueue,style:{stretch:'horizontal'}}));
c3xExports.add(ui.Button({label:'Create boundary exception log tasks (if blocked)',onClick:c3xExportBoundaryIssues,style:{stretch:'horizontal'}}));
c3xExports.add(ui.Label('Configure domain, geography and year mode in Controls. All ACZ tables are combined; district exports are separate per ACZ. Tasks are never started automatically. This session blocks repeated prefixes, but cannot detect previous Drive or task names. Full-period source preflight may be slow; bounded year batches are recommended.',{whiteSpace:'normal',fontSize:'11px'}));
c3xAbout.add(ui.Label('Fixed period unions, QA, evidence states, anomaly withholding, native grid, source admission and denominators are shared by both applications. A smaller export range does not change the union period.',{whiteSpace:'normal'}));
c3xAbout.add(ui.Label('QA checks identity and nonzero Ghana-clipped vector area; it does not establish geometry equivalence. Invalid IDs, assignments or zero-area geometries block data tasks; units are not silently dropped. A nonempty unit with no pixel centres remains NO_PIXEL_CENTRES.',{whiteSpace:'normal'}));
c3xAbout.add(ui.Label('Each analytical CSV contains the complete 69-field extended record. Blank withheld values are not zeros. Viewer/exporter agreement is not physical-fire accuracy validation.',{whiteSpace:'normal'}));
c3xTab('controls');ui.root.insert(0,c3xPanel);Map.setOptions('SATELLITE');
print('RP1 c3 consolidated exporter initialised. No checks or tasks run automatically.');
