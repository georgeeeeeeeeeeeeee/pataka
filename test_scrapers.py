"""
Comprehensive scraper audit: tests every configured scraper live,
reports result counts, data quality, and flags issues.
"""
import sys
import io

# Force UTF-8 output on Windows to handle Māori macrons etc.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import time
import traceback
import logging
from config import FUNDER_SOURCES
from scrapers import SCRAPER_REGISTRY, get_scraper

# Minimal logging so we can see warnings without noise
logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

results_summary = []


def check_opp(opp, i):
    """Return list of quality issues with a single opportunity."""
    issues = []
    if not opp.grant_name or len(opp.grant_name.strip()) < 4:
        issues.append("missing/short grant_name")
    if not opp.url or not opp.url.startswith("http"):
        issues.append(f"bad url: {opp.url!r:.60}")
    if not opp.description and not opp.raw_html:
        issues.append("no description or raw_html")
    if opp.description and len(opp.description) < 20:
        issues.append("very short description")
    return issues


def run_scraper(source_config):
    scraper_id = source_config.get("scraper", source_config["id"])
    name = source_config["name"]
    sid = source_config["id"]

    print(f"\n{'='*60}")
    print(f"  {name}  [{sid} -> {scraper_id}]")
    print(f"{'='*60}")

    # Check registry
    if scraper_id not in SCRAPER_REGISTRY:
        print(f"  {FAIL}: scraper_id '{scraper_id}' not in SCRAPER_REGISTRY")
        results_summary.append((name, FAIL, 0, [f"scraper '{scraper_id}' not found in registry"]))
        return

    t0 = time.time()
    try:
        scraper = get_scraper(scraper_id, source_config)
        opps = scraper.scrape()
        elapsed = time.time() - t0
    except Exception as e:
        elapsed = time.time() - t0
        tb = traceback.format_exc()
        print(f"  {FAIL}: exception after {elapsed:.1f}s")
        print(f"  {tb}")
        results_summary.append((name, FAIL, 0, [f"exception: {e}"]))
        return

    n = len(opps)
    all_issues = []

    for i, opp in enumerate(opps):
        issues = check_opp(opp, i)
        if issues:
            all_issues.append(f"  opp[{i}] '{opp.grant_name[:50]}': {', '.join(issues)}")

    # Flag if only fallback (single result with funder-level name)
    fallback_only = (
        n == 1
        and opps[0].grant_name.endswith("— Funding Opportunities")
        or (n == 1 and not opps[0].url.startswith("http"))
    )

    # Report
    print(f"  Elapsed : {elapsed:.1f}s")
    print(f"  Results : {n} opportunities")

    if n == 0:
        status = FAIL
        print(f"  {FAIL}: returned 0 results")
    elif fallback_only:
        status = WARN
        print(f"  {WARN}: only 1 fallback/whole-page result (scraper couldn't parse listings)")
    elif n == 1:
        status = WARN
        print(f"  {WARN}: only 1 result — possible parse failure or JS-required site")
    else:
        status = PASS
        print(f"  {PASS}")

    for issue in all_issues[:5]:  # cap to avoid wall-of-text
        print(f"  QA: {issue}")
    if len(all_issues) > 5:
        print(f"  QA: ... and {len(all_issues)-5} more issues")

    # Sample first result
    if opps:
        o = opps[0]
        print(f"\n  Sample [0]:")
        print(f"    name : {o.grant_name[:80]}")
        print(f"    url  : {o.url[:100]}")
        print(f"    desc : {(o.description or '')[:120]}")
        if o.amount_text:
            print(f"    amt  : {o.amount_text}")
        if o.deadline_text:
            print(f"    dead : {o.deadline_text}")

    results_summary.append((name, status, n, all_issues))


# GETS tests removed — procurement scraping moved to TenderPulse NZ


def audit_registry():
    """Check for scrapers in registry not used by any source config."""
    print(f"\n{'='*60}")
    print("  REGISTRY AUDIT")
    print(f"{'='*60}")

    configured_scrapers = {s.get("scraper", s["id"]) for s in FUNDER_SOURCES}

    issues = []
    for key in SCRAPER_REGISTRY:
        if key not in configured_scrapers:
            issues.append(f"  WARN: '{key}' is in SCRAPER_REGISTRY but not used by any FUNDER_SOURCES entry")

    for source in FUNDER_SOURCES:
        scraper_id = source.get("scraper", source["id"])
        if scraper_id not in SCRAPER_REGISTRY:
            issues.append(f"  FAIL: source '{source['id']}' references scraper '{scraper_id}' which is NOT in SCRAPER_REGISTRY")

    if not issues:
        print("  All registry entries match FUNDER_SOURCES. OK.")
    else:
        for i in issues:
            print(i)
    return issues


def print_summary():
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    total = len(results_summary)
    passed = sum(1 for _, s, _, _ in results_summary if s == PASS)
    warned = sum(1 for _, s, _, _ in results_summary if s == WARN)
    failed = sum(1 for _, s, _, _ in results_summary if s == FAIL)

    for name, status, n, issues in results_summary:
        flag = {"PASS": "OK ", "WARN": "?? ", "FAIL": "XX "}[status]
        print(f"  {flag} {name:<40} {n:>3} results")

    print(f"\n  {passed}/{total} passed, {warned} warnings, {failed} failures")


if __name__ == "__main__":
    print("Pātaka — Scraper Audit")
    print(f"Testing {len(FUNDER_SOURCES)} configured sources\n")

    registry_issues = audit_registry()

    for source in FUNDER_SOURCES:
        if not source.get("enabled", True):
            print(f"\nSKIP (disabled): {source['name']}")
            continue
        run_scraper(source)

    print_summary()

    if any(s == FAIL for _, s, _, _ in results_summary) or registry_issues:
        sys.exit(1)
