const {contextBridge,ipcRenderer}=require('electron');
const listen=(channel,callback)=>{
  const listener=(_event,value)=>callback(value);
  ipcRenderer.on(channel,listener);
  return ()=>ipcRenderer.removeListener(channel,listener);
};
contextBridge.exposeInMainWorld('cligrid',{
  state:()=>ipcRenderer.invoke('state'),
  action:action=>ipcRenderer.invoke('action',action),
  open:id=>ipcRenderer.invoke('open',id),
  input:(id,data)=>ipcRenderer.invoke('input',id,data),
  resize:(id,cols,rows)=>ipcRenderer.invoke('resize',id,cols,rows),
  restart:id=>ipcRenderer.invoke('restart',id),
  broadcast:command=>ipcRenderer.invoke('broadcast',command),
  folder:()=>ipcRenderer.invoke('folder'),
  copy:text=>ipcRenderer.invoke('copy',text),
  paste:()=>ipcRenderer.invoke('paste'),
  link:url=>ipcRenderer.invoke('link',url),
  bell:id=>ipcRenderer.invoke('bell',id),
  hide:()=>ipcRenderer.invoke('hide'),
  quit:()=>ipcRenderer.invoke('quit'),
  onTerminal:callback=>listen('terminal',callback),
  onState:callback=>listen('state-changed',callback),
  onFocus:callback=>listen('focus-pane',callback)
});
