import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('./operations.tsx', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } });
const require = createRequire(import.meta.url);
const module = { exports: {} };
new Function('require', 'module', 'exports', outputText)(name => name === '../api' ? { api: {} } : require(name), module, module.exports);
const { descendants, duration, failure, number, roleName } = module.exports;

test('group parent options exclude descendants independent of order and tolerate cycles', () => {
  const groups = [{ id: 3, parent_id: 2 }, { id: 2, parent_id: 1 }, { id: 4, parent_id: null }, { id: 1, parent_id: 3 }];
  assert.deepEqual([...descendants(groups, 1)].sort(), [1, 2, 3]);
  assert.deepEqual([...descendants(groups, 4)], [4]);
});
test('roles normalize enums and missing metrics never become zero', () => {
  assert.equal(roleName({ value: 'ADMIN' }), 'admin');
  assert.equal(roleName('Operator'), 'operator');
  assert.equal(roleName(null), '');
  assert.equal(number(null), '–');
  assert.equal(duration(undefined), '–');
  assert.equal(duration(0), '0 giây');
  assert.equal(duration(90061), '1 ngày 1 giờ 1 phút 1 giây');
});
test('validation failure preserves structured fields', () => {
  const error = Object.assign(new Error('Không hợp lệ'), { errors: { name: 'Bắt buộc' } });
  assert.equal(failure(error), error);
  assert.equal(typeof failure(null).message, 'string');
});
