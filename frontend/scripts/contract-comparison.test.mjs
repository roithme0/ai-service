import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sameContract } from './contract-comparison.mjs';

test('contract comparison ignores checkout line endings only', () => {
  assert.equal(sameContract(Buffer.from('a\r\nb\r\n'), Buffer.from('a\nb\n')), true);
  assert.equal(sameContract(Buffer.from('a\nb\n'), Buffer.from('a\nc\n')), false);
  assert.equal(sameContract(Buffer.from('a\n'), Buffer.from('a')), false);
});
