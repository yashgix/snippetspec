"""Fill docs/index.html from tools/page_template.html and the generated results files.

python tools/build_page.py
"""

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUTATION_KINDS = ("remove_operation", "rename_field", "add_required", "rename_param", "drop_enum_value")


def bar(name, value, total, label, warn=False):
    width = 100 * value / total if total else 0
    cls = "fill warn" if warn else "fill"
    return (
        f'<div class="bar"><span class="n">{name}</span>'
        f'<span class="track"><span class="{cls}" style="display:block;width:{width:.1f}%"></span></span>'
        f'<span class="v">{label}</span></div>'
    )


def mutation_bars(metrics):
    rows = [
        bar(kind, metrics[f"mutation_{kind}_caught"], metrics[f"mutation_{kind}_cases"], _of(metrics, kind))
        for kind in MUTATION_KINDS
    ]
    for kind in ("add_optional", "add_enum_value"):
        rows.append(
            bar(
                f"{kind} (neutral)",
                metrics[f"mutation_{kind}_flagged"],
                metrics[f"mutation_{kind}_cases"],
                _flagged(metrics, kind),
                True,
            )
        )
    return "".join(rows)


def _of(metrics, kind):
    return f"{metrics[f'mutation_{kind}_caught']} of {metrics[f'mutation_{kind}_cases']}"


def _flagged(metrics, kind):
    return f"{metrics[f'mutation_{kind}_flagged']} flagged of {metrics[f'mutation_{kind}_cases']}"


def recall_bars(holdout):
    return "".join(
        bar(kind, c["caught"], c["cases"], f"{c['caught']} of {c['cases']}") for kind, c in holdout["by_kind"].items()
    )


def code_bars(holdout):
    codes = holdout["clean_problem_calls_by_code"]
    top = max(codes.values())
    rows = sorted(codes.items(), key=lambda item: -item[1])
    return "".join(bar(code, count, top, f"{count} calls", True) for code, count in rows)


def values(metrics, holdout, ledger):
    found = {
        **metrics,
        "ledger_same": Counter(case["code"] for case in ledger["cases"]).most_common(1)[0][1],
        "h_pages": holdout["pages"],
        "h_cases": holdout["cases"],
        "h_caught": holdout["caught"],
        "h_calls": holdout["calls"],
        "h_mismatch": holdout["calls_mismatch"],
        "h_partial": holdout["calls_partial"],
        "h_unparsed": holdout["unparsed_commands"],
    }
    found.update(mutation_bars=mutation_bars(metrics), recall_bars=recall_bars(holdout), code_bars=code_bars(holdout))
    return found


def render(template, found):
    return re.sub(r"\{\{(\w+)\}\}", lambda match: str(found[match.group(1)]), template)


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main():
    template = (ROOT / "tools" / "page_template.html").read_text(encoding="utf-8")
    found = values(load("results/metrics.json"), load("results/holdout.json"), load("study/ledger.json"))
    (ROOT / "docs" / "index.html").write_text(render(template, found), encoding="utf-8")


if __name__ == "__main__":
    main()
