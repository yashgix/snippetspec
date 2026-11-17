#!/usr/bin/env node
import { readFileSync, readdirSync } from "node:fs"
import { basename, extname, join } from "node:path"
import { parseArgs } from "node:util"
import { pathToFileURL } from "node:url"
import { scan, type ScanResult } from "./report.js"
import type { Specs } from "./spec.js"
import { splitUrl } from "./url.js"
import { isObject } from "./values.js"

export function loadPages(folder: string): Record<string, string> {
  const files = readdirSync(folder, { recursive: true })
    .map(String)
    .filter((file) => /\.mdx?$/.test(file))
    .sort()
  return Object.fromEntries(files.map((file) => [file.replaceAll("\\", "/"), readFileSync(join(folder, file), "utf8")]))
}

export function textReport(result: ScanResult): string {
  const lines = result.calls
    .filter((row) => row.verdict !== "ok")
    .map((row) => {
      const head = `${row.page}:${row.line} #${row.index} ${row.method} ${splitUrl(row.url)?.path ?? ""} ${row.verdict}`
      return (
        head + (row.problems.length ? ` ${row.problems.map(([code, where]) => `${code} ${where}`).join("; ")}` : "")
      )
    })
  const count = (verdict: string) => result.calls.filter((row) => row.verdict === verdict).length
  lines.push(
    `${result.calls.length} calls: ${count("ok")} ok, ${count("partial")} partial, ${count("mismatch")} mismatch`,
  )
  if (result.unparsed) lines.push(`${result.unparsed} curl commands could not be read (quoting error)`)
  return `${lines.join("\n")}\n`
}

export function main(argv = process.argv.slice(2)): number {
  try {
    const { values, positionals } = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        docs: { type: "string" },
        spec: { type: "string", multiple: true },
        host: { type: "string" },
        json: { type: "boolean" },
        help: { type: "boolean", short: "h" },
      },
    })
    if (values.help) {
      process.stdout.write("Usage: snippetspec [PAGE...] --docs DIR --spec FILE (repeatable) --host HOST [--json]\n")
      return 0
    }
    if ((!positionals.length && !values.docs) || !values.spec?.length || !values.host)
      throw new Error("Provide PAGE or --docs DIR, at least one --spec FILE, and --host HOST")
    const pages = positionals.length
      ? Object.fromEntries(positionals.map((page) => [page, readFileSync(page, "utf8")]))
      : loadPages(values.docs ?? "")
    const specs: Specs = {}
    for (const file of values.spec) {
      const name = basename(file, extname(file))
      if (Object.hasOwn(specs, name)) throw new Error(`Duplicate spec name: ${name}`)
      const spec: unknown = JSON.parse(readFileSync(file, "utf8"))
      if (!isObject(spec)) throw new Error(`Spec must be an object: ${file}`)
      specs[name] = spec
    }
    const result = scan(pages, specs, values.host)
    process.stdout.write(values.json ? `${JSON.stringify(result, null, 1)}\n` : textReport(result))
    return result.calls.some((row) => row.verdict === "mismatch") ? 1 : 0
  } catch (error) {
    process.stderr.write(`snippetspec: ${error instanceof Error ? error.message : String(error)}\n`)
    return 2
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exitCode = main()
