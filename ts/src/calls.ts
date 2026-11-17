import ts from "typescript"
import type { Example } from "./examples.js"
import { pythonCalls } from "./python.js"
import { queryPairs, splitUrl } from "./url.js"
import { isObject, UNKNOWN, type Value } from "./values.js"

export interface Call {
  readonly tool: "curl" | "fetch" | "requests"
  readonly method: string
  readonly url: string
  readonly query: [string, string][]
  readonly body_kind: "none" | "json" | "form" | "unparsed"
  readonly body: Value
  readonly media: string | null
}

type InputExample = Pick<Example, "language" | "code">
const shellLanguages = new Set(["bash", "sh", "shell", "zsh", "console", "terminal"])
const jsLanguages = new Set(["javascript", "js", "jsx", "typescript", "ts", "tsx"])

export function findCalls(example: InputExample): Call[] {
  const language = example.language.toLowerCase()
  if (shellLanguages.has(language)) return shell(example.code).calls
  if (jsLanguages.has(language)) return javascript(example.code, language)
  if (["python", "py"].includes(language)) return pythonCalls(example.code)
  return []
}

export function unparsedCommands(example: InputExample): string[] {
  return shellLanguages.has(example.language.toLowerCase()) ? shell(example.code).unparsed : []
}

export function mediaType(headers: Value): string | null {
  const pairs = Array.isArray(headers)
    ? headers.flatMap((header) => {
        if (typeof header !== "string") return []
        const colon = header.indexOf(":")
        return [[colon < 0 ? header : header.slice(0, colon), colon < 0 ? "" : header.slice(colon + 1)]]
      })
    : isObject(headers)
      ? Object.entries(headers)
      : []
  for (const [name, value] of pairs) {
    if (String(name).trim().toLowerCase() === "content-type" && typeof value === "string")
      return value.split(";")[0]?.trim().toLowerCase() || null
  }
  return null
}

export function makeCall(
  tool: Call["tool"],
  method: string,
  url: string,
  body_kind: Call["body_kind"] = "none",
  body: Value = null,
  extra: [string, string][] = [],
  media: string | null = null,
): Call | null {
  const parts = splitUrl(url)
  return parts
    ? { tool, method: method.toUpperCase(), url, query: [...queryPairs(parts.query), ...extra], body_kind, body, media }
    : null
}

export function shellWords(command: string): string[] | null {
  const words: string[] = []
  let word = "",
    quote = "",
    started = false
  for (let index = 0; index < command.length; index++) {
    const char = command[index] ?? ""
    if (!quote && char === "#") {
      const newline = command.indexOf("\n", index)
      if (newline < 0) break
      index = newline - 1
      continue
    }
    if (!quote && /[ \t\r\n]/.test(char)) {
      if (started) words.push(word)
      word = ""
      started = false
      continue
    }
    started = true
    if (quote === "'") {
      if (char === quote) quote = ""
      else word += char
    } else if (char === "\\") {
      const next = command[++index]
      if (next === undefined) return null
      word += quote === '"' && next !== '"' && next !== "\\" ? `\\${next}` : next
    } else if (quote) {
      if (char === quote) quote = ""
      else word += char
    } else if (char === "'" || char === '"') quote = char
    else word += char
  }
  if (quote) return null
  if (started) words.push(word)
  return words
}

function ansiString(text: string, start: number): [string, number] {
  let end = start
  while (end < text.length && text[end] !== "'") end += text[end] === "\\" ? 2 : 1
  const escapes: Record<string, string> = { n: "\n", t: "\t", r: "\r", "\\": "\\", "'": "'", '"': '"' }
  const body = text
    .slice(start, end)
    .replace(/\\(x[\da-fA-F]{2}|u[\da-fA-F]{4}|[\s\S])/g, (all: string, code: string) =>
      /^[xu]/.test(code) && code.length > 1
        ? String.fromCodePoint(Number.parseInt(code.slice(1), 16))
        : (escapes[code] ?? all),
    )
  return [body, end + 1]
}

function commands(text: string): string[] {
  const out: string[] = []
  let current = "",
    quote = ""
  for (let index = 0; index < text.length; index++) {
    const char = text[index] ?? ""
    if (quote) {
      if (char === "\\" && quote === '"' && index + 1 < text.length) current += char + text[++index]
      else {
        if (char === quote) quote = ""
        current += char
      }
    } else if (char === "\\" && index + 1 < text.length) current += char + text[++index]
    else if (char === "$" && text[index + 1] === "'") {
      const [body, end] = ansiString(text, index + 2)
      current += `'${body.replace(/'/g, `'"'"'`)}'`
      index = end - 1
    } else if (char === "'" || char === '"') {
      quote = char
      current += char
    } else if (";&|<>\n".includes(char)) {
      out.push(current)
      current = ""
    } else current += char
  }
  out.push(current)
  return out
}

