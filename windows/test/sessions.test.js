import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Sessions } from '../src/sessions.js';
import { newPane } from '../src/model.js';

function fakePty() {
  const children=[];
  return {children, spawn(file,args,options) {
    const c={file,args,options,writes:[],killed:false,write(s){this.writes.push(s);},resize(c,r){this.size=[c,r];},kill(){this.killed=true;},onData(fn){this.data=fn;},onExit(fn){this.exit=fn;}};
    children.push(c); return c;
  }};
}
test('reopening keeps the process, removal kills it, stale events cannot overwrite restart', () => {
  const pty=fakePty(), events=[], sessions=new Sessions(pty, e=>events.push(e));
  const pane=newPane();
  sessions.open(pane); sessions.open(pane); assert.equal(pty.children.length,1);
  pty.children[0].data('hello'); assert.equal(sessions.open(pane).buffer,'hello');
  sessions.restart(pane); assert.equal(pty.children[0].killed,true);
  pty.children[0].exit({exitCode:9}); assert.equal(sessions.open(pane).exitCode,null);
  sessions.retain(new Set()); assert.equal(pty.children[1].killed,true);
  assert.equal(sessions.items.size,0);
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
