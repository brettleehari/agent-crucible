# SPDX-License-Identifier: Apache-2.0
"""The analytical survival report for a suites run — summary, heatmap, evidence.

A suites run produces one verdict per scenario across many domains. This renders
them the way a decision-maker reads them: the fail-closed verdict first; then the
question that actually guides remediation — *is a failure systemic (a failure mode
that fails everywhere) or local (a domain that fails on everything)?* — answered by
a **failure-mode × domain heatmap**; then the per-scenario evidence underneath.

Everything shown is a **count or a pass/fail**, never a graded score (Spine C3):
"money_leak sprang in 6 of 6 domains" is a fact about coverage, not a grade.

Example::

    html = render_suites_report(arena.scenario_results(), agent_label="hermes", seed=0)
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from crucible.mcp_arena import ScenarioResult
from crucible.suites import SUITES_BY_ID, Scenario
from crucible.tripwires import TRIPWIRES, TripwireStatus

_S = TripwireStatus.SPRUNG
_H = TripwireStatus.HELD
_N = TripwireStatus.NOT_ARMED
_SEVERITY = {None: 0, _N: 1, _H: 2, _S: 3}
_CELL_CLASS = {None: "none", _N: "na", _H: "held", _S: "sprung"}


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _cell_status(results: Sequence[ScenarioResult], suite: str, trap: str) -> TripwireStatus | None:
    """Worst status among a suite's scenarios for one trap (None if it has none)."""
    worst: TripwireStatus | None = None
    for r in results:
        if (
            r.scenario.suite == suite
            and r.scenario.trap == trap
            and _SEVERITY[r.status] > _SEVERITY[worst]
        ):
            worst = r.status
    return worst


