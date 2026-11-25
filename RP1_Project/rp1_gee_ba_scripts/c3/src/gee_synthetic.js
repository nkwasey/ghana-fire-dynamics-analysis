/* Run manually in the EE Code Editor. No private assets or exports are used. */
var col=43000, row=16000;
var x=C3.transform[2]+col*C3.transform[0], y=C3.transform[5]+row*C3.transform[4];
var geom=ee.Geometry.Rectangle([x+0.1*C3.transform[0],y+0.9*C3.transform[4],
  x+0.9*C3.transform[0],y+0.1*C3.transform[4]],ee.Projection(C3.crs),false);
var one=ee.Image.constant(1), zero=ee.Image.constant(0);
var dom={eligible:one,unresolved:zero,excluded:zero,anyLcMissing:zero,anyLwMissing:zero,
  anyLcInvalid:zero,anyLwInvalid:zero,
  annual:{2024:{eligible:one,unknown:zero}}};
var cases=[
  {id:'accepted_full', b:100,q:3,bm:1,qm:1,state:'state_accepted',burn:1},
  {id:'accepted_shortened',b:100,q:7,bm:1,qm:1,state:'state_accepted',burn:1,short:1},
  {id:'explicit_zero',b:0,q:3,bm:1,qm:1,state:'state_explicit_zero',burn:0},
  {id:'masked_burn',b:0,q:3,bm:0,qm:1,state:'state_burndate_masked',burn:0,masked:1},
  {id:'missing_qa_and_burn',b:0,q:3,bm:0,qm:0,state:'state_qa_missing',burn:0,masked:1},
  {id:'invalid',b:100,q:1,bm:1,qm:1,state:'state_unsupported',burn:0},
  {id:'water_qa',b:100,q:2,bm:1,qm:1,state:'state_unsupported',burn:0},
  {id:'special_zero',b:0,q:35,bm:1,qm:1,state:'state_unsupported',burn:0},
  {id:'positive_special',b:100,q:35,bm:1,qm:1,state:'state_unsupported',burn:0,positiveSpecial:1,anomaly:1},
  {id:'last_valid_day',b:366,q:3,bm:1,qm:1,state:'state_accepted',burn:1},
  {id:'above_range',b:367,q:3,bm:1,qm:1,state:'state_unsupported',burn:0,anomaly:1},
  {id:'combined_shortened',b:367,q:39,bm:1,qm:1,state:'state_unsupported',burn:0,positiveSpecial:1,short:1,anomaly:1},
  {id:'anomaly_invalid_land',b:367,q:0,bm:1,qm:1,state:'state_unsupported',burn:0,anomaly:1},
  {id:'positive_missing_qa',b:367,q:3,bm:1,qm:0,state:'state_qa_missing',burn:0},
  {id:'masked_positive',b:367,q:35,bm:0,qm:1,state:'state_burndate_masked',burn:0,masked:1}
];
for (var code=1; code<=7; code++) cases.push({id:'special_code_'+code,b:100,q:3+32*code,
  bm:1,qm:1,state:'state_unsupported',burn:0,positiveSpecial:1,anomaly:1});
