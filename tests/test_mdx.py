import unittest
from dataclasses import FrozenInstanceError

from snippetcheck.mdx import Example, extract


def codes(examples):
    return [example.code for example in examples]


def groups(examples):
    return [example.group for example in examples]


class ExampleTest(unittest.TestCase):
    def test_fields_and_frozen(self):
        example = Example("p.mdx", 2, "bash", None, None, "curl x", None)
        self.assertEqual((example.page, example.line, example.language), ("p.mdx", 2, "bash"))
        self.assertEqual(example.code, "curl x")
        self.assertIsNone(example.meta)
        self.assertIsNone(example.title)
        self.assertIsNone(example.group)
        with self.assertRaises(FrozenInstanceError):
            example.page = "other.mdx"

    def test_empty_page_has_no_examples(self):
        self.assertEqual(extract(""), [])
        self.assertEqual(extract("just prose\nand more"), [])


class FenceTest(unittest.TestCase):
    def test_backtick_fence(self):
        examples = extract("```bash\ncurl -s https://x/y\n```\n", "page.mdx")
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0].page, "page.mdx")
        self.assertEqual(examples[0].line, 1)
        self.assertEqual(examples[0].language, "bash")
        self.assertEqual(examples[0].code, "curl -s https://x/y")

    def test_page_defaults_to_empty_string(self):
        self.assertEqual(extract("```\nx\n```")[0].page, "")

    def test_tilde_fence(self):
        self.assertEqual(codes(extract("~~~python\nprint(1)\n~~~")), ["print(1)"])

    def test_closing_fence_needs_the_same_character_and_length(self):
        text = "````\na\n~~~\nb\n```\nc\n`````\nd"
        examples = extract(text)
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0].code, "a\n~~~\nb\n```\nc")

    def test_closing_fence_may_be_indented_with_trailing_spaces(self):
        self.assertEqual(codes(extract("  ```\nx\n   ```  \nafter")), ["x"])

    def test_unclosed_fence_runs_to_the_end(self):
        self.assertEqual(codes(extract("```\na\n\nb")), ["a\n\nb"])

    def test_empty_block(self):
        self.assertEqual(codes(extract("```\n```")), [""])

    def test_backtick_info_may_not_contain_a_backtick(self):
        self.assertEqual(extract("```a`b\ntext"), [])
        self.assertEqual(len(extract("~~~a`b\ntext\n~~~")), 1)

    def test_indent_is_removed_from_content_lines(self):
        self.assertEqual(codes(extract("  ```\n    a\n  b\n c\n  ```")), ["  a\nb\nc"])

    def test_line_numbers_are_one_based(self):
        text = "\n\n```\na\n```\n\n```\nb\n```"
        self.assertEqual([example.line for example in extract(text)], [3, 7])

    def test_two_character_lines_do_not_open_a_fence(self):
        self.assertEqual(extract("``x\ntext\n``"), [])


class InfoTest(unittest.TestCase):
    def test_default_language_and_no_meta(self):
        example = extract("```\nx\n```")[0]
        self.assertEqual((example.language, example.meta, example.title), ("text", None, None))

    def test_language_then_meta_and_title(self):
        example = extract('```typescript title="Add a memory" {1}\nx\n```')[0]
        self.assertEqual(example.language, "typescript")
        self.assertEqual(example.meta, 'title="Add a memory" {1}')
        self.assertEqual(example.title, "Add a memory")

    def test_single_quoted_title(self):
        self.assertEqual(extract("```bash title='hi there'\nx\n```")[0].title, "hi there")

    def test_bare_title_value(self):
        self.assertEqual(extract("```bash title=setup.md\nx\n```")[0].title, "setup.md")
        self.assertEqual(extract("```bash copies=1 title=x\nx\n```")[0].title, "x")

    def test_meta_without_a_title(self):
        example = extract("```bash other=1\nx\n```")[0]
        self.assertEqual(example.meta, "other=1")
        self.assertIsNone(example.title)

    def test_double_quoted_title_wins_over_single_quoted(self):
        example = extract("""```bash title='b' title="a"\nx\n```""")[0]
        self.assertEqual(example.title, "a")


class GroupTest(unittest.TestCase):
    def test_blocks_outside_containers_have_no_group(self):
        self.assertEqual(groups(extract("```bash\ncurl a\n```")), [None])

    def test_alternatives_container_numbers_its_blocks(self):
        text = (
            '<Tabs>\n<Tab title="a">\n```bash\ncurl a\n```\n</Tab>\n'
            '<Tab title="b">\n```bash\ncurl b\n```\n</Tab>\n</Tabs>\n'
            "```bash\ncurl c\n```\n"
            "<CodeGroup>\n```bash\ncurl d\n```\n</CodeGroup>\n"
        )
        self.assertEqual(groups(extract(text)), [0, 0, None, 1])

    def test_nested_containers_share_the_outermost_group(self):
        text = "<CodeGroup>\n<Tabs>\n```js\na\n```\n</Tabs>\n```js\nb\n```\n</CodeGroup>\n"
        self.assertEqual(groups(extract(text)), [0, 0])

    def test_each_container_gets_the_next_number(self):
        text = "<Tabs>\n```\na\n```\n</Tabs>\n<ViewGroup>\n```\nb\n```\n</ViewGroup>\n"
        self.assertEqual(groups(extract(text)), [0, 1])

    def test_container_attributes_are_allowed(self):
        text = '<CodeGroup title="x">\n```\na\n```\n</CodeGroup>\n'
        self.assertEqual(groups(extract(text)), [0])

    def test_self_closing_container_does_not_open(self):
        text = "<Tabs />\n```\na\n```\n<CodeBlockTabs/>\n```\nb\n```\n"
        self.assertEqual(groups(extract(text)), [None, None])

    def test_tags_inside_a_block_are_not_read(self):
        text = "```md\n<Tabs>\n```\n```bash\ncurl a\n```\n"
        examples = extract(text)
        self.assertEqual(groups(examples), [None, None])
        self.assertEqual([example.language for example in examples], ["md", "bash"])

    def test_stray_closing_tag_is_ignored(self):
        self.assertEqual(groups(extract("</Tabs>\n```\na\n```\n")), [None])

    def test_unclosed_container_keeps_its_group(self):
        self.assertEqual(groups(extract("<Tabs>\n```\na\n```\n")), [0])

    def test_container_name_must_be_followed_by_space_or_bracket(self):
        text = "<TabsExtra>\n```\na\n```\n</TabsExtra>\n"
        self.assertEqual(groups(extract(text)), [None])


if __name__ == "__main__":
    unittest.main()
