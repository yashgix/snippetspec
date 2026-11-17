import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { afterEach, beforeEach, expect, test, vi } from "vitest"
import { main, loadPages, textReport } from "../src/cli.js"
import { scan, toViolations, operations, match, deref } from "../src/index.js"

const specs = {
  v1: {
    paths: {
      "/items": {
        get: {},
        post: {
          requestBody: {
            content: {
              "application/json": {
                schema: { type: "object", required: ["name"], properties: { name: { type: "string" } } },
              },
            },
          },
        },
      },
    },
  },
}
const fence = (code: string, language = "bash") => `\n\n\`\`\`${language}\n${code}\n\`\`\`\n`
let folder: string
beforeEach(() => {
  folder = mkdtempSync(join(process.cwd(), ".test-"))
})
afterEach(() => {
  vi.restoreAllMocks()
  rmSync(folder, { recursive: true, force: true })
})

function cli(args: string[]): { code: number; stdout: string; stderr: string } {
  let stdout = "",
    stderr = ""
  vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
    stdout += String(chunk)
    return true
  })
  vi.spyOn(process.stderr, "write").mockImplementation((chunk) => {
    stderr += String(chunk)
    return true
  })
  return { code: main(args), stdout, stderr }
}

function setup(code: string): { page: string; args: string[] } {
  const page = join(folder, "page.mdx"),
    spec = join(folder, "v1.json")
  writeFileSync(page, code)
  writeFileSync(spec, JSON.stringify(specs.v1))
  return { page, args: ["--docs", folder, "--spec", spec, "--host", "api.test"] }
}

test("CLI text output and mismatch exit status", () => {
  const { args } = setup(fence("curl https://api.test/items\ncurl https://api.test/nope\ncurl 'oops"))
  expect(cli(args)).toEqual({
    code: 1,
    stderr: "",
    stdout:
      "page.mdx:3 #1 GET /nope mismatch unknown_path /nope\n2 calls: 1 ok, 0 partial, 1 mismatch\n1 curl commands could not be read (quoting error)\n",
  })
})

test("CLI JSON and explicit PAGE preserve full report fields", () => {
  const { args, page } = setup(fence("curl https://api.test/items"))
  const result = cli([page, ...args, "--json"])
  expect(result.code).toBe(0)
  expect(result.stderr).toBe("")
  expect(JSON.parse(result.stdout)).toEqual(scan({ [page]: fence("curl https://api.test/items") }, specs, "api.test"))
})

test("CLI accepts repeatable specs and exits zero for partial calls", () => {
  const { args } = setup(
    fence("fetch('https://api.test/extra', {method: 'POST', body: JSON.stringify(payload)})", "ts"),
  )
  const second = join(folder, "v2.json")
  writeFileSync(second, JSON.stringify({ paths: { "/extra": specs.v1.paths["/items"] } }))
  expect(cli([...args, "--spec", second])).toEqual({
    code: 0,
    stdout: "page.mdx:3 #0 POST /extra partial\n1 calls: 0 ok, 1 partial, 0 mismatch\n",
    stderr: "",
  })
})

test("CLI help and argument failures", () => {
  expect(cli(["--help"])).toMatchObject({ code: 0, stderr: "" })
  expect(cli([]).code).toBe(2)
  expect(cli(["--unknown"]).code).toBe(2)
  const { args } = setup(fence("curl https://api.test/items"))
  expect(cli([...args, "--spec", join(folder, "v1.json")]).stderr).toContain("Duplicate spec name")
  expect(cli([...args, "missing.mdx"]).code).toBe(2)
})

test("folder loading sorts relative Markdown and MDX paths and ignores other files", () => {
  mkdirSync(join(folder, "nested"))
  writeFileSync(join(folder, "z.md"), "z")
  writeFileSync(join(folder, "nested", "a.mdx"), "a")
  writeFileSync(join(folder, "ignored.json"), "{}")
  expect(Object.entries(loadPages(folder))).toEqual([
    ["nested/a.mdx", "a"],
    ["z.md", "z"],
  ])
})

test("report indexes count only host calls and reset for each example", () => {
  const page =
    fence("curl https://other.test/items\ncurl https://api.test/items\ncurl https://api.test/nope") +
    fence("requests.post('https://api.test/items', json={'name': payload})", "python")
  const result = scan({ "p.mdx": page }, specs, "api.test")
  expect(result).toMatchObject({ pages: 1, examples: 2, other_host: 1, unparsed: 0 })
  expect(result.calls.map((row) => [row.index, row.verdict])).toEqual([
    [0, "ok"],
    [1, "mismatch"],
    [0, "partial"],
  ])
  expect(textReport(result)).toContain("3 calls: 1 ok, 1 partial, 1 mismatch")
})

test("Margin violations include one entry per problem at the code block's opening line", () => {
  const result = scan({ "nested/p.mdx": fence("curl https://api.test/items -d '{\"extra\":true}'") }, specs, "api.test")
  expect(toViolations(result)).toEqual([
    { path: "nested/p.mdx", line: 3, message: "POST https://api.test/items: missing_field $.name" },
    { path: "nested/p.mdx", line: 3, message: "POST https://api.test/items: undocumented_field $.extra" },
  ])
  expect(toViolations(result.calls)).toEqual(toViolations(result))
  expect(toViolations(scan({ "p.md": fence("curl https://api.test/items") }, specs, "api.test"))).toEqual([])
})

test("matching keeps method-first precedence, literal preference, and stable spec order", () => {
  const ops = operations({
    a: { paths: { "/items/{id}": { get: {}, delete: {} }, "/items/search": { post: {} } } },
    b: { paths: { "/items/{id}": { get: {} } } },
  })
  expect(match(ops, "get", "/items/search/")[0]?.name).toBe("GET /items/{id}")
  expect(match(ops, "POST", "/items/search")[0]?.name).toBe("POST /items/search")
  expect(match(ops, "GET", "/items/7")[0]?.spec).toBe("a")
  expect(match(ops, "PATCH", "/items/7")).toEqual([null, ["method_not_allowed", "DELETE,GET"]])
  expect(match(ops, "GET", "/other")).toEqual([null, ["unknown_path", "/other"]])
})

test("local references preserve siblings, unescape pointers, and stop cycles", () => {
  const spec = { defs: { "a/b": { type: "string" }, A: { $ref: "#/defs/B" }, B: { $ref: "#/defs/A" } } }
  expect(deref(spec, { $ref: "#/defs/a~1b", type: "number" })).toEqual({ type: "number" })
  expect(deref(spec, { $ref: "#/defs/A" })).toEqual({ $ref: "#/defs/A" })
  expect(deref(spec, { $ref: "https://x/schema" })).toEqual({ $ref: "https://x/schema" })
})