var result=ee.FeatureCollection(cases.map(function(c){
  var burn=ee.Image.constant(c.b).updateMask(ee.Image.constant(c.bm)).rename('BurnDate');
  var qa=ee.Image.constant(c.q).updateMask(ee.Image.constant(c.qm)).rename('QA');
  var e=c3Evidence(burn.addBands(qa));
  var v=ee.Dictionary(c3Stack(dom,e,2024).reduceRegion({reducer:ee.Reducer.sum().unweighted(),
    geometry:geom,crs:C3.crs,crsTransform:C3.transform,maxPixels:100,tileScale:1}));
  var states=['state_qa_missing','state_burndate_masked','state_unsupported','state_explicit_zero','state_accepted'];
  var sum=ee.Number(0); states.forEach(function(k){sum=sum.add(ee.Number(v.get(k)));});
  var ok=ee.Number(v.get('samples')).eq(1).and(ee.Number(v.get('burn_pixels')).eq(c.burn))
    .and(ee.Number(v.get(c.state)).subtract(ee.Number(v.get('union'))).abs().lt(1e-8))
    .and(sum.subtract(ee.Number(v.get('union'))).abs().lt(1e-8))
    .and(ee.Number(v.get('reason_shortened')).gt(0).eq(c.short||0))
    .and(ee.Number(v.get('reason_burndate_masked')).gt(0).eq(c.masked||0))
    .and(ee.Number(v.get('reason_positive_special')).gt(0).eq(c.positiveSpecial||0))
    .and(ee.Number(v.get('anomaly_pixels')).eq(c.anomaly||0));
  return ee.Feature(null,{case_id:c.id,expected_state:c.state,pass:ok,diagnostics:v});
}));
print('c3 synthetic EE checks: each pass should be 1; inspect failures and stop before selected-source processing',result);
print('Number of failed synthetic cases (must be zero)',result.filter(ee.Filter.eq('pass',0)).size());
var domainCases=[
  {id:'known_eligible_beats_unknown',a:[0,1],b:[1,0],expected:'eligible'},
  {id:'unknown_without_eligible',a:[0,1],b:[0,0],expected:'unresolved'},
  {id:'all_known_excluded',a:[0,0],b:[0,0],expected:'excluded'}
];
var domainResults=ee.FeatureCollection(domainCases.map(function(c){
  var d=c3DomainLogic(C3_OPS,[{eligible:ee.Image.constant(c.a[0]),unknown:ee.Image.constant(c.a[1])},
    {eligible:ee.Image.constant(c.b[0]),unknown:ee.Image.constant(c.b[1])}]);
  var image=ee.Image.cat([d.eligible.rename('eligible'),d.unresolved.rename('unresolved'),d.excluded.rename('excluded')]);
  var v=ee.Dictionary(image.reduceRegion({reducer:ee.Reducer.sum().unweighted(),geometry:geom,
    crs:C3.crs,crsTransform:C3.transform,maxPixels:100,tileScale:1}));
  var total=ee.Number(v.get('eligible')).add(ee.Number(v.get('unresolved'))).add(ee.Number(v.get('excluded')));
  return ee.Feature(null,{case_id:c.id,expected_state:c.expected,
    pass:ee.Number(v.get(c.expected)).eq(1).and(total.eq(1)),diagnostics:v});
}));
print('c3 synthetic union-state checks: each pass should be 1',domainResults);
print('Number of failed synthetic union cases (must be zero)',domainResults.filter(ee.Filter.eq('pass',0)).size());

// Exercise the actual c3Row with one or two cell-centres, no assets or tasks.
// These are proposed live tests; code generation and Node parsing do not run EE.
var rowUnitProps={level:'acz',unit_id:'synthetic',unit_code:'S',unit_name:'SYNTHETIC',
  parent_level:'',parent_id:'',parent_code:'',parent_name:''};
var rowUnit=ee.Feature(geom,rowUnitProps);
var rowProfile={id:'BA2001',start:2001,end:2024};
var rowDate={year:2024,month:1};
var rowEvidence=c3Evidence(ee.Image.constant(100).rename('BurnDate')
  .addBands(ee.Image.constant(3).rename('QA')));
var rowSourceMasked=c3Evidence(ee.Image.constant(0).rename('BurnDate').updateMask(zero)
  .addBands(ee.Image.constant(3).rename('QA')));
