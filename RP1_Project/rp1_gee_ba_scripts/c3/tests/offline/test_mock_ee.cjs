'use strict';
// One-pixel scalar mock executes actual c3Evidence, c3Annual, c3Domain, c3Stack,
// and c3Row. It is not a model of EE projection, geometry or evaluation.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
function val(x){return x instanceof N?x.v:x instanceof I?x.one().v:x;}
class N{
 constructor(x){this.v=Number(val(x));} add(x){return new N(this.v+val(x));} subtract(x){return new N(this.v-val(x));}
 multiply(x){return new N(this.v*val(x));} divide(x){return new N(this.v/val(x));} gt(x){return new N(+(this.v>val(x)));} lt(x){return new N(+(this.v<val(x)));} lte(x){return new N(+(this.v<=val(x)));} eq(x){return new N(+(this.v===val(x)));} neq(x){return new N(+(this.v!==val(x)));} abs(){return new N(Math.abs(this.v));} max(x){return new N(Math.max(this.v,val(x)));} round(){return new N(Math.round(this.v));}
 and(x){return new N(+(Boolean(this.v)&&Boolean(val(x))));} or(x){return new N(+(Boolean(this.v)||Boolean(val(x))));} int(){return new N(+Boolean(this.v));}
}
let reducerMutation=null;
function mk(v,valid=true){return {v:Array.isArray(v)?v.map(Number):Number(v),valid:Array.isArray(valid)?valid.map(Boolean):!!valid};}
function pixels(a){return Array.isArray(a.v)?a.v.length:1;}
function at(x,i){return Array.isArray(x)?x[i]:x;}
function makeBand(values,valids){return values.length===1?mk(values[0],valids[0]):mk(values,valids);}
class I{
 constructor(b){if(b instanceof I){this.b=Object.assign({},b.b);}else if(typeof b==='number'){this.b={constant:mk(b)};} else this.b=b;}
 one(){return Object.values(this.b)[0];}
 select(n){let names=Array.isArray(n)?n:[n],out={};for(const k of names){if(!(k in this.b))throw Error('missing band '+k);out[k]=this.b[k];}return new I(out);}
 mask(){let out={};for(const [k,a] of Object.entries(this.b)){let n=pixels(a);out[k]=makeBand(Array.from({length:n},(_,i)=>+at(a.valid,i)),Array(n).fill(true));}return new I(out);}
 unmask(x){let out={};for(const [k,a] of Object.entries(this.b)){let n=pixels(a);out[k]=makeBand(Array.from({length:n},(_,i)=>at(a.valid,i)?at(a.v,i):val(x)),Array(n).fill(true));}return new I(out);}
 addBands(x){return new I(Object.assign({},this.b,x.b));}
 bin(x,fn){let rhs=x instanceof I?x:new I(Number(val(x))),left=Object.entries(this.b),right=Object.entries(rhs.b),len=Math.max(left.length,right.length),out={};
  if(left.length!==right.length&&left.length!==1&&right.length!==1)throw Error('mock band count mismatch');
  for(let j=0;j<len;j++){let [lk,a]=left[left.length===1?0:j],[rk,b]=right[right.length===1?0:j],n=Math.max(pixels(a),pixels(b));
   let key=left.length===1&&right.length>1?rk:lk;
   out[key]=makeBand(Array.from({length:n},(_,i)=>fn(at(a.v,i),at(b.v,i))),Array.from({length:n},(_,i)=>Boolean(at(a.valid,i)&&at(b.valid,i))));
  }return new I(out);}
 and(x){return this.bin(x,(a,b)=>+(Boolean(a)&&Boolean(b)));} or(x){return this.bin(x,(a,b)=>+(Boolean(a)||Boolean(b)));}
 not(){let out={};for(const [k,a] of Object.entries(this.b)){let n=pixels(a);out[k]=makeBand(Array.from({length:n},(_,i)=>+!at(a.v,i)),Array.from({length:n},(_,i)=>at(a.valid,i)));}return new I(out);} gt(x){return this.bin(x,(a,b)=>+(a>b));} lt(x){return this.bin(x,(a,b)=>+(a<b));} eq(x){return this.bin(x,(a,b)=>+(a===b));}
 neq(x){return this.bin(x,(a,b)=>+(a!==b));} bitwiseAnd(x){return this.bin(x,(a,b)=>a&b);} rightShift(x){return this.bin(x,(a,b)=>a>>b);}
 multiply(x){return this.bin(x,(a,b)=>a*b);} divide(x){return this.bin(x,(a,b)=>a/b);}
 remap(src,dst,def){let a=this.one(),n=pixels(a);return new I({v:makeBand(Array.from({length:n},(_,i)=>{let j=src.indexOf(at(a.v,i));return j<0?def:dst[j];}),Array.from({length:n},(_,i)=>at(a.valid,i)))});}
 rename(name){let names=Array.isArray(name)?name:[name],values=Object.values(this.b),out={};if(names.length!==values.length)throw Error('mock rename count mismatch');names.forEach((k,i)=>out[k]=values[i]);return new I(out);} toInt(){return this;} toDouble(){return this;}
 reduce(reducer){if(reducer.kind!=='min')throw Error('mock only supports per-pixel minimum');let bands=Object.values(this.b),n=Math.max(...bands.map(pixels));return new I({min:makeBand(Array.from({length:n},(_,i)=>Math.min(...bands.map(b=>at(b.v,i)))),Array.from({length:n},(_,i)=>bands.every(b=>at(b.valid,i))))});}
 // For this mock's sampled one-pixel region, Earth Engine's unweighted sum
 // returns zero when a band's sole input is masked. This is deliberately NOT
 // a test for empty geometry or a complete model of EE deferred evaluation.
 reduceRegion(opts){let o={},n=Math.max(...Object.values(this.b).map(pixels));for(let [k,v] of Object.entries(this.b)){o[k]=0;if(!opts||!opts.geometry||!opts.geometry.noCentres)for(let i=0;i<n;i++)if(at(v.valid,i))o[k]+=at(v.v,i);}return reducerMutation?reducerMutation(o):o;}
}
function img(x){return x instanceof I?x:new I(x);} img.constant=x=>new I(Number(x));
img.pixelArea=()=>new I(1000000);img.cat=arr=>new I(Object.assign({},...arr.map(x=>x.b)));
function Num(x){return x instanceof N?x:new N(x);}
// Missing dictionary keys without a non-null default are errors, rather than
// automatically null. This tests the conservative Earth Engine API contract.
function Dict(x){return {get:(k,fallback)=>{
 if(Object.prototype.hasOwnProperty.call(x,k)) return x[k];
 if(fallback!==undefined && fallback!==null) return fallback;
 throw Error('Missing dictionary key without default: '+k);
}};}
class F{constructor(props,geom){this.p=props||{};this.g=geom||{area:()=>new N(1000000)};}get(k){return this.p[k];}geometry(){return this.g;}}
function Feature(x,p){if(x instanceof F&&!p)return x;return new F(p||x);}
const ee={Image:img,Number:Num,Dictionary:Dict,Feature, String:x=>String(x),
 Algorithms:{If:(c,a,b)=>Boolean(val(c))?a:b,IsEqual:(a,b)=>val(a)===val(b)},
 Reducer:{sum:()=>({unweighted:()=>({})}),min:()=>({kind:'min'})}};
