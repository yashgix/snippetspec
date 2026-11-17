import { isIP } from "node:net"

export function splitUrl(url: string): { host: string | null; path: string; query: string } | null {
  try {
    // WHATWG URL normalizes dot segments and encodes placeholders that Python keeps verbatim.
    let start = 0
    while (start < url.length && url.charCodeAt(start) <= 32) start++
    const clean = url.slice(start).replace(/[\t\r\n]/g, "")
    const parts = /^(https?):\/\/([^/?#]*)([^?#]*)(?:\?([^#]*))?/i.exec(clean)
    if (!parts) return null
    const authority = parts[2] ?? ""
    const address = authority.slice(authority.lastIndexOf("@") + 1)
    let host: string
    if (address.startsWith("[")) {
      const end = address.indexOf("]")
      if (end < 0) return null
      host = address.slice(1, end)
      if (!isIP(host.split("%")[0] ?? "") && !/^v[0-9a-f]+\..+$/i.test(host)) return null
    } else {
      if (/[[\]]/.test(address)) return null
      host = address.split(":")[0] ?? ""
    }
    host = host.toLowerCase()
    if (!host) return null
    return { host, path: parts[3] ?? "", query: parts[4] ?? "" }
  } catch {
    return null
  }
}

export function queryPairs(text: string, keepBlank = true): [string, string][] {
  return [...new URLSearchParams(text)].filter(([, value]) => keepBlank || value !== "")
}

export function unquote(text: string): string {
  return new URLSearchParams(`v=${text.replace(/\+/g, "%2B").replace(/&/g, "%26")}`).get("v") ?? ""
}