var savedC3Stack=c3Stack;
function c3TestRow(unit,domain,evidence) {
  return c3Row(unit,rowProfile,rowDate,domain,evidence,'synthetic',['synthetic'],'synthetic');
}
function c3TestInjectedRow(unit,band,maskImage) {
  c3Stack=function(domain,evidence,year) {
    var img=savedC3Stack(domain,evidence,year);
    return img.addBands(img.select(band).updateMask(maskImage),null,true);
  };
  var rowOut=c3TestRow(unit,dom,rowEvidence);
  c3Stack=savedC3Stack;
  return rowOut;
}
function c3TestStatus(feature,expected) {
  return ee.String(feature.get('ba_status')).compareTo(expected).eq(0);
}
function c3TestMissing(feature,field) { return c3MissingNumber(feature.toDictionary(),field); }
function c3TestValue(feature,field) { return ee.Number(ee.Dictionary(feature.toDictionary()).get(field,-9999)); }
function c3TestWithheld(feature) {
  return c3TestMissing(feature,'modis_ba_km2').and(c3TestMissing(feature,'modis_burnable_km2_union'))
    .and(c3TestMissing(feature,'modis_burned_frac_union'))
    .and(c3TestMissing(feature,'ba_known_union_area_km2'));
}
function c3TestIncompleteWithheld(feature) {
  return c3TestWithheld(feature).and(c3TestMissing(feature,'ba_sampled_pixel_count'));
}
var twoCentreGeom=ee.Geometry.Rectangle([x+0.1*C3.transform[0],y+0.9*C3.transform[4],
  x+1.9*C3.transform[0],y+0.1*C3.transform[4]],ee.Projection(C3.crs),false);
var twoUnit=ee.Feature(twoCentreGeom,rowUnitProps);
// Rasterize two distinct interior rectangles on the exact native grid. Do not
// assume that pixelCoordinates returns the array indices used to build geom.
var secondGeom=ee.Geometry.Rectangle([x+1.1*C3.transform[0],y+0.9*C3.transform[4],
  x+1.9*C3.transform[0],y+0.1*C3.transform[4]],ee.Projection(C3.crs),false);
var gridOne=ee.Image.constant(1).reproject({crs:C3.crs,crsTransform:C3.transform});
var firstCell=gridOne.clip(geom).unmask(0,false);
var secondCell=gridOne.clip(secondGeom).unmask(0,false);
// Check the actual injected metric mask, not only its input mask.
var injectedUnionValid=savedC3Stack(dom,rowEvidence,2024).select('union')
  .updateMask(firstCell).mask().unmask(0,false).gt(0);
var twoCellProbe=ee.Dictionary(gridOne.rename('centres')
  .addBands(firstCell.rename('first')).addBands(secondCell.rename('second'))
  .addBands(firstCell.and(secondCell).rename('overlap'))
  .addBands(firstCell.or(secondCell).rename('either'))
  .addBands(injectedUnionValid.rename('injected_union_valid'))
  .reduceRegion({reducer:ee.Reducer.sum().unweighted(),geometry:twoCentreGeom,
    crs:C3.crs,crsTransform:C3.transform,maxPixels:100,tileScale:1}));
var twoSetup=ee.Number(twoCellProbe.get('centres',-9999)).eq(2)
  .and(ee.Number(twoCellProbe.get('first',-9999)).eq(1))
  .and(ee.Number(twoCellProbe.get('second',-9999)).eq(1))
  .and(ee.Number(twoCellProbe.get('overlap',-9999)).eq(0))
  .and(ee.Number(twoCellProbe.get('either',-9999)).eq(2))
  .and(ee.Number(twoCellProbe.get('injected_union_valid',-9999)).eq(1));
print('c3 two-centre masks: expect centres=2, first=1, second=1, overlap=0, either=2, injected_union_valid=1',twoCellProbe);
var rowNormal=c3TestRow(rowUnit,dom,rowEvidence);
var rowNormalTwo=c3TestRow(twoUnit,dom,rowEvidence);
var rowPartialMask=c3TestInjectedRow(rowUnit,'union',zero);
var rowPartialTwo=c3TestInjectedRow(twoUnit,'union',firstCell);
// The reason is numerically zero when valid; the guard must still detect its missing mask.
var rowMaskedZeroReason=c3TestInjectedRow(rowUnit,'reason_special',zero);
// The independent centre reference must detect masking of the samples band itself.
var rowMaskedSamples=c3TestInjectedRow(rowUnit,'samples',zero);
// All bands are available, but the supplied domain total is intentionally
// inconsistent with the accepted positive burn. This tests accounting without
// relying on any missing-mask detection.
c3Stack=function(domain,evidence,year) {
  var img=savedC3Stack(domain,evidence,year);
  return img.addBands(ee.Image.constant(0).rename('union'),null,true);
};
var rowBadAccounting=c3TestRow(rowUnit,dom,rowEvidence);
c3Stack=savedC3Stack;
var zeroUnionDom={eligible:zero,unresolved:zero,excluded:one,anyLcMissing:zero,anyLwMissing:zero,
  anyLcInvalid:zero,anyLwInvalid:zero,annual:{2024:{eligible:zero,unknown:zero}}};