let ctx={ee,console};vm.createContext(ctx);
for(const name of ['scientific_logic.js','ee_core.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../..','src',name),'utf8'),ctx);
// The reducer alone cannot distinguish an explicitly valid zero from an
// entirely masked band: both sums are zero. Its mask receipt must do so.
assert.strictEqual(new I({x:mk(0,true)}).reduceRegion().x,0);
assert.strictEqual(new I({x:mk(123,false)}).reduceRegion().x,0);
assert.strictEqual(new I({x:mk(0,true)}).mask().one().v,1);
assert.strictEqual(new I({x:mk(123,false)}).mask().one().v,0);
function image(b,qa,bv=true,qv=true){return new I({BurnDate:mk(b,bv),QA:mk(qa,qv)});}
function annual(lc,lw,lv=true,wv=true){return new I({LC_Type1:mk(lc,lv),LW:mk(lw,wv)});}
let sources={2001:annual(9,2),2002:annual(9,2)};
ctx.c3LcImage=index=>sources[Number(index)];
const receipt={lc_indexes:['2001','2002']};
let profile={id:'BA2001',start:2001,end:2002}, date={year:2002,month:1};
let unit=new F({level:'acz',unit_id:'forest',unit_code:'FZ',unit_name:'FOREST',parent_level:'',parent_id:'',parent_code:'',parent_name:''});
function unwrap(o){let out={};for(let [k,x] of Object.entries(o))out[k]=x instanceof N?x.v:x;return out;}
function row(raw){let d=ctx.c3Domain(profile,receipt),e=ctx.c3Evidence(raw);return unwrap(ctx.c3Row(unit,profile,date,d,e,'2024_01_01',['a','b'],'run').p);}
let r=row(image(100,3));assert.strictEqual(r.modis_ba_km2,1);assert.strictEqual(r.modis_burned_frac_union,1);assert.strictEqual(r.ba_state_closure_km2,0);
r=row(image(100,7));assert.strictEqual(r.modis_ba_km2,1);assert.strictEqual(r.ba_shortened_km2,1);assert.strictEqual(r.ba_full_period_only_km2,0);
r=row(image(0,3,false));assert.strictEqual(r.modis_ba_km2,0);assert.strictEqual(r.ba_state_burndate_masked_km2,1);assert.strictEqual(r.ba_supported_fraction,null);
r=row(image(0,3,true));assert.strictEqual(r.modis_ba_km2,0);assert.strictEqual(r.ba_state_explicit_zero_km2,1);assert.strictEqual(r.ba_state_burndate_masked_km2,0);
r=row(image(0,3,false,false));assert.strictEqual(r.ba_state_qa_missing_km2,1);assert.strictEqual(r.ba_reason_burndate_masked_km2,1);assert.strictEqual(r.ba_state_closure_km2,0);
r=row(image(100,35));assert.strictEqual(r.modis_ba_km2,null);assert.strictEqual(r.ba_status,'SOURCE_PIXEL_ANOMALY');assert.strictEqual(r.ba_reason_positive_special_km2,1);
r=row(image(367,3));assert.strictEqual(r.modis_ba_km2,null);assert.strictEqual(r.ba_status,'SOURCE_PIXEL_ANOMALY');assert.strictEqual(r.ba_reason_unexpected_burndate_km2,1);
sources={2001:annual(9,2,false,true),2002:annual(13,2)};
r=row(image(100,3));assert.strictEqual(r.ba_status,'DOMAIN_UNRESOLVED');assert.strictEqual(r.modis_ba_km2,null);assert.strictEqual(r.ba_domain_unresolved_km2,1);
sources={2001:annual(255,2),2002:annual(13,2)};
r=row(image(100,3));assert.strictEqual(r.ba_status,'DOMAIN_UNRESOLVED');assert.strictEqual(r.ba_any_lc_invalid_year_km2,1);
sources={2001:annual(9,0),2002:annual(13,2)};
r=row(image(100,3));assert.strictEqual(r.ba_status,'DOMAIN_UNRESOLVED');assert.strictEqual(r.ba_any_lw_invalid_year_km2,1);
sources={2001:annual(13,2),2002:annual(13,2)};
r=row(image(100,3));assert.strictEqual(r.modis_ba_km2,0);assert.strictEqual(r.modis_burnable_km2_union,0);assert.strictEqual(r.modis_burned_frac_union,null);assert.strictEqual(r.ba_status,'ZERO_UNION_DENOMINATOR');
// Construct region images from actual c3Stack per-pixel outputs; the mock
// reducer then sums their values/masks, including zero for all-masked bands.
const originalStack=ctx.c3Stack;
function stackFor(lc2001,lc2002,burn,qa,burnValid=true,qaValid=true){
 sources={2001:annual(lc2001,2),2002:annual(lc2002,2)};
 return originalStack(ctx.c3Domain(profile,receipt),ctx.c3Evidence(image(burn,qa,burnValid,qaValid)),2002);
}
function regionStack(stacks){
 let keys=Object.keys(stacks[0].b),out={};
 for(const st of stacks)assert.deepStrictEqual(Object.keys(st.b),keys);
 for(const k of keys)out[k]=mk(stacks.map(st=>st.b[k].v),stacks.map(st=>st.b[k].valid));
 return new I(out);
}
function runStack(stack,target=unit){
 ctx.c3Stack=()=>stack;
 return unwrap(ctx.c3Row(target,profile,date,{}, {},'src',['a'],'run').p);
}
let good=regionStack([stackFor(9,9,100,3),stackFor(9,9,0,3,false)]);
let f=runStack(good);
assert.strictEqual(f.ba_status,'ADMITTED');assert.strictEqual(f.ba_sampled_pixel_count,2);
assert.strictEqual(f.modis_ba_km2,1);assert.strictEqual(f.modis_burnable_km2_union,2);
assert.strictEqual(f.ba_state_burndate_masked_km2,1);assert.strictEqual(f.modis_burned_frac_union,0.5);
// The same reducer numeric zero occurs for valid zero and a masked band; only
// a true zero preserves every derived-band mask and passes the guard.
let validZero=regionStack([stackFor(9,9,0,3),stackFor(9,9,0,3)]);
f=runStack(validZero);assert.strictEqual(f.ba_status,'ADMITTED');assert.strictEqual(f.modis_ba_km2,0);
// A positive pixel count paired with zero accepted area must never pass the
// accounting guard, even if all other area totals and masks remain valid.
let falseCount=regionStack([stackFor(9,9,0,3),stackFor(9,9,0,3)]);
falseCount.b.burn_pixels=mk([1,0],[true,true]);
f=runStack(falseCount);assert.strictEqual(f.ba_status,'ACCOUNTING_INCONSISTENCY');assert.strictEqual(f.modis_ba_km2,null);
for(const [band,mask] of [['union',[false,false]],['union',[true,false]],['state_accepted',[false,false]],['samples',[true,false]]]){
 let bad=regionStack([stackFor(9,9,100,3),stackFor(9,9,0,3)]);
 bad.b[band]=mk(bad.b[band].v,mask);
 if(mask.every(x=>!x))assert.strictEqual(bad.reduceRegion()[band],0,'all-masked sum must be 0');
 f=runStack(bad);
 assert.strictEqual(f.ba_status,'REDUCTION_INCOMPLETE',band+' '+mask);
 assert.strictEqual(f.modis_ba_km2,null);assert.strictEqual(f.ba_known_union_area_km2,null);
}
// Actual row + real per-pixel domain builders: three union burns but only one
// pixel eligible in the reporting year => retained annual ratio is 3 / 1.
let mixed=regionStack([stackFor(9,9,100,3),stackFor(9,13,100,3),stackFor(9,13,100,3),stackFor(9,13,0,3),stackFor(9,13,0,3)]);
f=runStack(mixed);assert.strictEqual(f.ba_status,'ADMITTED');assert.strictEqual(f.modis_burned_frac_union,0.6);assert.strictEqual(f.modis_burned_frac_annual,3);
let corrupt=regionStack([stackFor(9,9,100,3),stackFor(9,9,0,3)]);
corrupt.b.union=mk([2,1],[true,true]);f=runStack(corrupt);
assert.strictEqual(f.ba_status,'ACCOUNTING_INCONSISTENCY');assert.strictEqual(f.modis_ba_km2,null);
const originalPixelArea=img.pixelArea;
img.pixelArea=()=>new I({area:mk(1000000,false)});
f=runStack(good);assert.strictEqual(f.ba_status,'REDUCTION_INCOMPLETE');assert.strictEqual(f.modis_ba_km2,null);
img.pixelArea=originalPixelArea;
// Fault injection after executing actual stacked-mask reduction tests absent and
// null dictionary keys independently from the masked-sum-zero behavior.
reducerMutation=o=>{delete o.union;return o;};f=runStack(good);assert.strictEqual(f.ba_status,'REDUCTION_INCOMPLETE');assert.strictEqual(f.modis_ba_km2,null);
reducerMutation=o=>{o.union=null;return o;};f=runStack(good);assert.strictEqual(f.ba_status,'REDUCTION_INCOMPLETE');
reducerMutation=o=>{delete o.c3_grid_centres;return o;};f=runStack(good);assert.strictEqual(f.ba_status,'EMPTY_REDUCTION_UNRESOLVED');
reducerMutation=o=>{o.c3_grid_centres=0;return o;};f=runStack(good);assert.strictEqual(f.ba_status,'REDUCTION_INCOMPLETE');
reducerMutation=o=>{o.c3_grid_centres=1.5;return o;};f=runStack(good);assert.strictEqual(f.ba_status,'REDUCTION_INCOMPLETE');
reducerMutation=o=>{o.samples=1;return o;};f=runStack(good);assert.strictEqual(f.ba_status,'ACCOUNTING_INCONSISTENCY');
reducerMutation=o=>({});f=runStack(good);assert.strictEqual(f.ba_status,'EMPTY_REDUCTION_UNRESOLVED');reducerMutation=null;
let emptyUnit=new F(unit.p,{area:()=>new N(0),noCentres:true});f=runStack(good,emptyUnit);
assert.strictEqual(f.ba_status,'NO_PIXEL_CENTRES');assert.strictEqual(f.modis_ba_km2,null);
console.log('PASS actual c3Row with 2-pixel stack, source-masked and valid-zero evidence');
console.log('PASS all/partial masked derived bands: sum zero yet reduction withheld');
console.log('PASS accounting inconsistency, missing/null keys, empty reference and no-centre cases');
console.log('PASS five-pixel actual stack retains union-over-annual ratio');
