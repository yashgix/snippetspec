import { readFileSync } from "node:fs"
import { describe, expect, test } from "vitest"
import type { Call } from "../src/calls.js"
import { checkCall, validate, type CheckResult } from "../src/check.js"
import { operations, type Problem, type Specs } from "../src/spec.js"
import { UNKNOWN, type Obj } from "../src/values.js"

function fixture<T>(name: string): T {
  return JSON.parse(readFileSync(`test/fixtures/${name}.json`, "utf8"), (_key, value: unknown) =>
    value && typeof value === "object" && "$unknown" in value ? UNKNOWN : value,
  ) as T
}

describe("Python reference checks", () => {
  const checks = fixture<{ specs: Specs; call: Call; result: CheckResult }[]>("checks")
  checks.forEach((item, index) => {
    test(`call ${index}: ${item.call.method} ${item.call.url}`, () => {
      expect(checkCall(item.specs, operations(item.specs), item.call)).toEqual(item.result)
    })
  })
  const validations =
    fixture<{ spec: Obj; schema: unknown; value: unknown; where: string; result: Problem[] }[]>("validation")
  validations.forEach((item, index) => {
    test(`schema ${index}`, () => expect(validate(item.spec, item.schema, item.value, item.where)).toEqual(item.result))
  })
})

test("path decoding preserves ampersands and plus signs", () => {
  const specs = {
    v: { paths: { "/items/{id}": { get: { parameters: [{ name: "id", in: "path", schema: { enum: ["a&b+c"] } }] } } } },
  }
  const call: Call = {
    tool: "curl",
    method: "GET",
    url: "https://x/items/a&b+c",
    query: [],
    body_kind: "none",
    body: null,
    media: null,
  }
  expect(checkCall(specs, operations(specs), call).problems).toEqual([])
})
