import type { Call } from "./calls.js"
import {
  bodySchemas,
  candidates,
  deref,
  mergeAllOf,
  parameterName,
  params,
  segments,
  type Operation,
  type Problem,
  type Specs,
} from "./spec.js"
import { splitUrl, unquote } from "./url.js"
import { isObject, UNKNOWN, type Obj } from "./values.js"

export interface CheckResult {
  operation: string | null
  problems: Problem[]
}
const JSON_MEDIA = "application/json"
const FORM_TYPES = ["multipart/form-data", "application/x-www-form-urlencoded"]

export function isPlaceholder(value: unknown): boolean {
  return value === UNKNOWN || (typeof value === "string" && /[${}<>]/.test(value))
}

function typeFits(declared: unknown, value: unknown): boolean {
  if (Array.isArray(declared)) return declared.some((name) => typeFits(name, value))
  switch (declared) {
    case "string":
      return typeof value === "string"
    case "boolean":
      return typeof value === "boolean"
    case "integer":
      return typeof value === "number" && Number.isInteger(value)
    case "number":
      return typeof value === "number"
    case "array":
      return Array.isArray(value)
    case "object":
      return isObject(value)
    case "null":
      return value === null
    default:
      return true
  }
}

function branches(schema: Obj): unknown[] | null {
  for (const key of ["anyOf", "oneOf"]) {
    const value = schema[key]
    if (Array.isArray(value) && value.length) return value
  }
  return null
}

function equal(a: unknown, b: unknown): boolean {
  // Python's literal equality treats booleans as integers, including within containers.
  if ((typeof a === "boolean" || typeof a === "number") && (typeof b === "boolean" || typeof b === "number"))
    return Number(a) === Number(b)
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((item, i) => equal(item, b[i]))
  if (isObject(a) && isObject(b))
    return (
      Object.keys(a).length === Object.keys(b).length &&
      Object.entries(a).every(([key, item]) => Object.hasOwn(b, key) && equal(item, b[key]))
    )
  return a === b
}

export function validate(spec: Obj, schema: unknown, value: unknown, where = "$"): Problem[] {
  if (isPlaceholder(value)) return []
  const resolved = mergeAllOf(spec, deref(spec, schema))
  if (!isObject(resolved)) return []
  const choices = branches(resolved)
  if (choices) {
    const results = choices.map((branch) => validate(spec, branch, value, where))
    if (results.some((found) => !found.length)) return []
    let best: Problem[] | undefined
    choices.forEach((branch, index) => {
      const candidate = deref(spec, branch)
      const found = results[index]
      if (found && (!isObject(candidate) || typeFits(candidate.type, value)) && (!best || found.length < best.length))
        best = found
    })
    return best ?? [["type", where]]
  }
  if (!typeFits(resolved.type, value)) return [["type", where]]
  if (Object.hasOwn(resolved, "const") && !equal(value, resolved.const)) return [["enum", where]]
  if (Array.isArray(resolved.enum) && !resolved.enum.some((item) => equal(item, value))) return [["enum", where]]
  if (Array.isArray(value) && Object.hasOwn(resolved, "items"))
    return value.flatMap((item, index) => validate(spec, resolved.items, item, `${where}[${index}]`))
  if (isObject(value) && isObject(resolved.properties)) {
    const properties = resolved.properties
    return objectProblems(resolved, value, where, (key, item) =>
      validate(spec, properties[key], item, `${where}.${key}`),
    )
  }
  return []
}

function objectProblems(
  schema: Obj,
  value: Obj,
  where: string,
  check: (key: string, item: unknown) => Problem[],
): Problem[] {
  if (!isObject(schema.properties)) return []
  const properties = schema.properties
  const problems: Problem[] = []
  if (Array.isArray(schema.required))
    for (const key of schema.required) {
      if (typeof key === "string" && !Object.hasOwn(value, key)) problems.push(["missing_field", `${where}.${key}`])
    }
  for (const [key, item] of Object.entries(value)) {
    if (Object.hasOwn(properties, key)) problems.push(...check(key, item))
    else if (schema.additionalProperties !== true && !isObject(schema.additionalProperties))
      problems.push(["undocumented_field", `${where}.${key}`])
  }
  return problems
}

function textFits(type: unknown, value: string): boolean {
  if (type === "integer") return /^-?\d+$/.test(value)
  if (type === "number") return /^-?\d+(?:\.\d+)?$/.test(value)
  if (type === "boolean") return value === "true" || value === "false"
  return true
}

