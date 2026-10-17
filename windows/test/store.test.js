import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createState} from '../src/model.js';
import {loadState,saveState} from '../src/store.js';
import {shellOptions} from '../src/sessions.js';

test('saved workspace round-trips and corrupt settings are never overwritten',t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'cligrid-store-'));t.after(()=>fs.rmSync(dir,{recursive:true}));
  const file=path.join(dir,'settings.json'),state=createState();
  state.workspaces[0].name='Coding 日本語';saveState(file,state);
  assert.deepEqual(loadState(file),state);
  fs.writeFileSync(file,'{broken');assert.throws(()=>loadState(file));
  assert.equal(fs.readFileSync(file,'utf8'),'{broken');
  const invalid=structuredClone(state);invalid.workspaces=[];
  assert.throws(()=>saveState(file,invalid));assert.equal(fs.readFileSync(file,'utf8'),'{broken');
});
test('Windows shells use system executables and preserve command arguments',()=>{
  const command='Write-Output "two words"; Get-Location';
  const pane={shell:'powershell',cwd:os.homedir(),command};
  const powershell=shellOptions(pane,'win32');
  assert.match(powershell.file,/System32\\WindowsPowerShell\\v1\.0\\powershell\.exe$/);
  assert.deepEqual(powershell.args,['-NoLogo','-NoExit','-Command',command]);
  const cmd=shellOptions({...pane,shell:'cmd'},'win32');
  assert.deepEqual(cmd.args,['/d','/k',command]);
  assert.throws(()=>shellOptions({...pane,cwd:path.join(os.tmpdir(),'cligrid-missing-dir-'+crypto.randomUUID())}));
});
