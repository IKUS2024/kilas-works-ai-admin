import test from 'node:test';
import assert from 'node:assert/strict';
import {appendDictation} from '../static/kilas_dictation.mjs';
test('dictation preserves existing editable text including changes made during processing',()=>{
  assert.equal(appendDictation('Naskah yang sudah diedit','Hasil dikte'),'Naskah yang sudah diedit\nHasil dikte');
  assert.equal(appendDictation('','Hasil dikte'),'Hasil dikte');
  assert.equal(appendDictation('A\n','B'),'A\nB');
});
test('no speech and length failure never return truncated/replacement text',()=>{
  assert.throws(()=>appendDictation('Original',' '));
  assert.throws(()=>appendDictation('Original','Long result',10));
});