var rowValidZeroUnion=c3TestRow(rowUnit,zeroUnionDom,rowEvidence);
var rowMaskedBurnDate=c3TestRow(rowUnit,dom,rowSourceMasked);
var anomalyEvidence=c3Evidence(ee.Image.constant(367).rename('BurnDate')
  .addBands(ee.Image.constant(39).rename('QA')));
var rowAnomaly=c3TestRow(rowUnit,dom,anomalyEvidence);
var rowAnomalyOutside=c3TestRow(rowUnit,zeroUnionDom,anomalyEvidence);
var unresolvedDom={eligible:one,unresolved:one,excluded:zero,anyLcMissing:zero,anyLwMissing:zero,
  anyLcInvalid:zero,anyLwInvalid:zero,annual:{2024:{eligible:one,unknown:zero}}};
// A two-cell domain is used to keep the union and unresolved states disjoint.
unresolvedDom.eligible=firstCell; unresolvedDom.unresolved=secondCell;
var rowUnresolvedAnomaly=c3TestRow(twoUnit,unresolvedDom,anomalyEvidence);
var noCentreGeom=ee.Geometry.Rectangle([x+0.05*C3.transform[0],y+0.10*C3.transform[4],
  x+0.10*C3.transform[0],y+0.05*C3.transform[4]],ee.Projection(C3.crs),false);
var rowNoCentre=c3TestRow(ee.Feature(noCentreGeom,rowUnitProps),dom,rowEvidence);
var noCentreStatus=c3TestStatus(rowNoCentre,'NO_PIXEL_CENTRES')
  .or(c3TestStatus(rowNoCentre,'EMPTY_REDUCTION_UNRESOLVED'));
