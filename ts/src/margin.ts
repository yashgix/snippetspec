import type { ScanResult, ScanRow } from "./report.js"

export interface DocsViolation {
  path: string
  message: string
  line: number
}

export function toViolations(rows: readonly ScanRow[] | ScanResult): DocsViolation[] {
  const calls: readonly ScanRow[] = "calls" in rows ? rows.calls : rows
  return calls.flatMap((row) =>
    row.problems.map(([code, where]) => ({
      path: row.page,
      message: `${row.method} ${row.url}: ${code} ${where}`,
      line: row.line,
    })),
  )
}