def render_suites_report(
    results: Sequence[ScenarioResult],
    *,
    agent_label: str,
    seed: int,
    trials: int = 1,
    prevalence: dict[Scenario, tuple[int, int]] | None = None,
) -> str:
    """Return a standalone analytical HTML report for a suites run.

    Pass ``trials`` > 1 and ``prevalence`` (scenario -> ``(sprung_k, N)``) to render a
    fail-closed multi-trial run of a *stochastic* agent: each cell stays a fail-closed
    pass/fail, and the evidence shows how often it sprang — ``k of N`` (C7), never a score.

    Example::

        Path("report.html").write_text(render_suites_report(results, agent_label="x", seed=0))
    """
    prev = prevalence or {}
    total = len(results)
    sprung = sum(1 for r in results if r.status is _S)
    not_armed = sum(1 for r in results if r.status is _N)
    passed = sprung == 0

    # Ordered domains (as encountered) and failure modes (frozen order).
    suites: list[str] = []
    for r in results:
        if r.scenario.suite not in suites:
            suites.append(r.scenario.suite)
    traps = [tw.id for tw in TRIPWIRES]
    trap_title = {tw.id: tw.title for tw in TRIPWIRES}

    # Per-failure-mode counts (systemic view) and per-domain counts (local view).
    mode_sprung = {
        t: sum(1 for r in results if r.scenario.trap == t and r.status is _S) for t in traps
    }
    mode_total = {t: sum(1 for r in results if r.scenario.trap == t) for t in traps}
    suite_sprung = {
        s: sum(1 for r in results if r.scenario.suite == s and r.status is _S) for s in suites
    }
    suite_total = {s: sum(1 for r in results if r.scenario.suite == s) for s in suites}

    worst_mode = max((t for t in traps if mode_total[t]), key=lambda t: mode_sprung[t], default="")
    domains_hit = sum(1 for s in suites if suite_sprung[s] > 0)

    # --- summary strip ---
    verdict_cls = "pass" if passed else "fail"
    verdict_txt = "SURVIVED" if passed else "DID NOT SURVIVE"
    trials_clause = (
        f" Fail-closed over {trials} trials of a stochastic agent (sprung if it leaked in any)."
        if trials > 1
        else ""
    )
    verdict_sub = (
        f"No scenario sprang across {total} situations in {len(suites)} domains.{trials_clause}"
        if passed
        else (
            f"{sprung} of {total} scenarios sprang, in {domains_hit} of {len(suites)} domains — "
            f"fail-closed: one failure is a failure.{trials_clause}"
        )
    )
    stat_cards = "".join(
        f'<div class="stat"><span class="v {cls}">{v}</span><span class="k">{_esc(k)}</span></div>'
        for v, k, cls in (
            (f"{sprung}/{total}", "scenarios sprang", "sprung" if sprung else "held"),
            (
                f"{domains_hit}/{len(suites)}",
                "domains with a failure",
                "sprung" if domains_hit else "held",
            ),
            (
                trap_title.get(worst_mode, "—") if sprung else "none",
                "most-failing mode",
                "sprung" if sprung else "held",
            ),
            (f"{not_armed}", "not armed (untested)", "na" if not_armed else "held"),
        )
    )

    # --- confidence strip (TAQI-Sigma / Cramer-Rao): state the rate, the interval,
    #     and the N that bought it. Only meaningful for a multi-trial stochastic run. ---
    conf_block = ""
    if trials > 1:
        from crucible.stats import cramer_rao_sigma, trials_for_halfwidth

        half_pp = round(1.96 * cramer_rao_sigma(0.5, trials) * 100)  # worst-case 95% half-width
        n10 = trials_for_halfwidth(0.5, 0.10)
        n05 = trials_for_halfwidth(0.5, 0.05)
        conf_cards = "".join(
            f'<div class="cstat"><span class="cv">{v}</span><span class="ck">{_esc(k)}</span></div>'
            for v, k in (
                (f"±{half_pp} pp", f"rate precision at {trials} trials (95%)"),
                (f"{n10}", "trials for ±10 pp"),
                (f"{n05}", "trials for ±5 pp"),
            )
        )
        conf_block = (
            '<div class="conf">'
            '<div class="conf-lbl">Confidence · every rate below is a credible interval, '
            "not a point estimate</div>"
            f'<div class="conf-grid">{conf_cards}</div>'
            '<p class="conf-note">Failure rates are Beta-Bernoulli posteriors — we report the '
            "rate, its 95% interval, and the trials that bought it. The pass/fail verdict is exact "
            "regardless; this is confidence on the <i>rate</i>, not the gate.</p>"
            "</div>"
        )

    # --- failure-mode bars (systemic view) ---
    mode_rows = ""
    for t in sorted(traps, key=lambda t: mode_sprung[t], reverse=True):
        if not mode_total[t]:
            continue
        pct = 100 * mode_sprung[t] / mode_total[t]
        mode_rows += (
            f'<div class="bar-row"><span class="bar-lab">{_esc(trap_title[t])}</span>'
            f'<span class="bar"><i style="width:{pct:.0f}%"></i></span>'
            f'<span class="bar-n">{mode_sprung[t]}/{mode_total[t]}</span></div>'
        )

    # --- heatmap: domain (rows) x failure mode (cols) ---
    head_cells = "".join(f'<th class="rot"><span>{_esc(trap_title[t])}</span></th>' for t in traps)
    body_rows = ""
    for s in suites:
        title = SUITES_BY_ID[s].title if s in SUITES_BY_ID else s
        cells = ""
        for t in traps:
            st = _cell_status(results, s, t)
            cls = _CELL_CLASS[st]
            mark = {"sprung": "✕", "held": "✓", "na": "·", "none": ""}[cls]
            cells += (
                f'<td class="cell {cls}" title="{_esc(title)} · {_esc(trap_title[t])}">{mark}</td>'
            )
        rate = f"{suite_sprung[s]}/{suite_total[s]}"
        body_rows += (
            f'<tr><th class="rowlab">{_esc(title)}</th>{cells}'
            f'<td class="rate {"sprung" if suite_sprung[s] else "held"}">{rate}</td></tr>'
        )

    # --- evidence: per-scenario, grouped by domain ---
    evidence = ""
    for s in suites:
        title = SUITES_BY_ID[s].title if s in SUITES_BY_ID else s
        rows = ""
        for r in results:
            if r.scenario.suite != s:
                continue
            cls = _CELL_CLASS[r.status]
            label = {"sprung": "SPRUNG", "held": "HELD", "na": "n/a", "none": "n/a"}[cls]
            detail = _esc(r.detail)
            if r.scenario in prev:
                from crucible.stats import interval_str

                k, n = prev[r.scenario]
                detail += f'  <span class="prev">· sprang in {_esc(interval_str(k, n))}</span>'
            rows += (
                f'<tr class="{cls}"><td class="ev-status"><span class="pill {cls}">{label}</span></td>'
                f'<td class="ev-tw">{_esc(r.scenario.title)}</td>'
                f'<td class="ev-sit">{_esc(r.scenario.situation)}</td>'
                f'<td class="ev-act">{detail}</td></tr>'
            )
        evidence += (
            f'<details class="ev-suite" open><summary>{_esc(title)} '
            f'<span class="ev-rate">{suite_sprung[s]}/{suite_total[s]} sprang</span></summary>'
            f'<table class="ev-table"><tr><th>verdict</th><th>scenario</th>'
            f"<th>situation</th><th>action taken</th></tr>{rows}</table></details>"
        )

    return f"""<title>Crucible Suites Report</title>
<style>
  :root{{
    color-scheme:light dark;
    --bg:#f5f6f8;--panel:#fff;--panel-2:#f8f9fb;--ink:#161a20;--soft:#5a6472;--faint:#8b95a3;
    --line:#e6e9ef;--line-2:#eef1f5;--held:#178a5f;--sprung:#c0392b;--na:#8892a0;
    --held-ghost:rgba(23,138,95,.12);--sprung-ghost:rgba(192,57,43,.10);--na-ghost:rgba(136,146,160,.12);
    --ember:#c9561f;--mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
    --sans:-apple-system,"Segoe UI",system-ui,Helvetica,Arial,sans-serif;
    --shadow:0 1px 2px rgba(20,24,32,.05),0 8px 26px -14px rgba(20,24,32,.20);
  }}
  @media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{
    --bg:#0f1319;--panel:#161c24;--panel-2:#1b222c;--ink:#e7ecf3;--soft:#a7b1bf;--faint:#6c7684;
    --line:#28313d;--line-2:#222a34;--held:#3fd39a;--sprung:#e0685c;--na:#7c8695;
    --held-ghost:rgba(63,211,154,.13);--sprung-ghost:rgba(224,104,92,.13);--na-ghost:rgba(124,134,149,.14);
    --ember:#f0842e;--shadow:0 1px 2px rgba(0,0,0,.4),0 12px 34px -14px rgba(0,0,0,.7);
  }}}}
  :root[data-theme="dark"]{{
    --bg:#0f1319;--panel:#161c24;--panel-2:#1b222c;--ink:#e7ecf3;--soft:#a7b1bf;--faint:#6c7684;
    --line:#28313d;--line-2:#222a34;--held:#3fd39a;--sprung:#e0685c;--na:#7c8695;
    --held-ghost:rgba(63,211,154,.13);--sprung-ghost:rgba(224,104,92,.13);--na-ghost:rgba(124,134,149,.14);
    --ember:#f0842e;--shadow:0 1px 2px rgba(0,0,0,.4),0 12px 34px -14px rgba(0,0,0,.7);
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5;-webkit-font-smoothing:antialiased}}
  main{{max-width:64rem;margin:0 auto;padding:2.4rem 1.25rem 4rem}}
  .head{{display:flex;flex-wrap:wrap;gap:.4rem 1.4rem;align-items:baseline;font-family:var(--mono);font-size:.74rem;letter-spacing:.02em;color:var(--faint)}}
  .head .brand{{color:var(--ember);font-weight:700}}
  h1{{font-size:1.6rem;margin:.5rem 0 1.2rem;letter-spacing:-.01em;text-wrap:balance}}
  .verdict{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:1.1rem 1.3rem;box-shadow:var(--shadow)}}
  .verdict.pass{{border-left:6px solid var(--held)}} .verdict.fail{{border-left:6px solid var(--sprung)}}
  .verdict b{{font-size:1.3rem}} .verdict.pass b{{color:var(--held)}} .verdict.fail b{{color:var(--sprung)}}
  .verdict p{{margin:.35rem 0 0;color:var(--soft);font-size:.95rem}}
  .strip{{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.6rem;margin:1.1rem 0 0}}
  .stat{{background:var(--panel-2);border:1px solid var(--line);border-radius:11px;padding:.7rem .85rem;display:flex;flex-direction:column;gap:.15rem}}
  .stat .v{{font-size:1.35rem;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
  .stat .v.sprung{{color:var(--sprung)}} .stat .v.held{{color:var(--held)}} .stat .v.na{{color:var(--na)}}
  .stat .k{{font-size:.72rem;color:var(--faint);text-transform:uppercase;letter-spacing:.04em}}
  h2{{font-size:1.02rem;margin:2.2rem 0 .3rem;letter-spacing:-.01em}}
  .hint{{color:var(--soft);font-size:.86rem;margin:0 0 .8rem;max-width:64ch}}
  .conf{{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--ember);border-radius:14px;padding:1rem 1.2rem;box-shadow:var(--shadow);margin-top:.9rem}}
  .conf-lbl{{font-family:var(--mono);font-size:.68rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ember);font-weight:700}}
  .conf-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.6rem;margin:.7rem 0 .3rem}}
  .cstat{{background:var(--panel-2);border:1px solid var(--line);border-radius:10px;padding:.6rem .8rem;display:flex;flex-direction:column;gap:.1rem}}
  .cstat .cv{{font-size:1.3rem;font-weight:800;letter-spacing:-.02em;color:var(--ember);font-variant-numeric:tabular-nums}}
  .cstat .ck{{font-size:.7rem;color:var(--faint);text-transform:uppercase;letter-spacing:.04em}}
  .conf-note{{margin:.5rem 0 0;font-size:.82rem;color:var(--soft)}}
  .card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:1.05rem 1.2rem;box-shadow:var(--shadow)}}
  .bar-row{{display:grid;grid-template-columns:12rem 1fr 3rem;align-items:center;gap:.7rem;margin:.35rem 0;font-size:.85rem}}
  .bar-lab{{color:var(--soft);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
  .bar{{height:.55rem;background:var(--held-ghost);border-radius:4px;overflow:hidden;position:relative}}
  .bar i{{position:absolute;left:0;top:0;bottom:0;background:var(--sprung);border-radius:4px}}
  .bar-n{{font-family:var(--mono);font-size:.78rem;color:var(--soft);text-align:right;font-variant-numeric:tabular-nums}}
  .heat-wrap{{overflow-x:auto}}
  table.heat{{border-collapse:collapse;font-size:.8rem;min-width:100%}}
  table.heat th.rot{{height:7.5rem;vertical-align:bottom;padding:0 .1rem;width:2rem}}
  table.heat th.rot span{{writing-mode:vertical-rl;transform:rotate(200grad);white-space:nowrap;color:var(--soft);font-weight:600;font-size:.72rem}}
  table.heat th.rowlab{{text-align:left;padding:.3rem .6rem .3rem 0;color:var(--ink);font-weight:600;white-space:nowrap;font-size:.82rem}}
  table.heat td.cell{{width:2rem;height:2rem;text-align:center;border:2px solid var(--bg);border-radius:6px;font-weight:700}}
  .cell.sprung{{background:var(--sprung);color:#fff}} .cell.held{{background:var(--held);color:#fff}}
  .cell.na{{background:var(--na-ghost);color:var(--na)}} .cell.none{{background:transparent}}
  td.rate{{font-family:var(--mono);font-size:.78rem;padding-left:.6rem;font-variant-numeric:tabular-nums}}
  td.rate.sprung{{color:var(--sprung);font-weight:700}} td.rate.held{{color:var(--held)}}
  .legend{{display:flex;gap:1rem;font-size:.76rem;color:var(--faint);margin-top:.7rem;font-family:var(--mono)}}
  .legend i{{display:inline-block;width:.7rem;height:.7rem;border-radius:3px;vertical-align:-1px;margin-right:.3rem}}
  .legend i.s{{background:var(--sprung)}} .legend i.h{{background:var(--held)}} .legend i.n{{background:var(--na-ghost);border:1px solid var(--na)}}
  details.ev-suite{{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin:.6rem 0;box-shadow:var(--shadow);overflow:hidden}}
  details.ev-suite summary{{cursor:pointer;padding:.7rem 1rem;font-weight:600;display:flex;justify-content:space-between;align-items:center}}
  .ev-rate{{font-family:var(--mono);font-size:.78rem;color:var(--soft)}}
  table.ev-table{{width:100%;border-collapse:collapse;font-size:.82rem}}
  table.ev-table th{{text-align:left;font-family:var(--mono);font-size:.64rem;letter-spacing:.05em;text-transform:uppercase;color:var(--faint);padding:.4rem .7rem;border-top:1px solid var(--line)}}
  table.ev-table td{{padding:.45rem .7rem;border-top:1px solid var(--line);vertical-align:top}}
  .ev-status{{width:5rem}} .ev-tw{{width:11rem;color:var(--soft)}} .ev-sit{{color:var(--soft)}}
  .ev-act{{font-family:var(--mono);font-size:.76rem;color:var(--ink)}}
  .ev-act .prev{{color:var(--sprung);font-weight:600}}
  .pill{{font-family:var(--mono);font-size:.64rem;font-weight:700;padding:.08rem .4rem;border-radius:999px;border:1px solid currentColor}}
  .pill.sprung{{color:var(--sprung)}} .pill.held{{color:var(--held)}} .pill.na{{color:var(--na)}}
  footer{{margin-top:2rem;padding-top:1.1rem;border-top:1px solid var(--line);color:var(--faint);font-size:.82rem}}
  footer .refuse{{font-style:italic}}
</style>
<main>
  <div class="head">
    <span class="brand">CRUCIBLE · SUITES REPORT</span>
    <span>agent: {_esc(agent_label)}</span><span>seed: {seed}</span>
    <span>{len(suites)} domains · {total} scenarios{f" · {trials} trials" if trials > 1 else ""}</span>
    <span>deterministic · replayable</span>
  </div>
  <h1>Where does your agent fail, and is it systemic or local?</h1>
  <div class="verdict {verdict_cls}">
    <b>{verdict_txt}</b>
    <p>{_esc(verdict_sub)}</p>
    <div class="strip">{stat_cards}</div>
  </div>
  {conf_block}

  <h2>Failure by mode — is a weakness systemic?</h2>
  <p class="hint">How often each of the eight failure modes sprang across every domain. A mode that fails
  broadly is a systemic weakness, independent of the domain it shows up in.</p>
  <div class="card">{mode_rows}</div>

  <h2>Failure map — mode × domain</h2>
  <p class="hint">Rows are domains, columns are failure modes. A red <b>column</b> means a mode fails
  almost everywhere (fix the behaviour); a red <b>row</b> means a domain fails on almost everything
  (fix that surface). Each cell is a pass/fail, not a score.</p>
  <div class="card heat-wrap">
    <table class="heat">
      <tr><th></th>{head_cells}<th></th></tr>
      {body_rows}
    </table>
    <div class="legend"><span><i class="s"></i>sprung</span><span><i class="h"></i>held</span><span><i class="n"></i>not armed</span></div>
  </div>

  <h2>Evidence — every scenario</h2>
  <p class="hint">The situation your agent faced and the exact action it took. Every verdict is
  reproducible from the same seed.</p>
  {evidence}

  <footer>
    Deterministic and replayable — same seed, byte-identical run.
    <div class="refuse">A fitness gate, not a debugger — pass/fail and counts, never a score, never advice.</div>
  </footer>
</main>
"""
