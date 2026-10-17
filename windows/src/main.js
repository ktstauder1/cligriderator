import { app, BrowserWindow, ipcMain, protocol, net, Menu, Tray, dialog, clipboard, shell, Notification } from 'electron';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { loadState, saveState } from './store.js';
import { activeWorkspace, changeState } from './model.js';
import { Sessions } from './sessions.js';

const require=createRequire(import.meta.url), pty=require('node-pty');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const smoke=process.argv.includes('--smoke-test');
if (smoke) app.setPath('userData',fs.mkdtempSync(path.join(os.tmpdir(),'cligrid-smoke-')));
app.setAppUserModelId('com.konatus.cligriderator');
protocol.registerSchemesAsPrivileged([{scheme:'cligrid',privileges:{standard:true,secure:true,supportFetchAPI:true}}]);
let win, tray, state, sessions, quitting=false;
const settingsFile=path.join(app.getPath('userData'),'settings.json');
const pageUrl='cligrid://app/index.html';
const show=()=>{ if (win.isMinimized()) win.restore(); win.show(); win.focus(); };
const send=(channel,value)=>{ if (win && !win.isDestroyed()) win.webContents.send(channel,value); };
const findPane=id=>{
  const pane=state.workspaces.flatMap(w=>w.panes).find(p=>p.id===id);
  if (!pane) throw new Error('Unknown terminal'); return pane;
};
async function confirm(message, detail) {
  return (await dialog.showMessageBox(win,{type:'warning',message,detail,buttons:['Cancel','Continue'],defaultId:0,cancelId:0,noLink:true})).response===1;
}
async function exit() {
  if (sessions.items.size && !await confirm('Stop all terminals and exit?','Running commands will end. Close the window to keep them running in the system tray.')) return;
  quitting=true; app.quit();
}
function handle(channel, fn) {
  ipcMain.handle(channel,async (event,...args)=>{
    if (event.sender!==win.webContents || event.senderFrame!==win.webContents.mainFrame || event.senderFrame.url!==pageUrl) throw new Error('Untrusted window');
    return fn(...args);
  });
}
function registerApi() {
  handle('state',()=>state);
  handle('action',async action=>{
    if (!action || JSON.stringify(action).length>32768) throw new Error('Invalid action');
    const previous=state;
    const next=changeState(state,action);
    if (['pane-remove','workspace-remove'].includes(action.type) && !await confirm('Remove and stop terminals?','Running commands in the removed panes will end.')) return state;
    if (state!==previous) throw new Error('The workspace changed while confirming. Try again.');
    saveState(settingsFile,next); state=next;
    sessions.retain(new Set(state.workspaces.flatMap(w=>w.panes.map(p=>p.id))));
    send('state-changed',state); return state;
  });
  handle('open',id=>sessions.open(findPane(id)));
  handle('input',(id,data)=>{ findPane(id); sessions.write(id,data); });
  handle('resize',(id,cols,rows)=>{ findPane(id); sessions.resize(id,cols,rows); });
  handle('restart',async id=>{
    const pane=findPane(id);
    if (!await confirm(`Restart ${pane.name}?`,'Any running command in this pane will end.')) return null;
    return sessions.restart(pane);
  });
  handle('broadcast',async command=>{
    if (typeof command!=='string' || !command.trim() || command.length>8192 || /[\r\n\0]/.test(command)) throw new Error('Enter a single command line');
    const panes=activeWorkspace(state).panes;
    if (!await confirm(`Send this command to ${panes.length} panes?`,command)) return false;
    // Check every recipient first; do not silently send to only half a workspace.
    for (const p of panes) sessions.alive(p.id);
    for (const p of panes) sessions.write(p.id,command+'\r');
    return true;
  });
  handle('folder',async ()=>{
    const result=await dialog.showOpenDialog(win,{properties:['openDirectory']});
    return result.canceled?null:result.filePaths[0];
  });
  handle('copy',text=>{ if (typeof text!=='string' || text.length>4*1024*1024) throw new Error('Selection too large'); clipboard.writeText(text); });
  handle('paste',async ()=>{
    const text=clipboard.readText();
    if (text.length>65536) throw new Error('Clipboard is too large (64 KB maximum)');
    if (/[\r\n\x00-\x08\x0b-\x1f\x7f]/.test(text) && !await confirm('Paste multiple lines or control characters?','Pasting may execute commands in the terminal.')) return '';
    return text;
  });
  handle('link',async value=>{
    if (typeof value!=='string' || value.length>8192) throw new Error('Invalid link');
    const url=new URL(value);
    if (!['http:','https:'].includes(url.protocol)) throw new Error('Only web links can be opened');
    if (await confirm('Open this link in your browser?',url.href)) await shell.openExternal(url.href);
  });
  const notified=new Map();
  handle('bell',id=>{
    const pane=findPane(id);
    if (!state.settings.notifications || win.isFocused() || Date.now()-(notified.get(id)||0)<30000) return;
    notified.set(id,Date.now());
    if (Notification.isSupported()) {
      const note=new Notification({title:'Cli Griderator',body:`${pane.name} needs attention`});
      note.on('click',()=>{ show(); send('focus-pane',id); }); note.show();
    }
  });
  handle('hide',()=>win.hide()); handle('quit',exit);
}
async function start() {
  try { state=loadState(settingsFile); }
  catch (error) {
    dialog.showErrorBox('Cannot load Cli Griderator settings',`${error.message}\n\nYour file was left unchanged:\n${settingsFile}`);
    app.exit(1); return;
  }
  protocol.handle('cligrid',request=>{
    const url=new URL(request.url);
    const files={'/index.html':'src/index.html','/renderer.js':'dist/renderer.js','/style.css':'src/style.css','/xterm.css':'dist/xterm.css'};
    if (url.host!=='app' || !Object.hasOwn(files,url.pathname)) return new Response('Not found',{status:404});
    return net.fetch(pathToFileURL(path.join(root,files[url.pathname])).href);
  });
  win=new BrowserWindow({width:1440,height:900,minWidth:720,minHeight:480,show:false,title:'Cli Griderator',backgroundColor:'#15171b',icon:path.join(root,'assets/icon.png'),webPreferences:{preload:path.join(root,'src/preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
  win.webContents.session.setPermissionRequestHandler((_w,_p,done)=>done(false));
  win.webContents.session.setPermissionCheckHandler(()=>false);
  win.webContents.on('will-navigate',event=>event.preventDefault());
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('render-process-gone',()=>{
    dialog.showMessageBox(win,{type:'error',message:'The terminal display stopped.',detail:'The terminal processes are still running. Reopen the display to reconnect.',buttons:['Reopen']}).then(()=>win.loadURL(pageUrl));
  });
  sessions=new Sessions(pty,event=>send('terminal',event));
  registerApi();
  Menu.setApplicationMenu(null);
  if (!smoke) {
    tray=new Tray(path.join(root,'assets/icon.png'));
    tray.setToolTip('Cli Griderator — terminals running');
    tray.setContextMenu(Menu.buildFromTemplate([{label:'Show Cli Griderator',click:show},{type:'separator'},{label:'Exit and stop terminals…',click:exit}]));
    tray.on('double-click',show);
    win.on('close',event=>{ if (!quitting) { event.preventDefault(); win.hide(); } });
    win.once('ready-to-show',()=>{win.maximize();win.show();});
  }
  await win.loadURL(pageUrl);
  if (smoke) {
    const {runSmoke}=await import('./smoke.js');
    let code=0;
    try { await runSmoke({win,sessions,state}); }
    catch (error) { console.error(error); code=1; }
    finally { sessions.dispose(); }
    app.exit(code);
  }
}
if (!smoke && !app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance',()=>{ if (win) show(); });
  app.on('before-quit',()=>{quitting=true;sessions?.dispose();});
  app.on('window-all-closed',()=>{});
  app.whenReady().then(start).catch(error=>{dialog.showErrorBox('Cli Griderator could not start',error.message);app.exit(1);});
}
