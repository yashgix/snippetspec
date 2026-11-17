import { findCalls, unparsedCommands, type Call } from "./calls.js"
import { checkCall } from "./check.js"
import { extract } from "./examples.js"
import { operations, type Problem, type Specs } from "./spec.js"
import { splitUrl } from "./url.js"
import { containsUnknown } from "./values.js"

export interface ScanRow {
  page: string
  line: number
  index: number
  language: string
  group: number | null
  tool: Call["tool"]
  method: string
  url: string
  operation: string | null
  verdict: "ok" | "partial" | "mismatch"
  problems: Problem[]
}
export interface ScanResult {
  pages: number
  examples: number
  other_host: number
  unparsed: number
  calls: ScanRow[]
}

export function scan(pages: Record<string, string>, specs: Specs, host: string): ScanResult {
  const result: ScanResult = { pages: Object.keys(pages).length, examples: 0, other_host: 0, unparsed: 0, calls: [] }
  const ops = operations(specs)
  for (const [page, text] of Object.entries(pages))
    for (const example of extract(text, page)) {
      result.examples++
      result.unparsed += unparsedCommands(example).length
      let index = 0
      for (const call of findCalls(example)) {
        if (splitUrl(call.url)?.host !== host) {
          result.other_host++
          continue
        }
        const checked = checkCall(specs, ops, call)
        const partial = call.body_kind === "unparsed" || (call.body_kind === "json" && containsUnknown(call.body))
        result.calls.push({
          page,
          line: example.line,
          index: index++,
          language: example.language,
          group: example.alternativesGroup ?? null,
          tool: call.tool,
          method: call.method,
          url: call.url,
          ...checked,
          verdict: checked.problems.length ? "mismatch" : partial ? "partial" : "ok",
        })
      }
    }
  return result
}
