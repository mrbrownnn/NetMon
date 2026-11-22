export interface HistoryRow {ts: string; status: string; value: number | null}

export function historyPoints(rows: HistoryRow[]): {x: number; y: number | null}[] {
  return rows.filter(row => Number.isFinite(Date.parse(row.ts)))
    .map(row => ({x: Date.parse(row.ts), y: ['UP', 'WARNING'].includes(row.status.toUpperCase()) && row.value != null && Number.isFinite(row.value) ? row.value : null}))
    .sort((a, b) => a.x - b.x);
}
