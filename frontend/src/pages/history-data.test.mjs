import assert from 'node:assert/strict';
import {test} from 'node:test';
import {historyPoints} from './history-data.ts';

test('latency history preserves gaps without inventing data', () => {
  const rows = [
    {ts: '2026-11-22T00:00:06Z', status: 'UP', value: null},
    {ts: '2026-11-22T00:00:04Z', status: 'PAUSED', value: 4},
    {ts: 'invalid', status: 'UP', value: 20},
    {ts: '2026-11-22T00:00:01Z', status: 'UP', value: 0},
    {ts: '2026-11-22T00:00:03Z', status: 'DOWN', value: 3},
    {ts: '2026-11-22T00:00:05Z', status: 'UNKNOWN', value: 5},
    {ts: '2026-11-22T00:00:02Z', status: 'WARNING', value: 12},
    {ts: '2026-11-22T00:00:07Z', status: 'UP', value: Infinity},
  ];
  const before = JSON.stringify(rows);
  const points = historyPoints(rows);
  assert.deepEqual(points.map(point => point.y), [0, 12, null, null, null, null, null]);
  assert.equal(points.length, rows.length - 1);
  assert.equal(points[0].x, Date.parse('2026-11-22T00:00:01Z'));
  assert.equal(JSON.stringify(rows), before);
  assert.deepEqual(historyPoints([]), []);
});