function text(value: unknown): string {
  return value === null ? "null" : String(value)
}

function parameterProblems(spec: Obj, schema: unknown, value: string, where: string): Problem[] {
  if (isPlaceholder(value)) return []
  const resolved = mergeAllOf(spec, deref(spec, schema))
  if (!isObject(resolved)) return []
  const choices = branches(resolved)
  if (choices)
    return choices.some((branch) => !parameterProblems(spec, branch, value, where).length) ? [] : [["type", where]]
  if (resolved.type === "array" && Object.hasOwn(resolved, "items"))
    return parameterProblems(spec, resolved.items, value, where)
  if (Object.hasOwn(resolved, "const")) return text(resolved.const) === value ? [] : [["enum", where]]
  if (Array.isArray(resolved.enum)) return resolved.enum.some((item) => text(item) === value) ? [] : [["enum", where]]
  const types = Array.isArray(resolved.type) ? resolved.type : [resolved.type]
  return types.some((type) => textFits(type, value)) ? [] : [["type", where]]
}

function pathProblems(spec: Obj, operation: Operation, path: string): Problem[] {
  const declared = params(spec, operation, "path")
  const actual = segments(path)
  return segments(operation.template).flatMap((segment, index) => {
    const name = parameterName(segment)
    const parameter = name === null ? undefined : declared[name]
    return parameter ? parameterProblems(spec, parameter.schema, unquote(actual[index] ?? ""), `path:${name}`) : []
  })
}

function queryProblems(spec: Obj, operation: Operation, query: Call["query"]): Problem[] {
  const declared = params(spec, operation, "query")
  const sent = new Set(query.map(([name]) => name))
  const problems: Problem[] = []
  for (const [name, parameter] of Object.entries(declared))
    if (parameter.required === true && !sent.has(name)) problems.push(["missing_param", `query:${name}`])
  for (const [name, value] of query) {
    const parameter = Object.hasOwn(declared, name) ? declared[name] : undefined
    problems.push(
      ...(parameter
        ? parameterProblems(spec, parameter.schema, value, `query:${name}`)
        : [["undocumented_param", `query:${name}`] as Problem]),
    )
  }
  return problems
}

function bodyProblems(spec: Obj, operation: Operation, call: Call): Problem[] {
  const schemas = bodySchemas(operation)
  if (call.body_kind === "none")
    return isObject(operation.op.requestBody) && operation.op.requestBody.required === true
      ? [["missing_body", "body"]]
      : []
  if (!Object.keys(schemas).length)
    return call.body_kind === "json" && isObject(call.body) && !Object.keys(call.body).length
      ? []
      : [["unexpected_body", "body"]]
  let media: string | undefined
  if (call.media) media = call.media.endsWith("+json") && Object.hasOwn(schemas, JSON_MEDIA) ? JSON_MEDIA : call.media
  else if (call.body_kind === "form") media = FORM_TYPES.find((name) => Object.hasOwn(schemas, name))
  else if (Object.hasOwn(schemas, JSON_MEDIA)) media = JSON_MEDIA
  if (!media || !Object.hasOwn(schemas, media))
    return [["content_type", `body:${call.media ?? (call.body_kind === "form" ? "form" : "json")}`]]
  const schema = mergeAllOf(spec, deref(spec, schemas[media]))
  if (FORM_TYPES.includes(media))
    return isObject(schema) && isObject(call.body) ? objectProblems(schema, call.body, "$", () => []) : []
  return media === JSON_MEDIA && call.body_kind === "json" ? validate(spec, schema, call.body) : []
}

export function checkCall(specs: Specs, ops: Operation[], call: Call): CheckResult {
  const path = splitUrl(call.url)?.path ?? ""
  const [found, problem] = candidates(ops, call.method, path)
  if (!found.length) return { operation: null, problems: problem ? [problem] : [] }
  // Several specs can declare the same route (e.g. a legacy and a current one); judge the call by its best fit.
  const results = found.map((operation) => operationProblems(specs[operation.spec] ?? {}, operation, path, call))
  const best = results.reduce(
    (winner, problems, index) => (problems.length < (results[winner]?.length ?? 0) ? index : winner),
    0,
  )
  const operation = found[best] as Operation
  return { operation: `${operation.spec}:${operation.name}`, problems: results[best] ?? [] }
}

function operationProblems(spec: Obj, operation: Operation, path: string, call: Call): Problem[] {
  return [
    ...pathProblems(spec, operation, path),
    ...queryProblems(spec, operation, call.query),
    ...bodyProblems(spec, operation, call),
  ]
}
