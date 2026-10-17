import {test,expect} from '@playwright/test';
import fs from 'node:fs';
import {createState,changeState} from '../src/model.js';

test.beforeEach(async({page})=>{
  let state=createState();
  await page.exposeFunction('mockAction',async action=>{state=changeState(state,action);return state;});
  await page.addInitScript(initial=>{
    let listener;
    window.cligrid={state:async()=>initial,onState:fn=>listener=fn,onTerminal:()=>{},onFocus:()=>{},
      action:async action=>{const next=await window.mockAction(action);listener(next);return next;},
      open:async()=>({buffer:'Windows PowerShell\r\nPS C:\\Users\\You> ',seq:0,exitCode:null}),
      input:async()=>{},resize:async()=>{},copy:async()=>{},paste:async()=>'',bell:async()=>{},hide:async()=>{},quit:async()=>{},link:async()=>{},folder:async()=>null,broadcast:async()=>true,restart:async()=>null};
  },state);
  const files={'/':'src/index.html','/renderer.js':'dist/renderer.js','/style.css':'src/style.css','/xterm.css':'dist/xterm.css'};
  await page.route('http://cligrid.test/**',route=>{
    const file=files[new URL(route.request().url()).pathname];
    if(!file)return route.fulfill({status:404,body:''});
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
});

test('grid, zoom, layouts and pane limits work without browser errors',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('http://cligrid.test/');
  await expect(page.locator('.pane:visible')).toHaveCount(6);
  await page.getByRole('button',{name:'Zoom',exact:true}).click();
  await expect(page.locator('.pane:visible')).toHaveCount(1);
  await page.getByRole('button',{name:'Show grid',exact:true}).click();
  await page.getByLabel('Layout',{exact:true}).selectOption('master');
  await expect(page.locator('.pane:visible')).toHaveCount(6);
  for(let n=6;n<20;n++)await page.getByRole('button',{name:'Add terminal',exact:true}).click();
  await expect(page.locator('.pane:visible')).toHaveCount(20);
  await expect(page.getByRole('button',{name:'Add terminal',exact:true})).toBeDisabled();
  expect(errors).toEqual([]);
});
test('settings, search and workspace switching keep existing terminal displays',async({page})=>{
  await page.goto('http://cligrid.test/');
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  await page.getByLabel('Font size',{exact:true}).fill('16');
  await page.getByRole('button',{name:'Save',exact:true}).click();
  await expect(page.locator('dialog')).not.toBeVisible();
  await page.getByRole('button',{name:'Manage workspaces',exact:true}).click();
  await page.getByRole('button',{name:'New workspace…',exact:true}).click();
  await page.getByLabel('Name',{exact:true}).fill('Coding');
  await page.getByRole('button',{name:'Save',exact:true}).click();
  await expect(page.locator('.pane:visible')).toHaveCount(1);
  await page.getByLabel('Workspace',{exact:true}).selectOption({label:'Default'});
  await expect(page.locator('.pane:visible')).toHaveCount(6);
  await expect(page.locator('.pane')).toHaveCount(7);
  await page.keyboard.press('Control+Shift+g');
  await page.getByLabel('Search text',{exact:true}).fill('PowerShell');
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await expect(page.getByText('Match found',{exact:true})).toBeVisible();
});
test('terminal labels are text, palette is keyboard usable, small window stays contained',async({page})=>{
  await page.goto('http://cligrid.test/');
  await page.getByRole('button',{name:'Options for Terminal 1',exact:true}).click();
  await page.getByRole('button',{name:'Edit name, command and folder…',exact:true}).click();
  await page.getByLabel('Name',{exact:true}).fill('<img src=x onerror=alert(1)>');
  await page.getByRole('button',{name:'Save',exact:true}).click();
  await expect(page.locator('.pane-title').first()).toHaveText('<img src=x onerror=alert(1)>');
  await expect(page.locator('.pane img')).toHaveCount(0);
  await page.keyboard.press('Control+Shift+p');
  await page.getByLabel('Find an action, pane or workspace').fill('Zoom focused');
  await page.keyboard.press('Enter');
  await expect(page.locator('.pane:visible')).toHaveCount(1);
  await page.getByRole('button',{name:'Show grid',exact:true}).click();
  await page.setViewportSize({width:800,height:600});
  expect(await page.evaluate(()=>document.body.scrollWidth<=innerWidth)).toBe(true);
  await page.setViewportSize({width:1440,height:900});
  await page.screenshot({path:'test-results/windows-grid.png'});
});
