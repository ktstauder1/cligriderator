export const element=(tag,text,className)=>{
  const node=document.createElement(tag); if (text!==undefined) node.textContent=text; if (className) node.className=className; return node;
};
export function button(text,run,className) {
  const node=element('button',text,className); node.type='button'; node.addEventListener('click',run); return node;
}
const dialog=document.querySelector('#dialog'), body=document.querySelector('#dialog-body'), actions=document.querySelector('#dialog-actions'), form=document.querySelector('#dialog-form');
let restoreFocus;
dialog.addEventListener('close',()=>restoreFocus?.focus());
export function openDialog(title) {
  if (dialog.open) dialog.close();
  restoreFocus=document.activeElement;
  document.querySelector('#dialog-title').textContent=title;
  body.replaceChildren(); actions.replaceChildren(); form.onsubmit=e=>e.preventDefault();
  dialog.showModal();
  return {body,actions,close:()=>dialog.close()};
}
export function field(parent,label,value,type='text',options) {
  const wrapper=element('label',label,type==='checkbox'?'checkbox':'');
  const input=element(type==='select'?'select':type==='textarea'?'textarea':'input');
  if (type==='select') for (const [key,text] of options) {const o=element('option',text);o.value=key;input.append(o);}
  else if (type!=='textarea') input.type=type;
  if (type==='checkbox') input.checked=value; else input.value=value;
  wrapper.append(input);parent.append(wrapper);return input;
}
export function finishForm(ctx,onSave,label='Save') {
  const save=button(label,()=>form.requestSubmit(),'primary');
  ctx.actions.append(button('Cancel',ctx.close),save);
  form.onsubmit=async e=>{
    e.preventDefault();save.disabled=true;
    try {await onSave();ctx.close();}
    catch(error){showToast(error.message);}
    finally{save.disabled=false;}
  };
  body.querySelector('input,select,textarea,button')?.focus();
}
let toastTimer;
export function showToast(message) {
  const toast=document.querySelector('#toast');toast.textContent=message;toast.hidden=false;
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.hidden=true,5000);
}
export const report=promise=>Promise.resolve(promise).catch(error=>showToast(error.message));
