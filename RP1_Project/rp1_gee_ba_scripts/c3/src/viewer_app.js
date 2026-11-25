// =============================================================================
// VIEWER 01 — CONTROLS, STATE AND REPORTING SCOPE
// =============================================================================
// Shared scientific functions and configuration are generated above this section.
var appTitle='RP1 c3 | Ghana MODIS viewer';
var panel=ui.Panel({style:{width:'430px',padding:'8px'}});
panel.add(ui.Label(appTitle,{fontWeight:'bold',fontSize:'17px'}));
panel.add(ui.Label('Pixel layers are evidence; consult reporting-unit status for results.',{color:'#8b4d00',fontSize:'11px',whiteSpace:'normal'}));
var status=ui.Label('Ready. Select settings and inspect a month.',{whiteSpace:'normal',color:'#245672'});
panel.add(status);
var controlsPanel=ui.Panel(),layersPanel=ui.Panel(),exportsPanel=ui.Panel(),aboutPanel=ui.Panel();
var nav=ui.Panel({layout:ui.Panel.Layout.flow('horizontal')});
function c3Tab(which){
  controlsPanel.style().set('shown',which==='controls'); layersPanel.style().set('shown',which==='layers');
  exportsPanel.style().set('shown',which==='exports'); aboutPanel.style().set('shown',which==='about');
}
['controls','layers','exports','about'].forEach(function(name){nav.add(ui.Button({label:name.charAt(0).toUpperCase()+name.slice(1),onClick:function(){c3Tab(name);}}));});
panel.add(nav);panel.add(controlsPanel);panel.add(layersPanel);panel.add(exportsPanel);panel.add(aboutPanel);
var profileSelect=ui.Select({items:['BA2001','BA2012'],value:'BA2001'});
var levelSelect=ui.Select({items:['ghana','acz','district'],value:'ghana'});
var zoneSelect=ui.Select({items:['coastal_zone','forest_zone','guinea_savannah','sudan_savannah','transition_zone'],value:'forest_zone'});
var districtBox=ui.Textbox({placeholder:'Exact dist_id (required for district)',value:''});
var yearOptions=[];for(var yi=C3.observationStartYear;yi<=C3.observationEndYear;yi++)yearOptions.push(String(yi));
var monthOptions=[];for(var mi=1;mi<=12;mi++)monthOptions.push(String(mi));
var yearBox=ui.Select({items:yearOptions,value:String(C3.observationEndYear)}),monthBox=ui.Select({items:monthOptions,value:'1'});
var districtChoices=ui.Select({items:[],placeholder:'Load district list for this ACZ',onChange:function(label){
  if(label&&districtLookup[label])districtBox.setValue(districtLookup[label]);
}});
var districtLookup={},districtLoadGeneration=0;
function c3FocusWidgets(){
  var mode=levelSelect.getValue();zoneSelect.setDisabled(mode==='ghana');
  districtBox.setDisabled(mode!=='district');districtChoices.setDisabled(mode!=='district'||Object.keys(districtLookup).length===0);
}
function c3LoadDistricts(){
  var zone=zoneSelect.getValue(),generation=++districtLoadGeneration;
  status.setValue('Loading district names and IDs for '+zone+'...');
  var units=c3Units('district',zone,'');
  ee.Dictionary({ids:units.aggregate_array('unit_id'),names:units.aggregate_array('unit_name'),count:units.size()}).evaluate(function(obj,err){
    if(generation!==districtLoadGeneration||zone!==zoneSelect.getValue())return;
    districtLookup={};districtChoices.items().reset([]);districtChoices.setDisabled(true);
    if(err||!obj||!obj.count||!obj.ids||!obj.names||obj.ids.length!==obj.count||obj.names.length!==obj.count){
      status.setValue('District list unavailable or incomplete. Enter exact dist_id manually; inspect the asset.');return;
    }
    var labels=[];
    for(var i=0;i<obj.ids.length;i++){
      var id=String(obj.ids[i]||''),name=String(obj.names[i]||'');
      if(!id||!name){status.setValue('District list has an empty ID/name. Enter an exact dist_id manually.');return;}
      var label=name+' | '+id;if(districtLookup[label]){status.setValue('Duplicate district label/ID. Check the asset.');return;}
      districtLookup[label]=id;labels.push(label);
    }
    labels.sort();districtChoices.items().reset(labels);c3FocusWidgets();
    status.setValue('Loaded '+labels.length+' district names and IDs.');
  });
}
levelSelect.onChange(c3FocusWidgets);
zoneSelect.onChange(function(){districtLoadGeneration++;districtLookup={};districtChoices.items().reset([]);districtBox.setValue('');c3FocusWidgets();});
profileSelect.onChange(function(value){
  var window=c3ObservationWindow(c3Profile(value)),start=window.start,opts=[];
  for(var y=start;y<=window.end;y++)opts.push(String(y));
  var current=Number(yearBox.getValue());yearBox.items().reset(opts);
  yearBox.setValue(String(current>=start&&current<=window.end?current:start));
});
function addControl(label,widget){controlsPanel.add(ui.Label(label,{fontWeight:'bold',margin:'4px 0 1px 0'}));controlsPanel.add(widget);}
addControl('Fixed union domain: BA2001 (2001–2024) or BA2012 (2012–2024)',profileSelect);
addControl('Map / raster scope',levelSelect);addControl('Agro-climatic zone for ACZ or district focus',zoneSelect);
addControl('District ID for district focus',districtBox);addControl('District name and ID',districtChoices);
controlsPanel.add(ui.Button({label:'Load district names for selected ACZ',onClick:c3LoadDistricts,style:{stretch:'horizontal'}}));
addControl('Year',yearBox);addControl('Month, 1–12',monthBox);c3FocusWidgets();
controlsPanel.add(ui.Label('Ghana is the initial visual AOI. The union period is independent of the selected export year.',{fontSize:'11px',whiteSpace:'normal'}));
function c3Settings(){
  var profile=c3Profile(profileSelect.getValue()),date=c3ParseDate(profile,yearBox.getValue(),monthBox.getValue());
  var level=levelSelect.getValue(),zone=zoneSelect.getValue(),district=(districtBox.getValue()||'').trim(), units;
  if(level==='ghana') {
    /* A named feature serves only as a source-preflight footprint. No national CSV row is calculated. */
    units=ee.FeatureCollection([ee.Feature(ee.FeatureCollection(C3.ghanaAsset).geometry(),{unit_id:'GHA',unit_name:'Ghana'})]);
  } else {
    if(level==='district'&&!district) throw new Error('Enter an exact dist_id for district focus.');
    units=c3Units(level,zone,district);
  }
  return {profile:profile,date:date,level:level,zone:zone,district:district,units:units};
}
function c3DatesForYear(year){var out=[];for(var m=1;m<=12;m++)out.push({year:year,month:m});return out;}
function c3ScopeTag(s){
  if(s.level==='ghana')return 'GHA';
  var tag=s.zone;
  if(s.level==='district'){
    var id=s.district,hash=2166136261;
    for(var i=0;i<id.length;i++){var v=hash^id.charCodeAt(i);hash=(v+(v<<1)+(v<<4)+(v<<7)+(v<<8)+(v<<24))|0;}
    tag+='_'+id.replace(/[^A-Za-z0-9_-]/g,'_').slice(0,24)+'_'+(hash>>>0).toString(16);
  }
  return tag;
}
// =============================================================================
// VIEWER 02 — MAP LAYERS AND VISIBILITY
// =============================================================================
var previewLayers={},previewReady=false;
var c3CreatedRasterPrefixes={};
function c3WarnDuplicate(name){if(c3CreatedRasterPrefixes[name])print('WARNING: this session already created a task with prefix',name);}
function c3RememberRaster(name){c3CreatedRasterPrefixes[name]=true;}
var boundaryGroup=ui.Panel(),domainGroup=ui.Panel(),evidenceGroup=ui.Panel(),reasonGroup=ui.Panel();
var groupPanels={Boundaries:boundaryGroup,Domain:domainGroup,Evidence:evidenceGroup,Reasons:reasonGroup};
var layerGroup=ui.Select({items:['Boundaries','Domain','Evidence','Reasons'],value:'Boundaries',onChange:function(v){
  Object.keys(groupPanels).forEach(function(k){groupPanels[k].style().set('shown',k===v);});
}});
layersPanel.add(ui.Label('Layer group',{fontWeight:'bold'}));layersPanel.add(layerGroup);
layersPanel.add(boundaryGroup);layersPanel.add(domainGroup);layersPanel.add(evidenceGroup);layersPanel.add(reasonGroup);
Object.keys(groupPanels).forEach(function(k){groupPanels[k].style().set('shown',k==='Boundaries');});
function viewerToggle(key,label,initial){
  var target=(key==='ghana'||key==='acz'||key==='districts'||key==='selected')?boundaryGroup:
    (key==='lc'||key==='annual'||key==='union'||key==='excluded'||key==='unresolved')?domainGroup:
    (key==='short'||key==='special'||key==='anomaly')?reasonGroup:evidenceGroup;
  target.add(ui.Checkbox({label:label,value:initial,onChange:function(value){
    show[key]=value;if(previewReady&&previewLayers[key])previewLayers[key].setShown(value);
  }}));
  return initial;
}
var show={
  ghana:viewerToggle('ghana','Ghana boundary',true),
  acz:viewerToggle('acz','ACZ boundaries',false),
  districts:viewerToggle('districts','District boundaries',false),
  selected:viewerToggle('selected','Selected focus boundary',true),
  lc:viewerToggle('lc','Selected-year IGBP land cover (context)',false),
  annual:viewerToggle('annual','Selected-year eligible area',false),
  union:viewerToggle('union','Selected period fixed union',false),
  excluded:viewerToggle('excluded','Definitely excluded from union',false),
  unresolved:viewerToggle('unresolved','Unresolved union membership',true),
  accepted:viewerToggle('accepted','Accepted positive pixel evidence',true),
  raw:viewerToggle('raw','Raw positive BurnDate (context)',false),
  zero:viewerToggle('zero','Explicit qualifying zero evidence',false),
  unsupported:viewerToggle('unsupported','Unsupported evidence',false),
  bmissing:viewerToggle('bmissing','BurnDate masked with QA present',false),
  qmissing:viewerToggle('qmissing','QA unavailable',false),
  anomaly:viewerToggle('anomaly','Source-pixel anomaly in known union',true),
  short:viewerToggle('short','Shortened mapping reason',false),
  special:viewerToggle('special','Special-condition reason',false)
};
function c3AddLayer(key,obj,vis,name){
  Map.addLayer(obj,vis,name,show[key]);
  previewLayers[key]=Map.layers().get(Map.layers().length()-1);
}
function c3ShowMap(s,domain,e){
  var geom=s.units.geometry(),u=domain.eligible;Map.layers().reset();previewLayers={};
  c3AddLayer('lc',domain.annual[s.date.year].lc.clip(geom),{min:1,max:17,palette:['05450a','086a10','54a708','78d203','009900','c6b044','dcd159','dade48','fbff13','b6ff05','27ff87','c24f44','a5a5a5','ff6d4c','69fff8','f9ffa4','1c0dff']},'Annual IGBP (context)');
  c3AddLayer('annual',domain.annual[s.date.year].eligible.selfMask().clip(geom),{palette:['1a9850']},'Selected-year eligible land');
  c3AddLayer('union',u.selfMask().clip(geom),{palette:['ffd92f']},'Fixed union eligible');
  c3AddLayer('excluded',domain.excluded.selfMask().clip(geom),{palette:['909090']},'Definitely outside union');
  c3AddLayer('unresolved',domain.unresolved.selfMask().clip(geom),{palette:['d02fc0']},'Unresolved union');
  c3AddLayer('raw',e.raw.updateMask(e.raw.gt(0)).clip(geom),{min:1,max:366,palette:['ffd2a6','b45900']},'Raw BurnDate positive — context');
  c3AddLayer('zero',u.and(e.explicit_zero).selfMask().clip(geom),{palette:['79c879']},'Evidence: qualifying zero');
  c3AddLayer('unsupported',u.and(e.unsupported).selfMask().clip(geom),{palette:['886633']},'Evidence: unsupported');
  c3AddLayer('bmissing',u.and(e.burndate_missing).selfMask().clip(geom),{palette:['7138c7']},'Evidence: BurnDate masked');
  c3AddLayer('qmissing',u.and(e.qa_missing).selfMask().clip(geom),{palette:['219ebc']},'Evidence: QA unavailable');
  c3AddLayer('short',u.and(e.flag_shortened).selfMask().clip(geom),{palette:['ff9500']},'Reason: shortened mapping');
  c3AddLayer('special',u.and(e.flag_special).selfMask().clip(geom),{palette:['ffde80']},'Reason: special condition');
  c3AddLayer('accepted',u.and(e.accepted).selfMask().clip(geom),{palette:['d7191c']},'Accepted pixel evidence — consult unit status');
  c3AddLayer('anomaly',u.and(e.anomaly).selfMask().clip(geom),{palette:['00ffff']},'Anomalous positive — consult unit status');
  c3AddLayer('ghana',ee.Image().byte().paint(ee.FeatureCollection(C3.ghanaAsset),1,2),{palette:['ffffff']},'Ghana boundary');
  c3AddLayer('acz',ee.Image().byte().paint(ee.FeatureCollection(C3.zoneAsset),1,1).clip(geom),{palette:['111111']},'ACZ boundaries');
  c3AddLayer('districts',ee.Image().byte().paint(ee.FeatureCollection(C3.districtAsset),1,1).clip(geom),{palette:['888888']},'District boundaries');
  c3AddLayer('selected',ee.Image().byte().paint(s.units,1,2),{palette:['00ff00']},'Selected scope');
  previewReady=true;Map.centerObject(s.units,s.level==='district'?9:7);
}
// =============================================================================
// VIEWER 03 — BURNED-AREA RASTER EXPORTS
// =============================================================================
function c3State(domain,e){
  var u=domain.eligible;
  return ee.Image.constant(0).where(domain.unresolved,1)
    .where(u.and(e.qa_missing),2).where(u.and(e.burndate_missing),3)
    .where(u.and(e.unsupported),4).where(u.and(e.explicit_zero),5)
    .where(u.and(e.accepted),6).rename('c3_state');
}
function c3QueueBa(s,domain,date,sourceIndex){
  var e=c3Evidence(c3BaImage(sourceIndex)),geom=s.units.geometry(),u=domain.eligible;
  var raster=ee.Image.cat([
    u.rename('c3_union_eligible'),domain.unresolved.rename('c3_union_unresolved'),
    c3State(domain,e),u.and(e.accepted).rename('c3_accepted_pixel_evidence'),
    u.and(e.anomaly).rename('c3_source_pixel_anomaly'),
    u.and(e.accepted).and(e.flag_shortened.not()).rename('c3_full_period_only'),
    u.and(e.flag_shortened).rename('c3_reason_shortened'),
    u.and(e.flag_qa_missing).rename('c3_reason_qa_missing'),
    u.and(e.flag_burndate_masked).rename('c3_reason_burndate_masked'),
    u.and(e.flag_qa_nonland).rename('c3_reason_qa_nonland'),
    u.and(e.flag_qa_invalid).rename('c3_reason_qa_invalid'),
    u.and(e.flag_special).rename('c3_reason_special'),
    u.and(e.flag_positive_special).rename('c3_reason_positive_special'),
    u.and(e.flag_unexpected_burndate).rename('c3_reason_unexpected_burndate'),
    e.raw.rename('raw_BurnDate')
  ]).toFloat().clip(geom).unmask(-9999,false);
  var name='MCD64A1_061_Burn_c3_'+s.profile.id+'_'+c3ScopeTag(s)+'_'+date.year+'_'+c3Pad(date.month);
  c3WarnDuplicate(name);
  Export.image.toDrive({image:raster,description:name,folder:C3.driveFolder,fileNamePrefix:name,
    region:geom,crs:C3.crs,crsTransform:C3.transform,maxPixels:C3.maxPixels,
    fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
  c3RememberRaster(name);return name;
}
function c3QueueDomain(s,domain){
  var geom=s.units.geometry(),ann=domain.annual[s.date.year];
  var img=ee.Image.cat([domain.eligible.rename('c3_union_eligible'),
    domain.excluded.rename('c3_union_excluded'),domain.unresolved.rename('c3_union_unresolved'),
    ann.eligible.rename('c3_annual_eligible'),ann.unknown.rename('c3_annual_unknown')]).toFloat().clip(geom).unmask(-9999,false);
  var name='MCD12Q1_061_Union_c3_'+s.profile.id+'_'+c3ScopeTag(s)+'_'+s.date.year;
  c3WarnDuplicate(name);
  Export.image.toDrive({image:img,description:name,folder:C3.driveFolder,fileNamePrefix:name,
    region:geom,crs:C3.crs,crsTransform:C3.transform,maxPixels:C3.maxPixels,
    fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
  c3RememberRaster(name);return name;
}
// =============================================================================
// VIEWER 04 — SOURCE CHECKS, MAP ACTIONS AND SELECTED-MONTH CSV
// =============================================================================
function c3Do(action){
  var created=[];
  try{
    var s=c3Settings();
    if(action==='csv_month'&&s.level==='ghana')throw new Error('National reporting rows are not defined; select an ACZ or district for a preview CSV.');
    var yearly=action==='ba_year'||action==='ba_stack';
    var dates=yearly?c3DatesForYear(s.date.year):[s.date];
    status.setValue('Checking source inventory, identities and native-grid metadata...');
    var receipt=c3SourcePreflight(s.profile,dates,s.units,s.level);
    if(action==='inspect'){
      var domain=c3Domain(s.profile,receipt),ev=c3Evidence(c3BaImage(receipt.ba_indexes[0][0]));
      c3ShowMap(s,domain,ev);
      if(s.level!=='ghana')print('Selected c3 unit-month result — consult status',c3Rows(s.units,s.profile,[s.date],receipt));
      else print('Ghana visual scope only: no national reporting row. Select an ACZ or district to inspect a reporting row.');
      status.setValue('Source preflight admitted. Inspect evidence; pixel layers do not certify unit-month results.');
    } else if(action==='ba_month'||action==='ba_year'){
      var dom=c3Domain(s.profile,receipt);
      for(var i=0;i<dates.length;i++)created.push(c3QueueBa(s,dom,dates[i],receipt.ba_indexes[i][0]));
      status.setValue(dates.length+' BA raster task(s) created; inspect and run intended tasks manually.');
    } else if(action==='domain'){
      c3QueueDomain(s,c3Domain(s.profile,receipt));
      status.setValue('Union / annual eligibility raster task created; run manually.');
    } else if(action==='ba_stack'){
      var stackDomain=c3Domain(s.profile,receipt);Map.layers().reset();previewReady=false;
      Map.addLayer(ee.Image().byte().paint(s.units,1,2),{palette:['151515']},'Selected scope',true);
      for(var j=0;j<dates.length;j++){
        var d=dates[j],e=c3Evidence(c3BaImage(receipt.ba_indexes[j][0]));
        Map.addLayer(stackDomain.eligible.and(e.accepted).selfMask().clip(s.units.geometry()),
          {palette:['d7191c']},'Accepted pixel evidence '+d.year+'-'+c3Pad(d.month),j===s.date.month-1);
      }
      Map.centerObject(s.units,s.level==='district'?9:7);
      status.setValue('12 diagnostic monthly layers added. Selected month shown. These do not certify reporting rows.');
    } else if(action==='csv_month'){
      if(s.level==='ghana')throw new Error('National reporting rows are not defined; select an ACZ or district for a preview CSV.');
      var name='rp1_ba_viewer_inspection_c3_'+s.profile.id+'_'+s.level+'_'+c3ScopeTag(s)+'_'+s.date.year+c3Pad(s.date.month)+'_ext';
      Export.table.toDrive({collection:c3Rows(s.units,s.profile,[s.date],receipt),description:name,folder:C3.driveFolder,
        fileNamePrefix:name,fileFormat:'CSV',selectors:c3Selectors(s.profile,s.date.year)});
      status.setValue('One diagnostic preview CSV task created; run manually.');
    }
  }catch(e){var msg=String((e&&e.message)||e);status.setValue((created.length?'PARTIAL: '+created.length+' task(s) created before error. ':'BLOCKED: ')+msg);print('Viewer action blocked: '+msg,'action='+action,'created_prefixes',created);}
}
// =============================================================================
// VIEWER 05 — CONTROLS, EXPORT BUTTONS AND ABOUT PANEL
// =============================================================================
controlsPanel.add(ui.Button({label:'Inspect selected month',onClick:function(){c3Do('inspect');},style:{stretch:'horizontal'}}));
controlsPanel.add(ui.Button({label:'Reset map to Ghana',onClick:function(){levelSelect.setValue('ghana');Map.layers().reset();previewReady=false;previewLayers={};Map.addLayer(ee.Image().byte().paint(ee.FeatureCollection(C3.ghanaAsset),1,2),{palette:['ffffff']},'Ghana boundary',true);Map.centerObject(ee.FeatureCollection(C3.ghanaAsset),7);status.setValue('Ghana focus selected; inspect a month to refresh evidence layers.');},style:{stretch:'horizontal'}}));
controlsPanel.add(ui.Button({label:'Open Layers',onClick:function(){c3Tab('layers');}}));
controlsPanel.add(ui.Button({label:'Open Exports',onClick:function(){c3Tab('exports');}}));
layersPanel.add(ui.Button({label:'Add 12 monthly BA evidence layers',onClick:function(){c3Do('ba_stack');},style:{stretch:'horizontal'}}));
layersPanel.add(ui.Button({label:'Restore selected-month view',onClick:function(){c3Do('inspect');},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Label('BA bands: fixed union, unresolved, state codes 0–6 (including five evidence states), accepted, anomaly, reason masks and raw BurnDate. Tasks are not submitted automatically.',{whiteSpace:'normal',fontSize:'11px'}));
exportsPanel.add(ui.Button({label:'Create selected-month BA evidence raster (1)',onClick:function(){c3Do('ba_month');},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create 12 selected-year monthly BA rasters',onClick:function(){c3Do('ba_year');},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create union / annual eligibility raster (1)',onClick:function(){c3Do('domain');},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create selected unit-month CSV (1)',onClick:function(){c3Do('csv_month');},style:{stretch:'horizontal'}}));
aboutPanel.add(ui.Label('BA2001 and BA2012 use separately constructed fixed period unions. Unknown monthly evidence contributes zero under the study scenario; this is not proof of unburned land. A qualifying positive with shortened mapping remains accepted.',{fontSize:'11px',whiteSpace:'normal'}));
aboutPanel.add(ui.Label('A positive source anomaly in the known union or unresolved union membership can withhold a unit-month result. Pixel map evidence and diagnostics are not a substitute for the CSV status. Source mismatch blocks output.',{fontSize:'11px',whiteSpace:'normal'}));
