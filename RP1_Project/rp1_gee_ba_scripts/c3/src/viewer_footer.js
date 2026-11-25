// =============================================================================
// VIEWER 07 — PRODUCT PLANS AND STANDARD EXPORT BUNDLES
// =============================================================================
function c3LstName(s,date){return 'MOD11A1_061_DN_c3_'+c3ScopeTag(s)+'_'+date.year+'_'+c3Pad(date.month);}
function c3LcName(s){return 'MCD12Q1_061_LCType1_LW_c3_'+c3ScopeTag(s)+'_'+s.date.year;}
function c3BaName(s,date){return 'MCD64A1_061_Burn_c3_'+s.profile.id+'_'+c3ScopeTag(s)+'_'+date.year+'_'+c3Pad(date.month);}
var c3LastViewPlan=null;
function c3ViewPlan(fullYear){
  try{
    var s=c3Settings(),dates=fullYear?c3DatesForYear(s.date.year):[s.date],names=[];
    for(var i=0;i<dates.length;i++){names.push(c3BaName(s,dates[i]));names.push(c3LstName(s,dates[i]));}
    if(fullYear)names.push(c3LcName(s));
    c3LastViewPlan=JSON.stringify({scope:s.level,scope_name:c3ScopeTag(s),domain:s.profile.id,folder:C3.driveFolder,prefixes:names});
    print('VIEWER PRODUCT PLAN — task descriptions and file prefixes; no source checks and no tasks created',
      {scope:s.level,scope_name:c3ScopeTag(s),domain:s.profile.id,folder:C3.driveFolder,count:names.length,prefixes:names,
       includes:fullYear?'12 monthly BA + 12 monthly LST + selected-year LC/LW':'one monthly BA + one monthly LST'});
    status.setValue('Plan: '+names.length+' tasks. Inspect exact names in Console. Source checks run on creation.');
  }catch(e){status.setValue('BLOCKED: '+String((e&&e.message)||e));}
}
function c3QueueLstKnown(s,date,projection){
  var name=c3LstName(s,date),geom=s.units.geometry();
  c3WarnDuplicate(name);
  Export.image.toDrive({image:c3MonthlyLst(date,geom).unmask(-9999,false),description:name,folder:C3.driveFolder,
    fileNamePrefix:name,region:geom,crs:projection.crs,crsTransform:projection.transform,maxPixels:C3.maxPixels,
    fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
  c3RememberRaster(name);return name;
}
function c3QueueLcKnown(s,receipt){
  var index=receipt.lc_indexes[s.date.year-s.profile.start],geom=s.units.geometry();
  var source=c3LcImage(index),name=c3LcName(s);
  var img=source.select(['LC_Type1','LW']).toFloat().clip(geom).unmask(-9999,false);
  c3WarnDuplicate(name);
  Export.image.toDrive({image:img,description:name,folder:C3.driveFolder,fileNamePrefix:name,region:geom,
    crs:C3.crs,crsTransform:C3.transform,maxPixels:C3.maxPixels,fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
  c3RememberRaster(name);return name;
}
function c3QueueStandard(fullYear){
  var created=[];
  try{
    var s=c3Settings(),dates=fullYear?c3DatesForYear(s.date.year):[s.date],counts=[],projections=[],i;
    var names=[];
    for(i=0;i<dates.length;i++){names.push(c3BaName(s,dates[i]));names.push(c3LstName(s,dates[i]));}
    if(fullYear)names.push(c3LcName(s));
    var signature=JSON.stringify({scope:s.level,scope_name:c3ScopeTag(s),domain:s.profile.id,folder:C3.driveFolder,prefixes:names});
    if(c3LastViewPlan!==signature)throw new Error('Inspect the current matching export plan before creating tasks.');
    status.setValue('Checking BA, land-cover and LST sources and projections before task creation...');
    var receipt=c3SourcePreflight(s.profile,dates,s.units,s.level);
    for(i=0;i<dates.length;i++)counts.push(c3LstSource(dates[i]).size());
    var n=ee.List(counts).getInfo();
    if(!n||n.length!==dates.length||n.some(function(v){return !v;}))throw new Error('One or more LST months are missing.');
    for(i=0;i<dates.length;i++){
      var p=ee.Image(c3LstSource(dates[i]).first()).select('LST_Day_1km').projection().getInfo();
      if(!p||!p.crs||!p.transform||p.transform.length!==6)throw new Error('An LST source projection is unavailable.');
      projections.push(p);
    }
    var domain=c3Domain(s.profile,receipt);
    for(i=0;i<dates.length;i++){created.push(c3QueueBa(s,domain,dates[i],receipt.ba_indexes[i][0]));created.push(c3QueueLstKnown(s,dates[i],projections[i]));}
    if(fullYear)created.push(c3QueueLcKnown(s,receipt));
    status.setValue((dates.length*2+(fullYear?1:0))+' tasks created; review and run them manually.');
    print('Standard product batch created',{count:dates.length*2+(fullYear?1:0),lst_monthly_source_image_counts:n,domain:s.profile.id,scope:c3ScopeTag(s)});
  }catch(e){
    var msg=String((e&&e.message)||e);
    status.setValue((created.length?'PARTIAL: '+created.length+' task(s) created; inspect Tasks. ':'BLOCKED: ')+msg);
    print('Standard product batch blocked',msg,'created_prefixes',created);
  }
}
exportsPanel.add(ui.Label('Standard bundles contain BA evidence and LST; the selected-year bundle also includes LC/LW. Domain diagnostics and the selected-month CSV are separate.',{fontSize:'11px',whiteSpace:'normal'}));
exportsPanel.add(ui.Button({label:'Inspect monthly BA + LST plan (2)',onClick:function(){c3ViewPlan(false);},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create monthly BA + LST tasks (2)',onClick:function(){c3QueueStandard(false);},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Inspect annual standard-product plan (25)',onClick:function(){c3ViewPlan(true);},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create annual standard-product tasks (25)',onClick:function(){c3QueueStandard(true);},style:{stretch:'horizontal'}}));
// =============================================================================
// VIEWER 08 — LEGEND AND INITIALIZATION
// =============================================================================
var legend=ui.Panel({style:{position:'top-right',width:'250px',padding:'8px'}});
legend.add(ui.Label('RP1 c3 legend',{fontWeight:'bold',fontSize:'13px'}));
legend.add(ui.Label('Red: accepted evidence | Cyan: anomaly | Magenta: unresolved union',{fontSize:'10px',whiteSpace:'normal'}));
legend.add(ui.Label('Purple: masked BurnDate | Blue: QA unavailable | Orange: shortened',{fontSize:'10px',whiteSpace:'normal'}));
legend.add(ui.Label('LST temperature: blue to red, 10–45 °C; other LST bands use their own scale.',{fontSize:'10px',whiteSpace:'normal'}));
legend.add(ui.Label('Evidence states are exclusive; reasons can overlap. Maps do not certify unit results.',{fontSize:'10px',whiteSpace:'normal'}));
var classLegend=ui.Panel();classLegend.style().set('shown',false);
var classLabels=['1 Evergreen Needleleaf Forest','2 Evergreen Broadleaf Forest','3 Deciduous Needleleaf Forest',
 '4 Deciduous Broadleaf Forest','5 Mixed Forest','6 Closed Shrublands','7 Open Shrublands',
 '8 Woody Savannas','9 Savannas','10 Grasslands','11 Permanent Wetlands','12 Croplands',
 '13 Urban and Built-up','14 Cropland/Natural Vegetation Mosaic','15 Snow and Ice','16 Barren','17 Water Bodies'];
var classColors=['05450a','086a10','54a708','78d203','009900','c6b044','dcd159','dade48','fbff13',
 'b6ff05','27ff87','c24f44','a5a5a5','ff6d4c','69fff8','f9ffa4','1c0dff'];
classLabels.forEach(function(label,i){classLegend.add(ui.Panel([
 ui.Label('',{backgroundColor:'#'+classColors[i],padding:'6px',margin:'1px 5px 1px 0'}),
 ui.Label(label,{fontSize:'10px',margin:'0'})],ui.Panel.Layout.flow('horizontal')));});
legend.add(ui.Checkbox({label:'Show 17 land-cover classes',value:false,onChange:function(v){classLegend.style().set('shown',v);}}));
legend.add(classLegend);
Map.add(legend);
layersPanel.add(ui.Checkbox({label:'Show map legend',value:true,onChange:function(v){legend.style().set('shown',v);}}));
c3Tab('controls');ui.root.insert(0,panel);Map.setOptions('SATELLITE');
Map.centerObject(ee.FeatureCollection(C3.ghanaAsset),7);
print(appTitle+' initialised. Ghana map focus. No source checks or export tasks run automatically.');
