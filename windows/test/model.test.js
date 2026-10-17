import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createState, validateState, layoutCells, SHAPES, newPane, changeState } from '../src/model.js';

test('every layout covers every pane once and fills each row, for 1–20 panes', () => {
  for (const shape of Object.keys(SHAPES)) for (let count = 1; count <= 20; count++) {
    const cells = layoutCells(count, shape);
    assert.deepEqual(cells.map(c => c.index).sort((a,b) => a-b), Array.from({length:count}, (_,i)=>i));
    const rows = Math.max(...cells.map(c => c.row + c.height));
    for (let row = 0; row < rows; row++) {
      assert.equal(cells.filter(c => c.row <= row && c.row + c.height > row).reduce((n,c)=>n+c.width,0), 12);
    }
  }
});

test('reject invalid settings and duplicate session IDs before writing or spawning', () => {
  for (const mutate of [
    s => s.workspaces[0].panes.push(s.workspaces[0].panes[0]),
    s => s.workspaces[0].panes = [],
    s => s.workspaces[0].panes = Array.from({length:21}, () => newPane()),
    s => s.settings.fontSize = NaN,
    s => s.workspaces[0].panes[0].cwd = 'bad\0path',
    s => s.workspaces[0].panes[0].shell = 'arbitrary.exe',
    s => s.activeWorkspace = 'missing'
  ]) {
    const state = createState(); mutate(state);
    assert.throws(() => validateState(state));
  }
});

test('workspace changes preserve session IDs, and removing the final pane is refused', () => {
  let state = createState();
  const original = structuredClone(state);
  state = changeState(state, {type:'workspace-add', name:'Coding'});
  assert.equal(original.workspaces.length, 1);
  assert.equal(state.workspaces.length, 2);
  assert.deepEqual(state.workspaces[0], original.workspaces[0]);
  const id = state.workspaces[1].panes[0].id;
  assert.throws(() => changeState(state, {type:'pane-remove', id}));
  state = changeState(state, {type:'pane-add'});
  state = changeState(state, {type:'pane-remove', id});
  assert.equal(state.workspaces[1].panes.length, 1);
});
