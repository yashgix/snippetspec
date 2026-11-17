import type { Root, RootContent } from "mdast"
import { remark } from "remark"
import remarkGfm from "remark-gfm"
import remarkMdx from "remark-mdx"

export interface Example {
  language: string
  title?: string
  meta?: string
  code: string
  alternativesGroup?: number
  line: number
}

const alternatives = new Set(["CodeBlockTabs", "Tabs", "CodeGroup", "CodeTabs", "ViewGroup"])
const markdown = remark().use(remarkGfm)
const mdx = remark().use(remarkMdx).use(remarkGfm)

export function parsePage(text: string, page = ""): Root {
  return (page.toLowerCase().endsWith(".md") ? markdown : mdx).parse(text)
}

export function extract(text: string, page = ""): Example[] {
  const out: Example[] = []
  let nextGroup = 0
  function walk(node: Root | RootContent, group?: number): void {
    let current = group
    if (
      (node.type === "mdxJsxFlowElement" || node.type === "mdxJsxTextElement") &&
      typeof node.name === "string" &&
      alternatives.has(node.name) &&
      current === undefined
    )
      current = nextGroup++
    if (node.type === "code") {
      const meta = node.meta ?? undefined
      const title =
        meta?.match(/title="([^"]+)"/) ?? meta?.match(/title='([^']+)'/) ?? meta?.match(/(?:^|\s)title=([^\s]+)/)
      out.push({
        language: node.lang ?? "text",
        title: title?.[1],
        meta,
        code: node.value,
        alternativesGroup: current,
        line: node.position?.start.line ?? 1,
      })
      return
    }
    if ("children" in node) for (const child of node.children) walk(child, current)
  }
  walk(parsePage(text, page))
  return out
}
