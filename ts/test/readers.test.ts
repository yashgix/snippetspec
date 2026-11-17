import { readFileSync } from "node:fs"
import { describe, expect, test } from "vitest"
import { findCalls, shellWords, unparsedCommands, type Call } from "../src/calls.js"
import { UNKNOWN } from "../src/values.js"

interface Fixture {
  code: string
  language: string
  calls: Call[]
  unparsed: string[]
}
function revive(_key: string, value: unknown): unknown {
  return value && typeof value === "object" && "$unknown" in value ? UNKNOWN : value
}
const fixtures = JSON.parse(readFileSync("test/fixtures/calls.json", "utf8"), revive) as Fixture[]

describe("Python reference reader edge cases", () => {
  fixtures.forEach((fixture, index) => {
    test(`${index}: ${fixture.language} ${fixture.code.slice(0, 85)}`, () => {
      expect(findCalls(fixture)).toEqual(fixture.calls)
      expect(unparsedCommands(fixture)).toEqual(fixture.unparsed)
    })
  })
})

test.each([
  ["a 'b c' d", ["a", "b c", "d"]],
  ['a "b\\xc\\"d"', ["a", 'b\\xc"d']],
  ["a\\ b '' \"\" # rest", ["a b", "", ""]],
  ["'unterminated", null],
  ["a \\", null],
])("shlex words: %s", (text, expected) => expect(shellWords(text as string)).toEqual(expected))

test("a regex literal is not an executable fetch call", () => {
  expect(findCalls({ language: "js", code: 'const pattern = /fetch("https:\\/\\/x.test/a")/' })).toEqual([])
})

test("host placeholders and literal URL paths retain Python URL splitting", () => {
  const calls = findCalls({
    language: "bash",
    code: 'curl "http://<your-domain>/a/../b" "https://x.test/items/{id}?q=a%26b&q="',
  })
  expect(calls.map((call) => call.url)).toEqual(["http://<your-domain>/a/../b", "https://x.test/items/{id}?q=a%26b&q="])
  expect(calls[1]?.query).toEqual([
    ["q", "a&b"],
    ["q", ""],
  ])
  expect(shellWords("one # comment\ntwo")).toEqual(["one", "two"])
})
