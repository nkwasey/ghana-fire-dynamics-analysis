// =============================================================================
// VIEWER 06 — MOD11A1 MONTHLY LST AND ANNUAL LAND-COVER CONTEXT
// =============================================================================
// LST is independent of the burned-area domain and QA rules.
var lstBand = ui.Select({items:['LST_Day_C','LST_Night_C','Day_view_time_h','Night_view_time_h','n_day','n_night'],value:'LST_Day_C'});
layersPanel.add(ui.Label('LST layer (monthly MOD11A1)',{fontWeight:'bold'}));
layersPanel.add(lstBand);
function c3LstSource(date) {
  var w=c3Month(date.year,date.month);
  return ee.ImageCollection(C3.lstId).filterDate(w.start,w.end);
}
function c3MonthlyLst(date, geom) {
  var daily=c3LstSource(date).map(function(im) {
    im=ee.Image(im);
    var day=im.select('QC_Day').bitwiseAnd(3).eq(0), night=im.select('QC_Night').bitwiseAnd(3).eq(0);
    return im.select('LST_Day_1km').multiply(0.02).subtract(273.15).updateMask(day).rename('LST_Day_C')
      .addBands(im.select('LST_Night_1km').multiply(0.02).subtract(273.15).updateMask(night).rename('LST_Night_C'))
      .addBands(im.select('Day_view_time').multiply(0.1).updateMask(day).rename('Day_view_time_h'))
      .addBands(im.select('Night_view_time').multiply(0.1).updateMask(night).rename('Night_view_time_h'));
  });
  var means=daily.mean();
  var countDay=daily.select('LST_Day_C').count().rename('n_day');
  var countNight=daily.select('LST_Night_C').count().rename('n_night');
  return means.addBands(countDay).addBands(countNight).toFloat().clip(geom);
}
function c3LstAction(exportImage) {
  try {
    var s=c3Settings(), collection=c3LstSource(s.date);
    var counts=ee.Dictionary({units:s.units.size(),lst:collection.size()}).getInfo();
    if (!counts.units || !counts.lst) throw new Error('No selected boundary or no MOD11A1 images for this month.');
    var projection=ee.Image(collection.first()).select('LST_Day_1km').projection().getInfo();
    if (!projection || !projection.crs || !projection.transform || projection.transform.length!==6) {
      throw new Error('MOD11A1 native projection unavailable.');
    }
    var img=c3MonthlyLst(s.date,s.units.geometry());
    if (exportImage) {
      var name='MOD11A1_061_DN_c3_'+c3ScopeTag(s)+'_'+s.date.year+'_'+c3Pad(s.date.month);
      c3WarnDuplicate(name);
      Export.image.toDrive({image:img.unmask(-9999,false),description:name,folder:C3.driveFolder,
        fileNamePrefix:name,region:s.units.geometry(),crs:projection.crs,crsTransform:projection.transform,
        maxPixels:C3.maxPixels,fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
      c3RememberRaster(name);
      status.setValue('One monthly LST raster task created; start it manually.');
    } else {
      var band=lstBand.getValue(), vis={min:10,max:45,palette:['040274','2c7bb6','abd9e9','ffffbf','fdae61','d73027']};
      if (band.indexOf('view_time')>=0) vis={min:0,max:24,palette:['2c7bb6','ffffbf','d7191c']};
      if (band.indexOf('n_')===0) vis={min:0,max:31,palette:['ffffff','2c7bb6','08306b']};
      Map.addLayer(img.select(band),vis,'LST context: '+band,true);
      Map.centerObject(s.units,s.level==='district'?9:7);
      status.setValue('LST added. This layer uses its own product grid and QA.');
    }
    print('LST monthly source image count and first-image projection (not daily or pixel completeness)',counts.lst,projection);
  } catch(e) {status.setValue('BLOCKED: '+String(e.message||e));print('LST action blocked: '+String((e && e.message)||e));}
}
layersPanel.add(ui.Button({label:'Add selected LST layer',onClick:function(){c3LstAction(false);},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create selected-month LST raster task',onClick:function(){c3LstAction(true);},style:{stretch:'horizontal'}}));
function c3LstYear(stackOnly) {
  var created=[];
  try {
    var s=c3Settings(), dates=c3DatesForYear(s.date.year), checks=[], i;
    for (i=0;i<dates.length;i++) checks.push(c3LstSource(dates[i]).size());
    var receipt=ee.Dictionary({units:s.units.size(),counts:ee.List(checks)}).getInfo();
    if (!receipt.units || receipt.counts.some(function(n){return n===0;})) {
      throw new Error('A boundary or one or more MOD11A1 months are unavailable; no LST tasks created.');
    }
    if (stackOnly) {
      var band=lstBand.getValue(), vis={min:10,max:45,palette:['040274','2c7bb6','abd9e9','ffffbf','fdae61','d73027']};
      if (band.indexOf('view_time')>=0) vis={min:0,max:24,palette:['2c7bb6','ffffbf','d7191c']};
      if (band.indexOf('n_')===0) vis={min:0,max:31,palette:['ffffff','2c7bb6','08306b']};
      for (i=0;i<dates.length;i++) Map.addLayer(c3MonthlyLst(dates[i],s.units.geometry()).select(band),vis,
        'LST '+band+' '+dates[i].year+'-'+c3Pad(dates[i].month),i===s.date.month-1);
      Map.centerObject(s.units,s.level==='district'?9:7);
      status.setValue('Twelve monthly LST layers added; the selected month is shown. Toggle months in Layers.');
      print('LST source counts',receipt.counts); return;
    }
    var projections=[];
    for (i=0;i<dates.length;i++) {
      var p=ee.Image(c3LstSource(dates[i]).first()).select('LST_Day_1km').projection().getInfo();
      if (!p || !p.crs || !p.transform || p.transform.length!==6) throw new Error('LST projection unavailable; no LST tasks created.');
      projections.push(p);
    }
    for (i=0;i<dates.length;i++) {
      var date=dates[i], name='MOD11A1_061_DN_c3_'+c3ScopeTag(s)+'_'+date.year+'_'+c3Pad(date.month);
      c3WarnDuplicate(name);
      Export.image.toDrive({image:c3MonthlyLst(date,s.units.geometry()).unmask(-9999,false),
        description:name,folder:C3.driveFolder,fileNamePrefix:name,region:s.units.geometry(),
        crs:projections[i].crs,crsTransform:projections[i].transform,maxPixels:C3.maxPixels,
        fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
      c3RememberRaster(name);created.push(name);
    }
    status.setValue('Twelve monthly LST tasks created; start only the tasks intended.');
    print('LST source counts',receipt.counts);
  } catch(e) {status.setValue((created.length?'PARTIAL: '+created.length+' task(s) created. ':'BLOCKED: ')+String(e.message||e));print('LST annual action blocked: '+String((e && e.message)||e),'created_prefixes',created);}
}
function c3LcExport() {
  try {
    var s=c3Settings(), col=c3LcCollection(s.date.year);
    var counts=ee.Dictionary({units:s.units.size(),lc:col.size(),indexes:col.aggregate_array('system:index')}).getInfo();
    if (!counts.units || counts.lc!==1 || !counts.indexes || counts.indexes.length!==1 || !c3SafeIndex(counts.indexes[0])) throw new Error('Boundary is empty or annual land-cover source is not uniquely identified.');
    var source=c3LcImage(counts.indexes[0]);
    print('Annual land-cover source projections',source.select('LC_Type1').projection(),source.select('LW').projection());
    var img=source.select(['LC_Type1','LW']).toFloat().clip(s.units.geometry()).unmask(-9999,false);
    var name='MCD12Q1_061_LCType1_LW_c3_'+c3ScopeTag(s)+'_'+s.date.year;
    c3WarnDuplicate(name);
    Export.image.toDrive({image:img,description:name,folder:C3.driveFolder,fileNamePrefix:name,
      region:s.units.geometry(),crs:C3.crs,crsTransform:C3.transform,maxPixels:C3.maxPixels,
      fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
    c3RememberRaster(name);
    status.setValue('Annual LC/LW context task created on the BA grid, using nearest-neighbour sampling.');
  } catch(e) {status.setValue('BLOCKED: '+String(e.message||e));print('LC action blocked: '+String((e && e.message)||e));}
}
exportsPanel.add(ui.Button({label:'Create selected-year LST tasks (12)',onClick:function(){c3LstYear(false);},style:{stretch:'horizontal'}}));
layersPanel.add(ui.Button({label:'Add yearly LST layer stack (12)',onClick:function(){c3LstYear(true);},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create annual LC/LW context task',onClick:c3LcExport,style:{stretch:'horizontal'}}));
