// Executed by the installed/packaged application, with an isolated userData directory.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

async function until(check, label) {
  const deadline=Date.now()+30000;
  while(Date.now()<deadline){if(await check())return;await delay(100);}
  throw new Error(`Timed out: ${label}`);
}
export async function runSmoke({win,sessions,state}) {
  win.show();
  await until(()=>win.webContents.executeJavaScript("document.querySelectorAll('.pane').length === 6"),'six rendered panes');
  await until(()=>sessions.items.size===6,'six shell processes');
  const pane=state.workspaces[0].panes[0],id=JSON.stringify(pane.id);
  const command=process.platform==='win32'?"[Console]::WriteLine('CLIGRID_' + 'SMOKE_OK')\r":"printf 'CLIGRID_%s\\n' 'SMOKE_OK'\r";
  await win.webContents.executeJavaScript(`window.cligrid.input(${id},${JSON.stringify(command)})`);
  await until(()=>sessions.items.get(pane.id).buffer.includes('CLIGRID_SMOKE_OK'),'shell executes keyboard input');
  await until(()=>win.webContents.executeJavaScript("document.querySelector('.pane .xterm-accessibility-tree')?.textContent.includes('CLIGRID_SMOKE_OK')"),'terminal visibly renders shell output');
  await win.webContents.executeJavaScript(`window.cligrid.resize(${id},100,32)`);
  assert.equal(sessions.items.get(pane.id).child.cols,100);
  assert.equal(sessions.items.get(pane.id).child.rows,32);
  const same=sessions.items.get(pane.id).child;
  win.hide();await delay(100);assert.equal(sessions.items.get(pane.id).child,same);win.show();
  assert.equal(await win.webContents.executeJavaScript("typeof require"),'undefined');
  assert.equal(await win.webContents.executeJavaScript("window.cligrid.input('unknown','x').then(()=>false,()=>true)"),true);
  const output=process.env.CLIGRID_SMOKE_DIR || path.join(process.cwd(),'test-results','runtime');
  fs.mkdirSync(output,{recursive:true});
  await win.webContents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  fs.writeFileSync(path.join(output,'window.png'),(await win.webContents.capturePage()).toPNG());
  fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({passed:true,platform:process.platform,arch:process.arch,checks:['six rendered panes','six real shells','renderer → IPC → PTY command output','visible terminal output','resize','hide preserves shell','renderer isolation','unknown terminal rejected']},null,2));
  console.log('CLIGRID_RUNTIME_SMOKE_OK');
}
