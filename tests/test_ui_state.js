const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

function harness(){
  const elements=new Map();
  const context=vm.createContext({console,structuredClone,window:{addEventListener(){}},document:{getElementById(id){if(!elements.has(id))elements.set(id,{});return elements.get(id);}}});
  const source=fs.readFileSync(path.join(__dirname,'../openarch/static/app.js'),'utf8').replace('init().catch(error);','');
  vm.runInContext(source,context);
  vm.runInContext("render=()=>{};progress=()=>{};projectList=async()=>{};error=()=>{};",context);
  return {context,run:code=>vm.runInContext(code,context)};
}

test('out-of-order project loads cannot return to an older selection',async()=>{
  const h=harness();h.run("var pending={};api=url=>new Promise(resolve=>pending[url]=resolve);var first=openProject('a');var second=openProject('b');");
  h.run("pending['/api/projects/b']({id:'b'});");await h.run('second');
  h.run("pending['/api/projects/a']({id:'a'});");await h.run('first');
  assert.equal(h.run('project.id'),'b');
});

test('a stale poll cannot overwrite a newly saved revision',async()=>{
  const h=harness();h.run("project={id:'a',revision:1,pages:[],runs:[]};var resolvePoll;api=()=>new Promise(resolve=>resolvePoll=resolve);var pendingPoll=pollProject();project={id:'a',revision:2,pages:[],runs:[]};resolvePoll({id:'a',revision:1,pages:[],runs:[]});");
  await h.run('pendingPoll');assert.equal(h.run('project.revision'),2);
});

test('polling preserves dirty edits and the stale revision for conflict detection',async()=>{
  const h=harness();h.run("project={id:'a',revision:1,pages:[],runs:[]};markDirty();api=async()=>({id:'a',revision:2,pages:[],runs:[]});");
  await h.run('pollProject()');assert.equal(h.run('project.revision'),1);assert.equal(h.run('dirty'),true);
});

test('project selection resets cloud consent',async()=>{
  const h=harness();h.run("$('cloud-consent').checked=true;api=async()=>({id:'b'});");
  await h.run("openProject('b')");assert.equal(h.run("$('cloud-consent').checked"),false);
});

test('saving review collects dimensions and opening edits together',()=>{
  const h=harness();h.run(`
    project={spec:{width:{value_mm:10000},levels:[],openings:[{id:'door',x_mm:1000}]}};
    $('measures').children=[{dataset:{measure:'width'}}];$('levels').children=[];
    readMeasure=()=>({value_mm:12000});readOpenings=()=>[{id:'door',x_mm:1500}];
    var reviewed=readReviewSpec();
  `);
  assert.equal(h.run('reviewed.width.value_mm'),12000);
  assert.equal(h.run('reviewed.openings[0].x_mm'),1500);
  assert.equal(h.run('project.spec.width.value_mm'),10000);
});

test('advanced JSON and form edits cannot silently replace one another',()=>{
  const h=harness();h.run("markDirty('json');");
  assert.throws(()=>h.run("requireEditor('form')"));
  h.run("clearDirty();markDirty('form');");
  assert.throws(()=>h.run("requireEditor('json')"));
  h.run("clearDirty();requireEditor('json');");
});

test('an action freezes editor inputs until its response is handled',async()=>{
  const h=harness();h.run("var finish;var action=guard(()=>new Promise(resolve=>finish=resolve))();");
  assert.equal(h.run("$('workspace').inert"),true);
  h.run('finish();');await h.run('action');
  assert.equal(h.run("$('workspace').inert"),false);
});
