import path from 'node:path';
import os from 'node:os';
import fs from 'node:fs';

export function shellOptions(pane, platform=process.platform) {
  const cwd=pane.cwd || os.homedir();
  if (!fs.statSync(cwd).isDirectory()) throw new Error('Choose an existing working directory');
  const root=process.env.SystemRoot || 'C:\\Windows';
  if (platform==='win32') return {
    file:pane.shell==='cmd' ? path.win32.join(root,'System32','cmd.exe') : path.win32.join(root,'System32','WindowsPowerShell','v1.0','powershell.exe'),
    args:pane.shell==='cmd' ? ['/d',...(pane.command?['/k',pane.command]:[])] : ['-NoLogo',...(pane.command?['-NoExit','-Command',pane.command]:[])], cwd
  };
  // Enables real runtime tests on the development host; Windows uses ConPTY above.
  return {file:'/bin/bash',args:pane.command?['-lc',pane.command]:['--noprofile','--norc'],cwd};
}
export class Sessions {
  constructor(pty, emit) { this.pty=pty; this.emit=emit; this.items=new Map(); }
  open(pane) {
    if (!this.items.has(pane.id)) {
      if (this.items.size>=60) throw new Error('60 active terminals reached. Close a workspace first.');
      const {file,args,cwd}=shellOptions(pane);
      const env={...process.env,TERM:'xterm-256color',COLORTERM:'truecolor',CLIGRID:'1'};
      delete env.ELECTRON_RUN_AS_NODE; delete env.NODE_OPTIONS;
      const child=this.pty.spawn(file,args,{name:'xterm-256color',cols:80,rows:24,cwd,env,useConpty:true});
      const item={child,buffer:'',seq:0,exitCode:null}; this.items.set(pane.id,item);
      child.onData(data=>{
        if (this.items.get(pane.id)!==item) return;
        item.buffer=(item.buffer+data).slice(-256*1024); item.seq++;
        this.emit({id:pane.id,type:'data',data,seq:item.seq});
      });
      child.onExit(({exitCode})=>{
        if (this.items.get(pane.id)!==item) return;
        item.exitCode=exitCode; item.seq++;
        this.emit({id:pane.id,type:'exit',exitCode,seq:item.seq});
      });
    }
    const {buffer,seq,exitCode}=this.items.get(pane.id); return {buffer,seq,exitCode};
  }
  alive(id) {
    const item=this.items.get(id);
    if (!item || item.exitCode!==null) throw new Error('Terminal has stopped. Use Restart.');
    return item.child;
  }
  write(id,data) {
    if (typeof data!=='string' || data.length>65536) throw new Error('Input is too large');
    this.alive(id).write(data);
  }
  resize(id,cols,rows) {
    if (![cols,rows].every(n=>Number.isInteger(n)&&n>=1&&n<=1000)) throw new Error('Invalid terminal size');
    this.alive(id).resize(cols,rows);
  }
  stop(id) {
    const item=this.items.get(id); this.items.delete(id);
    if (item && item.exitCode===null) item.child.kill();
  }
  restart(pane) { this.stop(pane.id); return this.open(pane); }
  retain(ids) { for (const id of this.items.keys()) if (!ids.has(id)) this.stop(id); }
  dispose() { this.retain(new Set()); }
}
