import { isObject, type Obj } from "./values.js"

export type Specs = Record<string, Obj>
export type Problem = [code: string, where: string]
export interface Operation {
  readonly spec: string
  readonly method: string
  readonly template: string
  readonly op: Obj
  readonly name: string
}

export function operations(specs: Specs | [string, Obj][]): Operation[] {
  const out: Operation[] = []
  for (const [spec, document] of Array.isArray(specs) ? specs : Object.entries(specs)) {
    if (!isObject(document.paths)) continue
    const prefix = basePath(document)
    for (const [path, item] of Object.entries(document.paths)) {
      if (!isObject(item)) continue
      const template = prefix + path
      for (const [method, op] of Object.entries(item)) {
        if (["get", "post", "put", "patch", "delete"].includes(method) && isObject(op)) {
          const name = `${method.toUpperCase()} ${template}`
          out.push({ spec, method: method.toUpperCase(), template, op: withPathParameters(item, op), name })
        }
      }
    }
  }
  return out
}

// The first server URL's path (e.g. "/v2"), which the docs write in front of every spec path.
export function basePath(spec: Obj): string {
  const server = Array.isArray(spec.servers) ? spec.servers[0] : undefined
  const url = isObject(server) ? server.url : undefined
  if (typeof url !== "string" || url.includes("{")) return ""
  const match = /^[a-z][a-z0-9+.-]*:\/\/[^/?#]*([^?#]*)/i.exec(url)
  return (match ? (match[1] ?? "") : url.startsWith("/") ? (url.split(/[?#]/)[0] ?? "") : "").replace(/\/+$/, "")
}

function withPathParameters(item: Obj, op: Obj): Obj {
  if (!Array.isArray(item.parameters) || !item.parameters.length) return op
  const own = Array.isArray(op.parameters) ? op.parameters : []
  return { ...op, parameters: [...item.parameters, ...own] }
}

export function segments(path: string): string[] {
  return path.split("/").filter(Boolean)
}
export function parameterName(segment: string): string | null {
  return segment.length > 2 && segment.startsWith("{") && segment.endsWith("}") ? segment.slice(1, -1) : null
}

export function match(ops: Operation[], method: string, path: string): [Operation, null] | [null, Problem] {
  const [found, problem] = candidates(ops, method, path)
  return found[0] ? [found[0], null] : [null, problem ?? ["unknown_path", path]]
}

// The most specific operations a method and path reach, earliest first, or the reason none does.
export function candidates(ops: Operation[], method: string, path: string): [Operation[], Problem | null] {
  const parts = segments(path)
  const fitting = ops.filter((op) => {
    const template = segments(op.template)
    return (
      template.length === parts.length &&
      template.every((part, index) => parameterName(part) !== null || part === parts[index])
    )
  })
  if (!fitting.length) return [[], ["unknown_path", path]]
  const allowed = fitting.filter((op) => op.method.toUpperCase() === method.toUpperCase())
  if (!allowed.length)
    return [[], ["method_not_allowed", [...new Set(fitting.map((op) => op.method.toUpperCase()))].sort().join(",")]]
  const literals = (op: Operation) => segments(op.template).filter((part) => parameterName(part) === null).length
  const most = Math.max(...allowed.map(literals))
  return [allowed.filter((op) => literals(op) === most), null]
}

export function deref(spec: Obj, schema: unknown): unknown {
  let current = schema
  for (let depth = 0; depth < 12; depth++) {
    if (!isObject(current) || typeof current.$ref !== "string" || !current.$ref.startsWith("#/")) break
    let target: unknown = spec
    for (const raw of current.$ref.slice(2).split("/")) {
      const key = raw.replace(/~1/g, "/").replace(/~0/g, "~")
      target = isObject(target) && Object.hasOwn(target, key) ? target[key] : undefined
    }
    if (target === undefined || target === null) break
    if (!isObject(target)) return target
    const { $ref: _ref, ...siblings } = current
    current = { ...target, ...siblings }
  }
  return current
}

// A schema with its allOf parts folded in: properties and required lists combined, its own keys winning.
export function mergeAllOf(spec: Obj, schema: unknown, depth = 0): unknown {
  if (!isObject(schema) || !Array.isArray(schema.allOf) || depth > 12) return schema
  const merged: Obj = {}
  const properties: Obj = {}
  const required: string[] = []
  const take = (part: Obj) => {
    if (isObject(part.properties)) Object.assign(properties, part.properties)
    if (Array.isArray(part.required))
      for (const name of part.required) if (typeof name === "string" && !required.includes(name)) required.push(name)
  }
  for (const raw of schema.allOf) {
    const part = mergeAllOf(spec, deref(spec, raw), depth + 1)
    if (!isObject(part)) continue
    take(part)
    const { properties: _p, required: _r, ...rest } = part
    Object.assign(merged, rest)
  }
  const { allOf: _a, properties: _p, required: _r, ...own } = schema
  take(schema)
  Object.assign(merged, own)
  if (Object.keys(properties).length) merged.properties = properties
  if (required.length) merged.required = required
  return merged
}

export function bodySchemas(operation: Operation): Obj {
  const body = operation.op.requestBody
  if (!isObject(body) || !isObject(body.content)) return {}
  return Object.fromEntries(
    Object.entries(body.content).flatMap(([media, entry]) =>
      isObject(entry) && Object.hasOwn(entry, "schema") ? [[media, entry.schema]] : [],
    ),
  )
}

export function params(spec: Obj, operation: Operation, where: string): Record<string, Obj> {
  const declared = operation.op.parameters
  if (!Array.isArray(declared)) return {}
  return Object.fromEntries(
    declared
      .map((item) => deref(spec, item))
      .flatMap((parameter) =>
        isObject(parameter) && parameter.in === where && typeof parameter.name === "string"
          ? [[parameter.name, parameter]]
          : [],
      ),
  )
}
