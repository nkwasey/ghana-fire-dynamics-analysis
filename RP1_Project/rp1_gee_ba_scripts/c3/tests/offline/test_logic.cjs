'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const base=path.resolve(__dirname,'../..');
const ctx={console}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(base,'src/scientific_logic.js'),'utf8'),ctx);
const O={and:(a,b)=>a&&b,or:(a,b)=>a||b,not:a=>!a};
const defaults={qaAvailable:true,burnAvailable:true,land:true,valid:true,shortened:false,special:false,positive:false,zero:true,outOfRange:false};
const names=['qa_missing','burndate_missing','unsupported','explicit_zero','accepted'];
function c(overrides){return ctx.c3ClassifyEvidence(O,Object.assign({},defaults,overrides));}
function state(out){return names.filter(k=>out[k]);}
function check(overrides,expected){assert.deepStrictEqual(state(c(overrides)),[expected]);}
check({positive:true,zero:false},'accepted');
let short=c({positive:true,zero:false,shortened:true}); assert.deepStrictEqual(state(short),['accepted']);assert(short.flag_shortened);
let contradiction=c({positive:true,zero:false,special:true}); assert(contradiction.unsupported && contradiction.anomaly && contradiction.flag_positive_special);
let outOfRange=c({positive:true,zero:false,outOfRange:true}); assert(outOfRange.unsupported && outOfRange.anomaly && outOfRange.flag_unexpected_burndate);
check({},'explicit_zero');
check({burnAvailable:false},'burndate_missing');
let both=c({qaAvailable:false,burnAvailable:false});assert.deepStrictEqual(state(both),['qa_missing']);assert(both.flag_qa_missing&&both.flag_burndate_masked);
check({valid:false},'unsupported');check({land:false},'unsupported');check({special:true},'unsupported');
check({positive:false,zero:false},'unsupported');
let combinations=0;
for(let mask=0;mask<256;mask++){
 const bits=Array.from({length:8},(_,i)=>Boolean(mask&(1<<i)));
 const [qaAvailable,burnAvailable,land,valid,shortened,special,positive,zero]=bits;
 if(positive&&zero) continue;
 const p={qaAvailable,burnAvailable,land,valid,shortened,special,positive,zero,outOfRange:false};
 const r=ctx.c3ClassifyEvidence(O,p), active=state(r);
 assert.strictEqual(active.length,1,'state partition '+JSON.stringify(p));
 assert.strictEqual(r.accepted,qaAvailable&&burnAvailable&&land&&valid&&positive&&!special);
 assert.strictEqual(r.anomaly,qaAvailable&&burnAvailable&&positive&&special);
 assert.strictEqual(r.explicit_zero,qaAvailable&&burnAvailable&&land&&valid&&zero&&!special);
 assert.strictEqual(r.flag_positive_special,qaAvailable&&burnAvailable&&positive&&special);
 combinations++;
}
let d=ctx.c3DomainLogic(O,[{eligible:false,unknown:true},{eligible:true,unknown:false}]);
assert(d.eligible&&!d.unresolved&&!d.excluded&&d.any_unknown_year);
d=ctx.c3DomainLogic(O,[{eligible:false,unknown:true},{eligible:false,unknown:false}]);assert(d.unresolved&&!d.eligible&&!d.excluded);
d=ctx.c3DomainLogic(O,[{eligible:false,unknown:false},{eligible:false,unknown:false}]);assert(d.excluded&&!d.eligible&&!d.unresolved);
const options=[{eligible:true,unknown:false},{eligible:false,unknown:false},{eligible:false,unknown:true}];
let domainCases=0;
for(const a of options)for(const b of options)for(const z of options){
 let result=ctx.c3DomainLogic(O,[a,b,z]);
 assert.strictEqual([result.eligible,result.unresolved,result.excluded].filter(Boolean).length,1);
 if(ctx.c3DomainLogic(O,[b,z]).eligible) assert(result.eligible,'shorter union must be subset');
 domainCases++;
}
assert.deepStrictEqual(Array.from(ctx.c3Admission([0,1,2,4])),['MISSING','ADMITTED','AMBIGUOUS_MULTIPLE','AMBIGUOUS_MULTIPLE']);
console.log(`PASS synthetic evidence: ${combinations} admissible Boolean cases, five exclusive states and overlapping flags`);
console.log(`PASS synthetic domain: ${domainCases} annual combinations, precedence and nested-period subset`);
console.log('PASS source admission: missing, exact-one and ambiguous multiple');