function shell(code: string): { calls: Call[]; unparsed: string[] } {
  const calls: Call[] = [],
    unparsed: string[] = []
  const text = code.replace(/\\\n/g, " ").replace(/\\\s*$/, "")
  for (const command of commands(text)) {
    const words = shellWords(command)
    if (words === null) {
      if (/^\s*(\$\s+)?\$?curl\b/.test(command)) unparsed.push(command.trim())
    } else calls.push(...curl(words))
  }
  return { calls, unparsed }
}

const longArguments = new Set([
  "request",
  "header",
  "url",
  "data",
  "data-raw",
  "data-binary",
  "data-ascii",
  "data-urlencode",
  "json",
  "form",
  "form-string",
  "output",
  "user",
  "user-agent",
  "referer",
  "cookie",
  "cookie-jar",
  "write-out",
  "max-time",
  "connect-timeout",
  "retry",
  "upload-file",
  "config",
  "proxy",
  "range",
  "cacert",
  "cert",
])
const shortOptions: Record<string, string> = { X: "request", H: "header", d: "data", F: "form", G: "get", I: "head" }
function urlencode(value: string): string {
  const pos = value.indexOf("=")
  const encode = (text: string) =>
    new URLSearchParams([["", text]]).toString().slice(1).replace(/%7E/gi, "~").replace(/\*/g, "%2A")
  if (pos < 0) return encode(value)
  const name = value.slice(0, pos),
    content = value.slice(pos + 1)
  if (content.startsWith("@")) return `${name}={?}`
  return name ? `${name}=${encode(content)}` : encode(content)
}