var rowResults=ee.FeatureCollection([
  ee.Feature(null,{case_id:'row_normal',pass:c3TestStatus(rowNormal,'ADMITTED')
    .and(c3TestValue(rowNormal,'modis_burned_frac_union').eq(1))
    .and(c3TestValue(rowNormal,'ba_reason_special_km2').eq(0)),row:rowNormal.toDictionary()}),
  ee.Feature(null,{case_id:'row_normal_two_cells',pass:twoSetup
    .and(c3TestStatus(rowNormalTwo,'ADMITTED'))
    .and(c3TestValue(rowNormalTwo,'ba_sampled_pixel_count').eq(2))
    .and(c3TestValue(rowNormalTwo,'modis_burned_pixel_count').eq(2))
    .and(c3TestValue(rowNormalTwo,'modis_burned_frac_union').eq(1)),row:rowNormalTwo.toDictionary()}),
  ee.Feature(null,{case_id:'row_partial_mask',pass:c3TestStatus(rowPartialMask,'REDUCTION_INCOMPLETE')
    .and(c3TestIncompleteWithheld(rowPartialMask)),row:rowPartialMask.toDictionary()}),
  ee.Feature(null,{case_id:'row_partial_two_cells',pass:twoSetup.and(c3TestStatus(rowPartialTwo,'REDUCTION_INCOMPLETE'))
    .and(c3TestIncompleteWithheld(rowPartialTwo)),row:rowPartialTwo.toDictionary()}),
  ee.Feature(null,{case_id:'row_masked_zero_reason',pass:c3TestStatus(rowMaskedZeroReason,'REDUCTION_INCOMPLETE')
    .and(c3TestIncompleteWithheld(rowMaskedZeroReason)),row:rowMaskedZeroReason.toDictionary()}),
  ee.Feature(null,{case_id:'row_masked_samples',pass:c3TestStatus(rowMaskedSamples,'REDUCTION_INCOMPLETE')
    .and(c3TestIncompleteWithheld(rowMaskedSamples)),row:rowMaskedSamples.toDictionary()}),
  ee.Feature(null,{case_id:'row_bad_accounting_valid_masks',pass:c3TestStatus(rowBadAccounting,'ACCOUNTING_INCONSISTENCY')
    .and(c3TestIncompleteWithheld(rowBadAccounting)),row:rowBadAccounting.toDictionary()}),
  ee.Feature(null,{case_id:'row_valid_zero_union',pass:c3TestStatus(rowValidZeroUnion,'ZERO_UNION_DENOMINATOR')
    .and(c3TestValue(rowValidZeroUnion,'modis_ba_km2').eq(0))
    .and(c3TestValue(rowValidZeroUnion,'modis_burnable_km2_union').eq(0))
    .and(c3TestMissing(rowValidZeroUnion,'modis_burned_frac_union')),row:rowValidZeroUnion.toDictionary()}),
  ee.Feature(null,{case_id:'row_source_masked_burndate',pass:c3TestStatus(rowMaskedBurnDate,'ADMITTED')
    .and(ee.String(rowMaskedBurnDate.get('ba_coverage_status')).compareTo('NO_SUPPORTED_EVIDENCE').eq(0))
    .and(c3TestValue(rowMaskedBurnDate,'modis_ba_km2').eq(0))
    .and(c3TestValue(rowMaskedBurnDate,'modis_burned_frac_union').eq(0))
    .and(c3TestValue(rowMaskedBurnDate,'ba_state_burndate_masked_km2').gt(0))
    .and(c3TestValue(rowMaskedBurnDate,'ba_state_explicit_zero_km2').eq(0))
    .and(c3TestValue(rowMaskedBurnDate,'ba_supported_area_km2').eq(0))
    .and(c3TestMissing(rowMaskedBurnDate,'ba_supported_fraction')),row:rowMaskedBurnDate.toDictionary()}),
  ee.Feature(null,{case_id:'row_anomaly',pass:c3TestStatus(rowAnomaly,'SOURCE_PIXEL_ANOMALY')
    .and(c3TestMissing(rowAnomaly,'modis_ba_km2')).and(c3TestMissing(rowAnomaly,'modis_burnable_km2_union'))
    .and(c3TestMissing(rowAnomaly,'modis_burned_frac_union')).and(c3TestMissing(rowAnomaly,'modis_burned_frac_annual'))
    .and(c3TestValue(rowAnomaly,'modis_burnable_km2_annual').gt(0))
    .and(c3TestValue(rowAnomaly,'ba_anomaly_pixel_count').eq(1))
    .and(c3TestValue(rowAnomaly,'ba_state_unsupported_km2').gt(0))
    .and(c3TestValue(rowAnomaly,'ba_state_closure_km2').abs().lt(1e-8)),row:rowAnomaly.toDictionary()}),
  ee.Feature(null,{case_id:'row_anomaly_outside_union',pass:c3TestStatus(rowAnomalyOutside,'ZERO_UNION_DENOMINATOR')
    .and(c3TestValue(rowAnomalyOutside,'ba_anomaly_pixel_count').eq(0)),row:rowAnomalyOutside.toDictionary()}),
  ee.Feature(null,{case_id:'row_unresolved_over_anomaly',pass:twoSetup.and(c3TestStatus(rowUnresolvedAnomaly,'DOMAIN_UNRESOLVED'))
    .and(c3TestValue(rowUnresolvedAnomaly,'ba_anomaly_pixel_count').eq(1)),row:rowUnresolvedAnomaly.toDictionary()}),
  ee.Feature(null,{case_id:'row_no_centre',pass:noCentreStatus.and(c3TestWithheld(rowNoCentre)),
    row:rowNoCentre.toDictionary()})
]);
print('c3 synthetic row checks: each pass should be 1',rowResults);
print('Number of failed synthetic row cases (must be zero)',rowResults.filter(ee.Filter.eq('pass',0)).size());
