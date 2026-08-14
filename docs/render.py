"""Render the project documents to PDF via the bundled Chromium.

    python docs/render.py            # all three
    python docs/render.py ceo        # one

Sources live here in the repository rather than in a scratch directory. An
earlier set was written to a temp folder, cleaned up, and left three PDFs that
could only be updated by rewriting them from scratch.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

from playwright.async_api import async_playwright

HERE = pathlib.Path(__file__).parent
OUT = HERE.parent

DOCUMENTS = {
    "briefing": ("briefing.html", "HRHUB-Project-Briefing.pdf", "HRHUB — Project Briefing"),
    "accuracy": (
        "accuracy-report.html",
        "TalentFinder-Accuracy-Report.pdf",
        "TalentFinder — Matching Accuracy, Measured",
    ),
    "ceo": ("ceo-report.html", "TalentFinder-CEO-Report.pdf", "TalentFinder — Status Report"),
}

FOOTER = """
<div style="width:100%;font-family:Segoe UI,sans-serif;font-size:7.5pt;color:#8a919b;
            padding:0 15mm;display:flex;justify-content:space-between;">
  <span>{title}</span><span class="pageNumber"></span>
</div>
"""


async def render(page, source: pathlib.Path, target: pathlib.Path, title: str) -> None:
    await page.goto(source.as_uri(), wait_until="load")
    await page.pdf(
        path=str(target),
        format="A4",
        print_background=True,
        display_header_footer=True,
        header_template="<div></div>",
        footer_template=FOOTER.format(title=title),
        margin={"top": "14mm", "bottom": "16mm", "left": "0", "right": "0"},
    )
    print(f"  {target.name}  ({target.stat().st_size / 1024:.0f} KB)")


async def main(names: list[str]) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        for name in names:
            source_name, target_name, title = DOCUMENTS[name]
            source = HERE / source_name
            if not source.exists():
                print(f"  skipped {name}: {source_name} not found")
                continue
            await render(page, source, OUT / target_name, title)
        await browser.close()


if __name__ == "__main__":
    requested = sys.argv[1:] or list(DOCUMENTS)
    unknown = [n for n in requested if n not in DOCUMENTS]
    if unknown:
        raise SystemExit(f"unknown document(s): {', '.join(unknown)}")
    asyncio.run(main(requested))
