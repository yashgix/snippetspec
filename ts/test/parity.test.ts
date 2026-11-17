import { readFileSync } from "node:fs"
import { describe, expect, test } from "vitest"
import { loadPages } from "../src/cli.js"
import { extract, parsePage } from "../src/examples.js"
import { scan, type ScanResult } from "../src/report.js"
import { extractCodeExamplesFromMdast } from "../vendor/margin/code-examples.js"

function json<T>(file: string): T {
  return JSON.parse(readFileSync(file, "utf8")) as T
}
const pages = loadPages("../data/docs")

describe("Margin parity", () => {
  for (const [page, text] of Object.entries(pages))
    test(page, () => {
      expect(extract(text, page).map(({ line: _line, ...example }) => example)).toEqual(
        extractCodeExamplesFromMdast(parsePage(text, page)),
      )
    })
})

test("exact Supermemory Python scan parity", () => {
  const specs = {
    v4: json<Record<string, unknown>>("../data/openapi/v4.json"),
    v5: json<Record<string, unknown>>("../data/openapi/v5.json"),
  }
  expect(scan(pages, specs, "api.supermemory.ai")).toEqual(json<ScanResult>("test/fixtures/supermemory.json"))
})

test("exact Meilisearch Python scan parity", () => {
  const pages = Object.fromEntries(
    Object.entries(loadPages("../data/holdout/docs")).map(([name, text]) => [
      name,
      text.replaceAll("MEILISEARCH_URL", "https://ms.example"),
    ]),
  )
  const specs = { meili: json<Record<string, unknown>>("../data/holdout/spec/openapi.json") }
  expect(scan(pages, specs, "ms.example")).toEqual(json<ScanResult>("test/fixtures/meilisearch.json"))
})
