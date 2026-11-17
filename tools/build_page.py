"""Fill docs/index.html from tools/page_template.html, the generated results files and study/survey.json.

python tools/build_page.py
"""

import json
import re
from collections import Counter
from html import escape
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


SITE_PARTS = (("ok", "ok"), ("partial", "partial"), ("endpoint_not_in_spec", "gap"), ("field_level", "field"))


def site_rows(sites):
    top = max(site["calls"] for site in sites)
    rows = []
    for site in sites:
        parts = "".join(
            f'<span class="seg {cls}" style="width:{100 * site[key] / top:.2f}%"></span>' for key, cls in SITE_PARTS
        )
        label = f"{site['calls']} calls, {site['field_level']} field-level"
        name = escape(site["site"])
        alt = (
            f"{name}: {site['ok']} ok, {site['partial']} partial, "
            f"{site['endpoint_not_in_spec']} endpoint not in spec, {site['field_level']} field-level"
        )
        rows.append(
            f'<div class="srow"><span class="n">{name}</span>'
            f'<span class="segs" role="img" aria-label="{alt}">{parts}</span><span class="v">{label}</span></div>'
        )
    return "".join(rows)


def review_bars(review):
    top = max(row["count"] for row in review)
    return "".join(
        f'<div class="bar"><span class="n">{escape(row["label"])}</span><span class="track">'
        f'<span class="fill {row["kind"]}" style="display:block;width:{100 * row["count"] / top:.1f}%"></span></span>'
        f'<span class="v">{row["count"]} calls</span></div>'
        for row in review
    )


def compare(finding):
    caption = (
        f'<b>{finding["company"]}</b> &middot; <a href="{finding["docs_url"]}">{finding["page"]}</a>'
        f" &middot; <code>{escape(finding['call'])}</code>"
    )
    sides = (
        f'<div class="side bad"><span>The example sends</span><pre>{escape(finding["docs_send"])}</pre></div>'
        f'<div class="side good"><span>The API expects</span><pre>{escape(finding["api_expects"])}</pre></div>'
    )
    source = (
        f'Docs source: <a href="{finding["source"]}">pinned line</a>. Checked against '
        f'<a href="{finding["evidence"]}">{escape(finding["evidence_label"])}</a>. {escape(finding["verified"])}'
    )
    return (
        f'<figure class="finding"><figcaption>{caption}</figcaption><div class="compare">{sides}</div>'
        f'<p>{escape(finding["what"])}</p><p class="small muted">{source}</p></figure>'
    )


def findings_table(findings):
    rows = "".join(
        f'<tr><td>{f["company"]}</td><td><a href="{f["source"]}">{f["page"]}</a></td><td>{escape(f["what"])}</td>'
        f'<td><a href="{f["evidence"]}">{escape(f["evidence_label"])}</a></td></tr>'
        for f in findings
    )
    head = "<tr><th>Product</th><th>Docs page</th><th>What disagrees</th><th>Checked against</th></tr>"
    return f'<div class="table-wrap"><table><thead>{head}</thead><tbody>{rows}</tbody></table></div>'


def survey_values(survey):
    totals, funnel = survey["totals"], survey["funnel"]
    findings = survey["findings"]
    return {
        **{f"s_{key}": f"{value:,}" for key, value in totals.items()},
        **{f"f_{key}": value for key, value in funnel.items()},
        "s_date": survey["date"],
        "s_found": len(findings),
        "s_companies": len({f["company"] for f in findings}),
        "s_field_sites": sum(1 for site in survey["sites"] if site["field_level"]),
        "site_rows": site_rows(survey["sites"]),
        "review_bars": review_bars(survey["field_level_review"]),
        "featured": compare(findings[0]) + compare(findings[2]),
        "findings_table": findings_table(findings),
    }


def values(metrics, holdout, ledger):
    found = {
        **metrics,
        "ledger_same": Counter(case["code"] for case in ledger["cases"]).most_common(1)[0][1],
        "h_pages": holdout["pages"],
        "h_cases": holdout["cases"],
        "h_caught": holdout["caught"],
        "h_calls": holdout["calls"],
        "h_mismatch": holdout["calls_mismatch"],
        "h_mismatch_pct": round(100 * holdout["calls_mismatch"] / holdout["calls"]),
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
    found.update(survey_values(load("study/survey.json")))
    (ROOT / "docs" / "index.html").write_text(render(template, found), encoding="utf-8")


if __name__ == "__main__":
    main()
