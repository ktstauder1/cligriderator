import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Sessions } from '../src/sessions.js';
import { newPane } from '../src/model.js';

function fakePty() {
  const children=[];
  return {children, spawn(file,args,options) {
    const c={file,args,options,writes:[],killed:false,pause(){this.paused=true;},resume(){this.paused=false;},write(s){this.writes.push(s);},resize(c,r){this.size=[c,r];},kill(){this.killed=true;queueMicrotask(()=>this.exit({exitCode:0}));},onData(fn){this.data=fn;},onExit(fn){this.exit=fn;}};
    children.push(c); return c;
  }};
}
test('reopening keeps the process, removal kills it, stale events cannot overwrite restart', async () => {
  const pty=fakePty(), events=[], sessions=new Sessions(pty, e=>events.push(e));
  const pane=newPane();
  sessions.open(pane); sessions.open(pane); assert.equal(pty.children.length,1);
  pty.children[0].data('hello'); assert.equal(sessions.open(pane).buffer,'hello');
  await sessions.restart(pane); assert.equal(pty.children[0].killed,true);
  pty.children[0].exit({exitCode:9}); assert.equal(sessions.open(pane).exitCode,null);
  await sessions.retain(new Set()); assert.equal(pty.children[1].killed,true);
  assert.equal(sessions.items.size,0);
});
test('slow renderers pause output; acknowledgements from old processes cannot resume replacements',async()=>{
  const pty=fakePty(),sessions=new Sessions(pty,()=>{}),pane=newPane();
  const first=sessions.open(pane);pty.children[0].data('x'.repeat(128*1024));
  assert.equal(pty.children[0].paused,true);
  sessions.acknowledge(pane.id,first.generation,1);assert.equal(pty.children[0].paused,false);
  const second=await sessions.restart(pane);pty.children[1].data('y'.repeat(128*1024));
  sessions.acknowledge(pane.id,first.generation,999);assert.equal(pty.children[1].paused,true);
  sessions.acknowledge(pane.id,second.generation,1);assert.equal(pty.children[1].paused,false);
  assert.throws(()=>sessions.acknowledge(pane.id,second.generation,NaN));
});
test('shutdown waits for native process exit before resolving',async()=>{
  const pty=fakePty(),sessions=new Sessions(pty,()=>{}),pane=newPane();sessions.open(pane);
  pty.children[0].kill=function(){this.killed=true;};
  let done=false;const stopping=sessions.dispose().then(()=>done=true);
  await Promise.resolve();assert.equal(done,false);
  pty.children[0].exit({exitCode:0});await stopping;assert.equal(done,true);
});
test('output is bounded and terminal input and sizes are validated', () => {
  const pty=fakePty(), sessions=new Sessions(pty,()=>{}), pane=newPane();
  sessions.open(pane); pty.children[0].data('x'.repeat(2*1024*1024));
  assert.ok(sessions.open(pane).buffer.length <= 256*1024);
  assert.throws(()=>sessions.write(pane.id,'x'.repeat(70000)));
  assert.throws(()=>sessions.resize(pane.id,NaN,20));
  sessions.resize(pane.id,80,24); assert.deepEqual(pty.children[0].size,[80,24]);
  sessions.write(pane.id,'hello\r'); assert.deepEqual(pty.children[0].writes,['hello\r']);
  pty.children[0].exit({exitCode:1}); assert.throws(()=>sessions.write(pane.id,'bad'));
});
