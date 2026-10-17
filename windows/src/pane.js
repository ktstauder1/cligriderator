import {Terminal} from '@xterm/xterm';
import {FitAddon} from '@xterm/addon-fit';
import {SearchAddon} from '@xterm/addon-search';
import {WebLinksAddon} from '@xterm/addon-web-links';
import {THEMES} from './model.js';
import {element,button,report,showToast} from './dialogs.js';

const COLORS=['#8eacd4','#bb9ecb','#8dbfbd','#a6c29a','#d8be86','#d98d91'];
const fontFamily=name=>`"${name.replace(/["\\]/g,'')}", Consolas, "DejaVu Sans Mono", monospace`;
export class PaneView {
  constructor(pane,settings,callbacks) {
    this.id=pane.id;this.callbacks=callbacks;this.api=window.cligrid;this.seq=-1;this.ready=false;this.pending=[];this.exitCode=null;
    this.card=element('section',undefined,'pane');this.card.dataset.id=pane.id;
    const header=element('header',undefined,'pane-header');header.draggable=true;
    this.number=element('span',undefined,'pane-number');
    this.title=element('h2',pane.name,'pane-title');this.title.id=`title-${pane.id}`;this.card.setAttribute('aria-labelledby',this.title.id);
    this.directory=element('span',undefined,'pane-directory');
    this.status=element('span','starting','pane-state');
    const zoom=button('⤢',()=>callbacks.zoom(this.id));zoom.setAttribute('aria-label',`Zoom ${pane.name}`);
    const menu=button('···',()=>callbacks.menu(this.id));menu.setAttribute('aria-label',`Options for ${pane.name}`);
    header.append(this.number,this.title,this.directory,this.status,zoom,menu);
    const host=element('div',undefined,'terminal');this.host=host;
    this.exitBar=element('div',undefined,'exit-bar');this.exitBar.hidden=true;
    this.card.append(header,host,this.exitBar);document.querySelector('#grid').append(this.card);
    this.term=new Terminal({fontFamily:fontFamily(settings.font),fontSize:settings.fontSize,scrollback:settings.scrollback,cursorBlink:settings.cursorBlink,theme:THEMES[settings.theme],allowProposedApi:false,screenReaderMode:true});
    this.fitAddon=new FitAddon();this.search=new SearchAddon();
    this.term.loadAddon(this.fitAddon);this.term.loadAddon(this.search);
    this.term.loadAddon(new WebLinksAddon((event,url)=>{if(event.ctrlKey)report(this.api.link(url));}));
    this.term.open(host);
    this.term.onData(data=>report(this.api.input(this.id,data)));
    this.term.onBell(()=>{if(!this.card.classList.contains('focused'))this.attention();report(this.api.bell(this.id));});
    this.term.onTitleChange(title=>{this.directory.title=title;});
    this.term.attachCustomKeyEventHandler(event=>{
      if(event.type!=='keydown')return true;
      if(event.ctrlKey && !event.altKey && event.key.toLowerCase()==='v'){event.preventDefault();report(this.paste());return false;}
      if(event.ctrlKey && !event.altKey && event.key.toLowerCase()==='c' && (event.shiftKey || this.term.hasSelection())){event.preventDefault();report(this.copy());return false;}
      return !callbacks.shortcut(event);
    });
    host.addEventListener('paste',event=>{event.preventDefault();event.stopImmediatePropagation();report(this.paste());},true);
    this.card.addEventListener('mousedown',()=>callbacks.focus(this.id,false));
    header.addEventListener('dblclick',()=>callbacks.zoom(this.id));
    header.addEventListener('dragstart',event=>event.dataTransfer.setData('text/plain',this.id));
    header.addEventListener('dragover',event=>event.preventDefault());
    header.addEventListener('drop',event=>{event.preventDefault();callbacks.swap(event.dataTransfer.getData('text/plain'),this.id);});
    this.card.addEventListener('contextmenu',event=>{event.preventDefault();callbacks.menu(this.id);});
    this.observer=new ResizeObserver(()=>this.scheduleFit());this.observer.observe(host);
    this.update(pane,settings,0);
  }
  async start() {
    try {
      const snapshot=await this.api.open(this.id);
      this.snapshot(snapshot);this.ready=true;
      for(const event of this.pending)this.receive(event);this.pending=[];
      this.scheduleFit();
    }catch(error){this.showExit(null,error.message);showToast(error.message);}
  }
  snapshot(snapshot) {
    this.term.reset();this.seq=snapshot.seq;this.exitCode=snapshot.exitCode;this.generation=snapshot.generation;
    this.term.write(snapshot.buffer);this.exitBar.hidden=true;this.status.textContent='shell';
    if(snapshot.exitCode!==null)this.showExit(snapshot.exitCode);
  }
  receive(event) {
    if(!this.ready){this.pending.push(event);return;}
    if(event.generation!==this.generation || event.seq<=this.seq)return;this.seq=event.seq;
    if(event.type==='data') {
      this.term.write(event.data,()=>report(this.api.ack(this.id,event.generation,event.seq)));this.status.textContent='output';
      clearTimeout(this.activityTimer);this.activityTimer=setTimeout(()=>{if(this.exitCode===null)this.status.textContent='shell';},1500);
      if(!this.card.classList.contains('focused'))this.attention();
    } else this.showExit(event.exitCode);
  }
  attention(){this.card.classList.add('attention');this.callbacks.attention(this.id);}
  showExit(code,message) {
    this.exitCode=code;this.status.textContent=code===0?'exited':'stopped';this.exitBar.hidden=false;
    this.exitBar.replaceChildren(element('span',message || `Exited with code ${code}`),button('Restart',()=>report(this.restart())));
  }
  async restart() {
    const result=await this.api.restart(this.id);
    if(result){this.snapshot(result);this.ready=true;this.scheduleFit();}
  }
  async copy(){if(this.term.hasSelection())await this.api.copy(this.term.getSelection());}
  async paste(){const text=await this.api.paste();if(text)this.term.paste(text);}
  focus(){this.card.classList.remove('attention');this.term.focus();}
  scheduleFit(){cancelAnimationFrame(this.frame);this.frame=requestAnimationFrame(()=>this.fit());}
  fit() {
    if(this.card.hidden || !this.ready || this.exitCode!==null || !this.host.clientWidth || !this.host.clientHeight)return;
    this.fitAddon.fit();
    // Ignore a resize racing an exit; the exit event supplies the visible status.
    this.api.resize(this.id,this.term.cols,this.term.rows).catch(()=>{});
  }
  update(pane,settings,index) {
    this.title.textContent=pane.name;this.directory.textContent=pane.cwd || '~';this.directory.title=pane.cwd || 'Home directory';
    this.number.textContent=String(index+1).padStart(2,'0');this.card.style.setProperty('--pane-color',COLORS[index%COLORS.length]);
    this.term.options.theme=THEMES[settings.theme];this.term.options.fontFamily=fontFamily(settings.font);
    this.term.options.fontSize=settings.fontSize;this.term.options.scrollback=settings.scrollback;this.term.options.cursorBlink=settings.cursorBlink;
    this.scheduleFit();
  }
  dispose(){clearTimeout(this.activityTimer);cancelAnimationFrame(this.frame);this.observer.disconnect();this.term.dispose();this.card.remove();}
}
