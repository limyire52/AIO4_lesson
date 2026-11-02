// Optional Node.js regression tests; the application itself does not require Node.js.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

function harness(){
  const elements=new Map();
  function element(){return {hidden:false,textContent:'',dataset:{},children:[],attributes:{},
    elements:new Proxy({}, {get:(target,key)=>target[key]||(target[key]={value:'',required:false,addEventListener(){}})}),
    listeners:{},addEventListener(type,callback){this.listeners[type]=callback;},reset(){},scrollIntoView(){},focus(){},querySelector(){return null;},querySelectorAll(){return [];},
    append(...items){this.children.push(...items);},replaceChildren(){this.children=[];},
    setAttribute(key,value){this.attributes[key]=value;}};}
  const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},createElement:element};
  const context=vm.createContext({document,console,URLSearchParams,FormData:class {constructor(){return [['q','']];}},fetch(){throw Error('unexpected network');}});
  let source=fs.readFileSync('static/app.js','utf8');
  source=source.slice(0,source.lastIndexOf('run(async()=>{await refreshCSRF();'));
  vm.runInContext(source,context);
  return {context,document,run:code=>vm.runInContext(code,context)};
}

test('Leaving an edited post clears the mutation target and its password requirement',()=>{
  const h=harness();
  h.run("editId='old-post';selected='old-post';$('post-form').elements.password.required=true;closeDetail();");
  assert.equal(h.run('editId'),null);
  assert.equal(h.run('selected'),null);
  assert.equal(h.run("$('post-form').elements.password.required"),false);
});

test('An older search response cannot replace a newer result',async()=>{
  const h=harness();
  h.run("user={id:'u'};var requests=[];api=()=>new Promise(resolve=>requests.push(resolve));var first=loadPosts();var second=loadPosts();");
  h.run("requests[1]({items:[{id:'new',title:'new result'}],page:1,pages:1,total:1});");
  await h.run('second');
  h.run("requests[0]({items:[{id:'old',title:'old result'}],page:2,pages:8,total:80});");
  await h.run('first');
  assert.equal(h.run('page'),1);
  assert.equal(h.run("$('posts').children[0].children[0].children[0].textContent"),'new result');
  assert.equal(h.run("$('post-count').textContent"),'1');
});

test('Leaving admin invalidates an in-flight report and clears private report data',async()=>{
  const h=harness();
  h.run("user={id:'a',role:'ADMIN'};$('reports-panel').hidden=false;api=()=>new Promise(resolve=>{globalThis.resolveReport=resolve;});var pending=openReport('r');user=null;navigation();");
  h.run("resolveReport({id:'r',post_id:'p',target_content:'private',reason:'private',status:'RECEIVED'});");
  await h.run('pending');
  assert.equal(h.run("$('report-detail').hidden"),true);
  assert.equal(h.run("$('report-target').textContent"),'');
});

test('A disabled final-page next button remains disabled after action completion',async()=>{
  const h=harness();
  h.run("page=3;pages=3;var next=$('next');next.id='next';");
  await h.run('run(async()=>{},next)');
  assert.equal(h.run('next.disabled'),true);
});

test('A form disables the submitter and rejects a second submission while pending',async()=>{
  const h=harness();
  h.run("var calls=0;form('new-form',()=>{calls++;return new Promise(resolve=>{globalThis.finishSubmit=resolve;});});var target=$('new-form');var submit=$('save');var event={target,submitter:submit,preventDefault(){}};var submission=target.listeners.submit(event);");
  assert.equal(h.run('submit.disabled'),true);
  await h.run('target.listeners.submit(event)');
  assert.equal(h.run('calls'),1);
  h.run('finishSubmit();');
  await h.run('submission');
  assert.equal(h.run('submit.disabled'),false);
  assert.equal(h.run('target.dataset.busy'),'false');
});