function curl(input: string[]): Call[] {
  const words = input[0] === "$" ? input.slice(1) : input
  if (words[0]?.replace(/^\$+/, "") !== "curl") return []
  let method: string | null = null,
    get = false,
    head = false,
    json = false
  const headers: string[] = [],
    data: string[] = [],
    forms: string[] = [],
    urls: string[] = []
  function assign(name: string, value = ""): void {
    if (name === "request") method = value
    else if (name === "header") headers.push(value)
    else if (name === "url") urls.push(value)
    else if (name === "json") {
      json = true
      data.push(value)
    } else if (["data", "data-raw", "data-binary", "data-ascii"].includes(name)) data.push(value)
    else if (name === "data-urlencode") data.push(urlencode(value))
    else if (["form", "form-string"].includes(name)) forms.push(value)
    else if (name === "get") get = true
    else if (name === "head") head = true
  }
  for (let index = 1; index < words.length; index++) {
    const word = words[index] ?? ""
    if (word.startsWith("--") && word.length > 2) {
      const equals = word.indexOf("=")
      const name = word.slice(2, equals < 0 ? undefined : equals)
      if (equals >= 0) {
        if (longArguments.has(name)) assign(name, word.slice(equals + 1))
      } else if (longArguments.has(name)) assign(name, words[++index] ?? "")
      else assign(name)
    } else if (word.startsWith("-") && word.length > 1) {
      for (let position = 1; position < word.length; position++) {
        const letter = word[position] ?? "",
          name = shortOptions[letter]
        if ("XHdFouAebcwmTKxr".includes(letter)) {
          const value = position + 1 < word.length ? word.slice(position + 1) : (words[++index] ?? "")
          if (name) assign(name, value)
          break
        }
        if (name) assign(name)
      }
    } else urls.push(word)
  }
  const payload = data.join("&")
  let kind: Call["body_kind"] = "none",
    body: Value = null,
    media: string | null = null
  let extra: [string, string][] = []
  if (get) {
    extra = queryPairs(payload)
    method ||= "GET"
  } else {
    method ||= head ? "HEAD" : data.length || forms.length ? "POST" : "GET"
    media = mediaType(headers) ?? (json ? "application/json" : null)
    if (forms.length) {
      kind = "form"
      body = Object.fromEntries(
        forms.map((item) => {
          const pos = item.indexOf("="),
            name = pos < 0 ? item : item.slice(0, pos),
            value = item.slice(pos + 1)
          return [name, pos < 0 || value.startsWith("@") || value.startsWith("<") ? UNKNOWN : value]
        }),
      )
    } else if (data.length) {
      if (payload.startsWith("@")) kind = "unparsed"
      else if (
        json ||
        headers.some(
          (header) => /^content-type\s*:/i.test(header.trim()) && /json/i.test(header.slice(header.indexOf(":") + 1)),
        ) ||
        /^[[{]/.test(payload.trimStart())
      ) {
        try {
          body = JSON.parse(payload) as Value
          kind = "json"
        } catch {
          kind = "unparsed"
        }
      } else {
        kind = "form"
        body = Object.fromEntries(queryPairs(payload, false))
      }
    }
  }
  return urls.flatMap((url) => {
    const call = makeCall("curl", method ?? "GET", url, kind, body, extra, media)
    return call ? [call] : []
  })
}

function jsValue(node: ts.Node | undefined, source: ts.SourceFile): Value {
  if (!node) return UNKNOWN
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text
  if (ts.isTemplateExpression(node)) {
    let value = node.head.text
    for (const span of node.templateSpans) value += `{${span.expression.getText(source).trim()}}${span.literal.text}`
    return value
  }
  if (ts.isNumericLiteral(node)) return Number(node.text.replace(/_/g, ""))
  if (
    ts.isPrefixUnaryExpression(node) &&
    (node.operator === ts.SyntaxKind.MinusToken || node.operator === ts.SyntaxKind.PlusToken) &&
    ts.isNumericLiteral(node.operand)
  )
    return (node.operator === ts.SyntaxKind.MinusToken ? -1 : 1) * Number(node.operand.text.replace(/_/g, ""))
  if (node.kind === ts.SyntaxKind.TrueKeyword) return true
  if (node.kind === ts.SyntaxKind.FalseKeyword) return false
  if (node.kind === ts.SyntaxKind.NullKeyword) return null
  if (ts.isArrayLiteralExpression(node)) return node.elements.map((item) => jsValue(item, source))
  if (ts.isObjectLiteralExpression(node)) {
    const entries: [string, Value][] = []
    for (const property of node.properties) {
      if (ts.isSpreadAssignment(property) || !property.name || ts.isComputedPropertyName(property.name)) return UNKNOWN
      const key =
        ts.isIdentifier(property.name) || ts.isStringLiteral(property.name) || ts.isNumericLiteral(property.name)
          ? property.name.text
          : null
      if (key === null) return UNKNOWN
      entries.push([key, ts.isPropertyAssignment(property) ? jsValue(property.initializer, source) : UNKNOWN])
    }
    return Object.fromEntries(entries)
  }
  return UNKNOWN
}

function fetchCall(node: ts.CallExpression, source: ts.SourceFile): Call | null {
  const url = jsValue(node.arguments[0], source)
  if (typeof url !== "string") return null
  if (node.arguments.length < 2) return makeCall("fetch", "GET", url)
  const optionsNode = node.arguments[1]
  const options = jsValue(optionsNode, source)
  if (!isObject(options) || !optionsNode || !ts.isObjectLiteralExpression(optionsNode)) return null
  const method = Object.hasOwn(options, "method") ? options.method : "GET"
  if (typeof method !== "string") return null
  let kind: Call["body_kind"] = "none",
    body: Value = null
  if (Object.hasOwn(options, "body") && options.body !== null) {
    const property = [...optionsNode.properties]
      .reverse()
      .find(
        (item) =>
          item.name && (ts.isIdentifier(item.name) || ts.isStringLiteral(item.name)) && item.name.text === "body",
      )
    const expression = property && ts.isPropertyAssignment(property) ? property.initializer : undefined
    if (
      expression &&
      ts.isCallExpression(expression) &&
      ts.isPropertyAccessExpression(expression.expression) &&
      expression.expression.expression.getText(source) === "JSON" &&
      expression.expression.name.text === "stringify"
    ) {
      kind = "json"
      body = jsValue(expression.arguments[0], source)
    } else if (typeof options.body === "string") {
      try {
        body = JSON.parse(options.body) as Value
        kind = "json"
      } catch {
        kind = "unparsed"
      }
    } else kind = "unparsed"
  }
  return makeCall("fetch", method, url, kind, body, [], mediaType((options.headers ?? {}) as Value))
}

function javascript(code: string, language: string): Call[] {
  const source = ts.createSourceFile(
    `example.${language}`,
    code,
    ts.ScriptTarget.Latest,
    true,
    ["jsx", "tsx"].includes(language) ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  )
  const calls: Call[] = []
  function walk(node: ts.Node): void {
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "fetch" &&
      !node.questionDotToken &&
      !node.typeArguments
    ) {
      const call = fetchCall(node, source)
      if (call) calls.push(call)
    }
    if (!ts.isTemplateExpression(node)) ts.forEachChild(node, walk)
  }
  walk(source)
  return calls
}
