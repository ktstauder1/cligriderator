// Shared by the trusted main process, renderer and tests. No platform dependencies.
export const MAX_PANES = 20;
export const SHAPES = { auto: [3,2], master: [2,2], '2x2':[2,2], '2x3':[2,3], '3x2':[3,2], '3x3':[3,3], '4x2':[4,2] };
for (let n = 1; n <= 6; n++) { SHAPES[`1x${n}`] = [1,n]; SHAPES[`${n}x1`] = [n,1]; }
export const THEMES = {
  griderator: { background:'#15171b', foreground:'#e6e8eb', cursor:'#d8be86', selectionBackground:'#454852', black:'#252830', red:'#d98d91', green:'#a6c29a', yellow:'#d8be86', blue:'#8eacd4', magenta:'#bb9ecb', cyan:'#8dbfbd', white:'#d4d7dc', brightBlack:'#747a87', brightRed:'#edafb2', brightGreen:'#c2dbb8', brightYellow:'#ecdbad', brightBlue:'#b2caeb', brightMagenta:'#d7bde4', brightCyan:'#b0dbd8', brightWhite:'#ffffff' },
  nord: {background:'#2e3440',foreground:'#eceff4',cursor:'#88c0d0',selectionBackground:'#4c566a'},
  dracula: {background:'#282a36',foreground:'#f8f8f2',cursor:'#bd93f9',selectionBackground:'#44475a'},
  'high-contrast': {background:'#000000',foreground:'#ffffff',cursor:'#ffff00',selectionBackground:'#555555'}
};
export function newPane(name = 'Terminal') {
  return { id:crypto.randomUUID(), name, shell:'powershell', cwd:'', command:'' };
}
export function createState() {
  const id = crypto.randomUUID();
  return { version:1, activeWorkspace:id,
    settings:{theme:'griderator',font:'Consolas',fontSize:13,scrollback:10000,cursorBlink:false,notifications:true},
    workspaces:[{id, name:'Default', layout:'auto', panes:Array.from({length:6},(_,i)=>newPane(`Terminal ${i+1}`))}] };
}
const ensure = (condition, message) => { if (!condition) throw new Error(message); };
function text(value, max, label) {
  ensure(typeof value === 'string' && value.length <= max && !value.includes('\0'), `Invalid ${label}`);
}
export function validateState(state) {
  ensure(state?.version === 1, 'Unsupported settings version');
  const s = state.settings;
  ensure(s && Object.hasOwn(THEMES, s.theme), 'Unknown theme');
  text(s.font, 100, 'font');
  ensure(Number.isInteger(s.fontSize) && s.fontSize >= 8 && s.fontSize <= 32, 'Font size must be 8–32');
  ensure(Number.isInteger(s.scrollback) && s.scrollback >= 100 && s.scrollback <= 100000, 'Scrollback must be 100–100000');
  ensure(typeof s.cursorBlink === 'boolean' && typeof s.notifications === 'boolean', 'Invalid settings');
  ensure(Array.isArray(state.workspaces) && state.workspaces.length > 0 && state.workspaces.length <= 10, 'Use 1–10 workspaces');
  const ids = new Set();
  const unique = id => { text(id, 80, 'ID'); ensure(/^[a-zA-Z0-9-]+$/.test(id) && !ids.has(id), 'Invalid or duplicate ID'); ids.add(id); };
  for (const w of state.workspaces) {
    unique(w.id); text(w.name, 80, 'workspace name'); ensure(w.name.trim(), 'Name cannot be empty');
    ensure(Object.hasOwn(SHAPES, w.layout), 'Unknown layout');
    ensure(Array.isArray(w.panes) && w.panes.length >= 1 && w.panes.length <= MAX_PANES, 'Use 1–20 panes per workspace');
    for (const p of w.panes) {
      unique(p.id); text(p.name,80,'pane name'); text(p.cwd,4096,'directory'); text(p.command,8192,'command');
      ensure(['powershell','cmd'].includes(p.shell), 'Unknown shell');
    }
  }
  ensure(state.workspaces.some(w => w.id === state.activeWorkspace), 'Unknown active workspace');
  return state;
}
export const activeWorkspace = state => state.workspaces.find(w => w.id === state.activeWorkspace);
export function changeState(previous, action) {
  const state = structuredClone(previous), w = activeWorkspace(state);
  switch (action.type) {
    case 'pane-add': w.panes.push(newPane(`Terminal ${w.panes.length+1}`)); break;
    case 'pane-remove': ensure(w.panes.some(p=>p.id===action.id),'Unknown pane'); w.panes = w.panes.filter(p=>p.id!==action.id); break;
    case 'pane-edit': {
      const pane = w.panes.find(p=>p.id===action.id); ensure(pane,'Unknown pane');
      for (const key of ['name','cwd','command','shell']) if (Object.hasOwn(action.values,key)) pane[key] = action.values[key];
      break;
    }
    case 'pane-swap': {
      const a = w.panes.findIndex(p=>p.id===action.a), b = w.panes.findIndex(p=>p.id===action.b);
      ensure(a >= 0 && b >= 0,'Unknown pane'); [w.panes[a],w.panes[b]] = [w.panes[b],w.panes[a]]; break;
    }
    case 'workspace-add': {
      const id = crypto.randomUUID(); state.workspaces.push({id,name:action.name,layout:'auto',panes:[newPane()]}); state.activeWorkspace=id; break;
    }
    case 'workspace-switch': state.activeWorkspace=action.id; break;
    case 'workspace-rename': w.name=action.name; break;
    case 'workspace-remove': state.workspaces=state.workspaces.filter(v=>v.id!==w.id); state.activeWorkspace=state.workspaces[0]?.id; break;
    case 'layout': w.layout=action.value; break;
    case 'settings': for (const key of Object.keys(state.settings)) if (Object.hasOwn(action.values,key)) state.settings[key]=action.values[key]; break;
    default: throw new Error('Unknown action');
  }
  return validateState(state);
}
export function layoutCells(count, shape='auto') {
  ensure(Number.isInteger(count) && count >= 1 && count <= MAX_PANES,'Invalid pane count');
  ensure(Object.hasOwn(SHAPES,shape),'Unknown layout');
  if (shape==='master' && count>1) return [
    {index:0,col:0,row:0,width:6,height:count-1},
    ...Array.from({length:count-1},(_,i)=>({index:i+1,col:6,row:i,width:6,height:1}))
  ];
  const columns=Math.min(count, shape==='auto' && count===4 ? 2 : SHAPES[shape][0]);
  return Array.from({length:count},(_,index)=>{
    const start=Math.floor(index/columns)*columns, n=Math.min(columns,count-start), pos=index-start;
    const width=Math.floor(12/n), extra=12%n;
    return {index,col:pos*width+Math.min(pos,extra),row:Math.floor(index/columns),width:width+(pos<extra?1:0),height:1};
  });
}
