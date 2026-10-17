import {activeWorkspace,layoutCells,SHAPES,THEMES} from './model.js';
import {PaneView} from './pane.js';
import {element,button,field,openDialog,finishForm,showToast,report} from './dialogs.js';

const api=window.cligrid, $=selector=>document.querySelector(selector), views=new Map();
let state,focused,zoomed=null,applying=false;
const workspace=()=>activeWorkspace(state);
const current=()=>views.get(focused);
async function action(value) { await api.action(value); }
function focus(id,terminal=true) {
  if(!views.has(id))return;
  focused=id;
  for(const [key,view] of views)view.card.classList.toggle('focused',key===id);
  for(const b of $('#switcher').children){b.setAttribute('aria-current',b.dataset.id===id);if(b.dataset.id===id)b.classList.remove('attention');}
  views.get(id).card.classList.remove('attention');
  if(terminal)views.get(id).focus();
}
function zoom(id=focused) {zoomed=zoomed===id?null:id;layout();focus(id);}
function layout() {
  if(!state)return;
  const w=workspace(),ids=new Set(w.panes.map(p=>p.id)),cells=layoutCells(w.panes.length,w.layout);
  const rows=Math.max(...cells.map(c=>c.row+c.height));
  const visible=zoomed?1:Math.min(rows,w.layout==='master'?2:SHAPES[w.layout][1]);
  const height=Math.max(160,Math.floor(($('#grid').clientHeight-28-(visible-1)*10)/visible));
  $('#grid').style.gridAutoRows=`${height}px`;
  for(const [id,view] of views)view.card.hidden=!ids.has(id) || Boolean(zoomed && zoomed!==id);
  cells.forEach(cell=>{
    const view=views.get(w.panes[cell.index].id);if(!view)return;
    view.card.style.gridColumn=zoomed?'1 / span 12':`${cell.col+1} / span ${cell.width}`;
    view.card.style.gridRow=zoomed?'1':`${cell.row+1} / span ${cell.height}`;
    view.scheduleFit();
  });
  $('#zoom').textContent=zoomed?'Show grid':'Zoom';
}
function render(next) {
  state=next;const w=workspace();
  const all=new Set(state.workspaces.flatMap(ws=>ws.panes.map(p=>p.id)));
  for(const [id,view] of views)if(!all.has(id)){view.dispose();views.delete(id);}
  if(!w.panes.some(p=>p.id===focused)){focused=w.panes[0].id;zoomed=null;}
  if(zoomed && !w.panes.some(p=>p.id===zoomed))zoomed=null;
  const theme=THEMES[state.settings.theme];
  document.documentElement.style.setProperty('--bg',theme.background);
  document.documentElement.style.setProperty('--text',theme.foreground);
  document.documentElement.style.setProperty('--accent',theme.cursor);
  $('#workspace').replaceChildren(...state.workspaces.map(ws=>{const o=element('option',ws.name);o.value=ws.id;return o;}));
  $('#workspace').value=w.id;$('#layout').value=w.layout;$('#add').disabled=w.panes.length>=20;
  $('#switcher').replaceChildren();
  w.panes.forEach((pane,index)=>{
    let view=views.get(pane.id);
    if(!view){
      view=new PaneView(pane,state.settings,{focus,zoom,menu:paneMenu,shortcut,attention:id=>{
        const b=Array.from($('#switcher').children).find(b=>b.dataset.id===id);b?.classList.add('attention');
      },swap:(a,b)=>{if(workspace().panes.some(p=>p.id===a))report(action({type:'pane-swap',a,b}));}});
      views.set(pane.id,view);report(view.start());
    }
    view.update(pane,state.settings,index);
    const b=button(String(index+1),()=>{if(zoomed)zoomed=pane.id;layout();focus(pane.id);view.card.scrollIntoView({block:'nearest'});});
    b.dataset.id=pane.id;b.title=pane.name;b.setAttribute('aria-label',`Focus ${pane.name}`);
    b.style.setProperty('--pane-color',view.card.style.getPropertyValue('--pane-color'));
    b.classList.toggle('attention',view.card.classList.contains('attention'));$('#switcher').append(b);
  });
  $('#status').textContent=`${w.panes.length} terminals · ${w.name} · Closing the window keeps terminals running`;
  layout();focus(focused,false);
}
function paneMenu(id) {
  focus(id,false);const p=workspace().panes.find(p=>p.id===id),ctx=openDialog(p.name);
  const items=[['Zoom / show grid',()=>zoom(id)],['Find in terminal…',searchDialog],['Copy selection',()=>report(current().copy())],['Paste',()=>report(current().paste())],['Edit name, command and folder…',()=>editPane(p)],['Restart terminal…',()=>report(current().restart())],['Remove terminal…',()=>report(action({type:'pane-remove',id}))]];
  for(const [label,run] of items)ctx.body.append(button(label,()=>{ctx.close();run();}));
  ctx.actions.append(button('Close',ctx.close));
}
function editPane(pane) {
  const ctx=openDialog('Edit terminal');
  const name=field(ctx.body,'Name',pane.name);name.maxLength=80;name.required=true;
  const shell=field(ctx.body,'Shell',pane.shell,'select',[['powershell','Windows PowerShell'],['cmd','Command Prompt']]);
  const cwd=field(ctx.body,'Starting folder (empty = home)',pane.cwd);
  ctx.body.append(button('Choose folder…',()=>report(api.folder().then(path=>{if(path)cwd.value=path;}))));
  const command=field(ctx.body,'Startup command (optional)',pane.command,'textarea');command.maxLength=8192;
  ctx.body.append(element('p','Shell, folder and command changes take effect when you restart this terminal.'));
  finishForm(ctx,()=>action({type:'pane-edit',id:pane.id,values:{name:name.value,shell:shell.value,cwd:cwd.value,command:command.value}}));
}
function settingsDialog() {
  const ctx=openDialog('Settings'),s=state.settings;
  const theme=field(ctx.body,'Theme',s.theme,'select',Object.keys(THEMES).map(k=>[k,k]));
  const font=field(ctx.body,'Font family',s.font);font.maxLength=100;
  const size=field(ctx.body,'Font size',s.fontSize,'number');size.min=8;size.max=32;
  const scroll=field(ctx.body,'Scrollback lines',s.scrollback,'number');scroll.min=100;scroll.max=100000;
  const blink=field(ctx.body,'Blink cursor',s.cursorBlink,'checkbox');
  const notify=field(ctx.body,'Desktop notifications for terminal bells',s.notifications,'checkbox');
  finishForm(ctx,()=>action({type:'settings',values:{theme:theme.value,font:font.value,fontSize:Number(size.value),scrollback:Number(scroll.value),cursorBlink:blink.checked,notifications:notify.checked}}));
}
function textDialog(title,label,value,save) {
  const ctx=openDialog(title),input=field(ctx.body,label,value);input.required=true;input.maxLength=80;finishForm(ctx,()=>save(input.value));
}
function workspaceDialog() {
  const ctx=openDialog('Workspaces');
  ctx.body.append(element('p','Switching workspaces keeps their terminal processes running. Up to 20 panes per workspace and 60 active terminals in total.'));
  ctx.body.append(button('New workspace…',()=>{ctx.close();textDialog('New workspace','Name','',name=>action({type:'workspace-add',name}));}),
    button('Rename current workspace…',()=>{ctx.close();textDialog('Rename workspace','Name',workspace().name,name=>action({type:'workspace-rename',name}));}),
    button('Remove current workspace…',()=>{ctx.close();report(action({type:'workspace-remove'}));}));
  ctx.actions.append(button('Close',ctx.close));
}
function searchDialog() {
  const view=current(),ctx=openDialog(`Find in ${workspace().panes.find(p=>p.id===focused).name}`);
  const query=field(ctx.body,'Search text','','search');
  const result=element('p','Search the terminal scrollback.');ctx.body.append(result);
  const find=reverse=>{const found=view.search[reverse?'findPrevious':'findNext'](query.value);result.textContent=found?'Match found':'No match';};
  ctx.actions.append(button('Previous',()=>find(true)),button('Next',()=>find(false)),button('Close',ctx.close));
  $('#dialog-form').onsubmit=e=>{e.preventDefault();find(false);};query.focus();
}
function broadcastDialog() {
  const ctx=openDialog('Send command to all terminals'),command=field(ctx.body,'Command','');command.required=true;command.maxLength=8192;
  ctx.body.append(element('p','This types the command and presses Enter in every pane of the current workspace. Ensure each pane is ready for the command.'));
  finishForm(ctx,async()=>{if(await api.broadcast(command.value))showToast('Command sent');},'Review command');
}
function paletteDialog() {
  const ctx=openDialog('Commands'),input=field(ctx.body,'Find an action, pane or workspace','','search'),list=element('div',undefined,'action-list');ctx.body.append(list);
  const entries=[['Add terminal',()=>action({type:'pane-add'})],['Zoom focused terminal',()=>zoom()],['Find in terminal',searchDialog],['Settings',settingsDialog],['Manage workspaces',workspaceDialog],['Send command to all',broadcastDialog],['Keyboard shortcuts',shortcutsDialog],['Hide to tray',()=>api.hide()],['Exit and stop terminals',()=>api.quit()],
    ...workspace().panes.map(p=>[`Focus: ${p.name}`,()=>focus(p.id)]),
    ...state.workspaces.map(w=>[`Workspace: ${w.name}`,()=>action({type:'workspace-switch',id:w.id})]),
    ...Object.keys(SHAPES).map(value=>[`Layout: ${value}`,()=>action({type:'layout',value})])];
  let selected=0,buttons=[];
  const paint=()=>buttons.forEach((b,i)=>b.classList.toggle('selected',i===selected));
  const filter=()=>{
    selected=0;buttons=[];list.replaceChildren();const q=input.value.toLowerCase();
    for(const [label,run] of entries)if(label.toLowerCase().includes(q)){
      const b=button(label,()=>{ctx.close();report(run());});buttons.push(b);list.append(b);
    }
    if(!buttons.length)list.append(element('p','No matching commands'));paint();
  };
  input.addEventListener('input',filter);
  input.addEventListener('keydown',e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();selected=Math.max(0,Math.min(buttons.length-1,selected+(e.key==='ArrowDown'?1:-1)));paint();buttons[selected]?.scrollIntoView({block:'nearest'});}});
  $('#dialog-form').onsubmit=e=>{e.preventDefault();buttons[selected]?.click();};
  ctx.actions.append(button('Close',ctx.close));filter();input.focus();
}
function shortcutsDialog() {
  const ctx=openDialog('Keyboard shortcuts');ctx.body.append(element('p','Ctrl+Shift+1…9 / 0 — focus terminal 1…10\nCtrl+Shift+Arrow — move between terminals\nCtrl+Shift+Z — zoom / show grid\nCtrl+Shift+T — new terminal\nCtrl+Shift+P — commands\nCtrl+Shift+G — find\nCtrl+Shift+E — send command to all\nCtrl+Shift+R — restart focused terminal\nCtrl+Shift+, — settings\nCtrl+Shift+W — hide to tray\nCtrl+Shift+C / V — copy / paste\nDrag a pane header onto another to swap them.'));ctx.actions.append(button('Close',ctx.close));
}
function shortcut(event) {
  if(!state || $('#dialog').open || !event.ctrlKey || !event.shiftKey || event.altKey)return false;
  const key=({Comma:',',Slash:'/'}[event.code] || event.key).toLowerCase(),w=workspace();let fn;
  const digit=/^Digit([0-9])$/.exec(event.code)?.[1];
  if(digit)fn=()=>{const p=w.panes[digit==='0'?9:Number(digit)-1];if(p){if(zoomed)zoomed=p.id;layout();focus(p.id);views.get(p.id).card.scrollIntoView({block:'nearest'});}};
  const actions={z:()=>zoom(),t:()=>action({type:'pane-add'}),p:paletteDialog,g:searchDialog,e:broadcastDialog,r:()=>current().restart(),',':settingsDialog,w:()=>api.hide(),q:()=>api.quit(),'/':shortcutsDialog};
  fn ||= actions[key];
  if(key.startsWith('arrow'))fn=()=>{
    const cells=layoutCells(w.panes.length,w.layout),cell=cells[w.panes.findIndex(p=>p.id===focused)];
    let x=cell.col+cell.width/2,y=cell.row+cell.height/2;
    if(key==='arrowleft')x=cell.col-.5;if(key==='arrowright')x=cell.col+cell.width;
    if(key==='arrowup')y=cell.row-.5;if(key==='arrowdown')y=cell.row+cell.height;
    const next=cells.find(c=>c.col<=x&&c.col+c.width>x&&c.row<=y&&c.row+c.height>y);
    if(next){const id=w.panes[next.index].id;if(zoomed)zoomed=id;layout();focus(id);views.get(id).card.scrollIntoView({block:'nearest'});}
  };
  if(!fn)return false;event.preventDefault();event.stopPropagation();report(fn());return true;
}
async function start() {
  if(!api)throw new Error('Open this application with its desktop launcher.');
  for(const name of Object.keys(SHAPES)){const o=element('option',name==='auto'?'Auto layout':name);o.value=name;$('#layout').append(o);}
  api.onTerminal(event=>views.get(event.id)?.receive(event));
  api.onState(next=>{applying=true;render(next);applying=false;});
  api.onFocus(id=>{const w=state.workspaces.find(w=>w.panes.some(p=>p.id===id));if(w)report(action({type:'workspace-switch',id:w.id}).then(()=>focus(id)));});
  render(await api.state());
  $('#workspace').onchange=()=>report(action({type:'workspace-switch',id:$('#workspace').value}));
  $('#layout').onchange=()=>{if(!applying)report(action({type:'layout',value:$('#layout').value}));};
  const handlers={add:()=>action({type:'pane-add'}),zoom:()=>zoom(),palette:paletteDialog,settings:settingsDialog,workspaces:workspaceDialog,broadcast:broadcastDialog,hide:()=>api.hide()};
  for(const [id,fn] of Object.entries(handlers))$('#'+id).onclick=()=>report(fn());
  document.addEventListener('keydown',event=>{if(!event.target.closest('.xterm'))shortcut(event);});
  new ResizeObserver(layout).observe($('#grid'));
  current().focus();
}
report(start());
