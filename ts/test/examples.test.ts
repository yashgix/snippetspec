import { expect, test } from "vitest"
import { extract, parsePage } from "../src/examples.js"
import { extractCodeExamplesFromMdast } from "../vendor/margin/code-examples.js"

test.each(["CodeBlockTabs", "Tabs", "CodeGroup", "CodeTabs", "ViewGroup"])(
  "nested %s uses the outer group",
  (container) => {
    const text = `<${container}>\n<Tabs>\n\n~~~ts title="first" extra\na\n~~~\n\n</Tabs>\n\n~~~js\nb\n~~~\n\n</${container}>\n\n~~~\nc\n~~~\n\n<CodeGroup>\n\n~~~py\nd\n~~~\n\n</CodeGroup>`
    const examples = extract(text, "p.mdx")
    expect(examples.map((example) => example.alternativesGroup)).toEqual([0, 0, undefined, 1])
    expect(examples[0]).toMatchObject({
      line: 4,
      language: "ts",
      meta: 'title="first" extra',
      title: "first",
      code: "a",
    })
    expect(examples.map(({ line: _line, ...example }) => example)).toEqual(
      extractCodeExamplesFromMdast(parsePage(text)),
    )
  },
)

test("Markdown uses CommonMark HTML and literal braces instead of MDX expressions", () => {
  const text =
    "A literal { and <https://example.com>.\n\n<Tabs>\n\n```sh title='run it'\ncurl https://x/a\n```\n\n</Tabs>"
  const examples = extract(text, "p.md")
  expect(examples).toHaveLength(1)
  expect(examples[0]).toMatchObject({ language: "sh", title: "run it", line: 5, alternativesGroup: undefined })
  expect(() => extract(text, "p.mdx")).toThrow()
})

test("blockquotes and list fences retain source positions", () => {
  const text = "> ```bash\n> curl https://x/a\n> ```\n\n- item\n\n  ```js\n  fetch('https://x/b')\n  ```"
  expect(extract(text, "p.md").map(({ line, code }) => [line, code])).toEqual([
    [1, "curl https://x/a"],
    [7, "fetch('https://x/b')"],
  ])
})

test("title precedence, empty titles, longer fences and unclosed blocks follow Margin", () => {
  const text = '````ts title=bare title=\'single\' title="double"\nx\n```\n````\n\n~~~text title=""\ny'
  const examples = extract(text)
  expect(examples.map(({ line: _line, ...example }) => example)).toEqual(extractCodeExamplesFromMdast(parsePage(text)))
  expect(examples.map((example) => example.title)).toEqual(["double", '""'])
  expect(examples.map((example) => example.code)).toEqual(["x\n```", "y"])
})
