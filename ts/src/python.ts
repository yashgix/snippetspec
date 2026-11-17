import { makeCall, mediaType, type Call } from "./calls.js"
import { isObject, truthy, UNKNOWN, type Value } from "./values.js"

interface Token {
  text: string
  value?: Value
  kind: "string" | "number" | "name" | "punct"
}
const methods = new Set(["get", "post", "put", "patch", "delete", "request"])
const closes: Record<string, string> = { "(": ")", "[": "]", "{": "}" }

function decode(text: string): string {
  const escapes: Record<string, string> = {
    n: "\n",
    r: "\r",
    t: "\t",
    b: "\b",
    f: "\f",
    v: "\v",
    a: "\x07",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "\n": "",
  }
  return text.replace(
    /\\(U[\da-fA-F]{8}|u[\da-fA-F]{4}|x[\da-fA-F]{2}|[0-7]{1,3}|[\s\S])/g,
    (all: string, code: string) => {
      if (/^[Uux]/.test(code) && code.length > 1) return String.fromCodePoint(Number.parseInt(code.slice(1), 16))
      if (/^[0-7]/.test(code)) return String.fromCodePoint(Number.parseInt(code, 8))
      return escapes[code] ?? all
    },
  )
}

function tokens(code: string): Token[] | null {
  const out: Token[] = [],
    stack: string[] = []
  let index = 0
  while (index < code.length) {
    const char = code[index] ?? ""
    if (/\s/.test(char) || code.startsWith("\\\n", index)) {
      index += code.startsWith("\\\n", index) ? 2 : 1
      continue
    }
    if (char === "#") {
      const end = code.indexOf("\n", index)
      index = end < 0 ? code.length : end
      continue
    }
    const string = /^(?:([rRuUbBfF]{1,2}))?('''|"""|'|")/.exec(code.slice(index))
    if (string) {
      const prefix = (string[1] ?? "").toLowerCase(),
        quote = string[2] ?? "'"
      const start = index
      index += string[0].length
      const bodyStart = index
      while (index < code.length && !code.startsWith(quote, index)) {
        if (quote.length === 1 && code[index] === "\n") return null
        index += code[index] === "\\" ? 2 : 1
      }
      if (index >= code.length) return null
      const body = code.slice(bodyStart, index)
      index += quote.length
      let value: Value = prefix.includes("b") ? UNKNOWN : prefix.includes("r") ? body : decode(body)
      if (prefix.includes("f") && typeof value === "string")
        value = value
          .replace(/\{\{/g, "\x00")
          .replace(/\}\}/g, "\x01")
          .replace(/\{([^{}]*)\}/g, (_all: string, expression: string) => `{${expression.trim()}}`)
          .replaceAll("\x00", "{")
          .replaceAll("\x01", "}")
      out.push({ text: code.slice(start, index), kind: "string", value })
      continue
    }
    const name = /^[A-Za-z_]\w*/.exec(code.slice(index))
    if (name) {
      out.push({ text: name[0], kind: "name" })
      index += name[0].length
      continue
    }
    const number =
      /^(?:0[xX][\da-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?[\d_]+)?)/.exec(
        code.slice(index),
      )
    if (number) {
      out.push({ text: number[0], kind: "number" })
      index += number[0].length
      continue
    }
    if (closes[char]) stack.push(closes[char])
    else if ([")", "]", "}"].includes(char) && stack.pop() !== char) return null
    out.push({ text: char, kind: "punct" })
    index++
  }
  return stack.length ? null : out
}

function split(input: Token[], separator: string): Token[][] {
  const groups: Token[][] = [[]]
  let depth = 0
  for (const token of input) {
    if (depth === 0 && token.text === separator) groups.push([])
    else groups[groups.length - 1]?.push(token)
    if (closes[token.text]) depth++
    else if ([")", "]", "}"].includes(token.text)) depth--
  }
  return groups
}

function dictEntries(input: Token[]): [string, Token[]][] | null {
  if (input[0]?.text !== "{" || input.at(-1)?.text !== "}") return null
  const entries: [string, Token[]][] = []
  for (const group of split(input.slice(1, -1), ",")) {
    if (!group.length) continue
    const parts = split(group, ":")
    const name = literal(parts[0] ?? [])
    if (parts.length !== 2 || typeof name !== "string") return null
    entries.push([name, parts[1] ?? []])
  }
  return entries
}

function literal(input: Token[]): Value {
  if (!input.length) return UNKNOWN
  if (input.every((token) => token.kind === "string")) {
    if (input.some((token) => typeof token.value !== "string")) return UNKNOWN
    return input.map((token) => token.value).join("")
  }
  if (input.length === 1) {
    const token = input[0]
    if (!token) return UNKNOWN
    if (token.kind === "number") return Number(token.text.replace(/_/g, ""))
    if (token.text === "True") return true
    if (token.text === "False") return false
    if (token.text === "None") return null
    return UNKNOWN
  }
  const first = input[0]?.text,
    last = input.at(-1)?.text
  if ((first === "[" && last === "]") || (first === "(" && last === ")")) {
    const groups = split(input.slice(1, -1), ",")
    if (first === "(" && groups.length === 1 && groups[0]?.length) return literal(groups[0])
    return groups.filter((group) => group.length).map(literal)
  }
  const entries = dictEntries(input)
  return entries ? Object.fromEntries(entries.map(([key, value]) => [key, literal(value)])) : UNKNOWN
}

function queryValues(value: Value, client: string): string[] {
  if (value === UNKNOWN) return ["{?}"]
  if (Array.isArray(value)) return value.flatMap((item) => queryValues(item, client))
  if (value === null) return client === "requests" ? [] : [""]
  if (typeof value === "boolean") return [client === "httpx" ? String(value) : value ? "True" : "False"]
  return [String(value)]
}

function readCall(client: string, methodName: string, input: Token[]): Call | null {
  const positional: Token[][] = [],
    keywords = new Map<string, Token[]>()
  for (const group of split(input, ",")) {
    if (group[0]?.kind === "name" && group[1]?.text === "=") keywords.set(group[0].text, group.slice(2))
    else if (group.length) positional.push(group)
  }
  const argument = (name: string, position?: number) =>
    keywords.get(name) ?? (position === undefined ? undefined : positional[position])
  const method = methodName === "request" ? literal(argument("method", 0) ?? []) : methodName.toUpperCase()
  const url = literal(argument("url", methodName === "request" ? 1 : 0) ?? [])
  if (typeof method !== "string" || typeof url !== "string") return null
  const query: [string, string][] = []
  for (const [key, value] of dictEntries(argument("params") ?? []) ?? [])
    for (const item of queryValues(literal(value), client)) query.push([key, item])
  let kind: Call["body_kind"] = "none",
    body: Value = null
  if (client === "httpx" && keywords.has("content")) kind = "unparsed"
  else {
    for (const name of ["files", "data"]) {
      const payload = argument(name)
      const value = literal(payload ?? [])
      if (payload && (value === UNKNOWN || truthy(value))) {
        kind = isObject(value) ? "form" : "unparsed"
        body = kind === "form" ? value : null
        break
      }
    }
    if (kind === "none" && keywords.has("json")) {
      kind = "json"
      body = literal(argument("json") ?? [])
    }
  }
  return makeCall("requests", method, url, kind, body, query, mediaType(literal(argument("headers") ?? [])))
}

export function pythonCalls(code: string): Call[] {
  const input = tokens(code)
  if (!input) return []
  const calls: Call[] = []
  for (let index = 0; index < input.length; index++) {
    const owner = input[index],
      method = input[index + 2]
    if (
      !owner ||
      !["requests", "httpx"].includes(owner.text) ||
      owner.kind !== "name" ||
      input[index - 1]?.text === "." ||
      input[index + 1]?.text !== "." ||
      !method ||
      !methods.has(method.text) ||
      input[index + 3]?.text !== "("
    )
      continue
    let end = index + 4,
      depth = 1
    for (; end < input.length; end++) {
      const text = input[end]?.text ?? ""
      if (text === "(") depth++
      if (text === ")" && --depth === 0) break
    }
    const call = readCall(owner.text, method.text, input.slice(index + 4, end))
    if (call) calls.push(call)
  }
  return calls
}
