# SPDX-License-Identifier: Apache-2.0
"""Render a Crucible run as a shareable survival report, a badge, and JSON.

Three renderers, one run:

* :func:`render_report` -- a self-contained, screenshot-worthy HTML survival
  report (verdict, a summary meter, tripwires grouped agent-side / protocol-side,
  the replay command, the refusal). No external assets, theme-aware.
* :func:`render_badge` -- a self-hosted flat SVG status badge (no service): green
  "survived", red "N sprung", grey "not run". Commit it, reference it in a README.
* :func:`summary_json` -- a machine-readable summary for CI, dashboards, and
  metrics pipelines.

All three are a fitness gate, not a debugger: pass / fail / not-armed and a
replayable trace. Never a score, never advice.

Example::

    html = render_report(results, endpoint="fixture:naive", seed=42,
                         trace_path="t.jsonl", replay_cmd="crucible run ...")
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from typing import Any, cast

from crucible.tripwires import (
    HOLD_BASIS_LABEL,
    HOLD_BASIS_NOTE,
    Coverage,
    Effect,
    TripwireResult,
    TripwireStatus,
    verdict_strength,
)

_STATUS_LABEL = {
    TripwireStatus.SPRUNG: "SPRUNG",
    TripwireStatus.HELD: "HELD",
    TripwireStatus.NOT_ARMED: "NOT ARMED",
}
_STATUS_CLASS = {
    TripwireStatus.SPRUNG: "sprung",
    TripwireStatus.HELD: "held",
    TripwireStatus.NOT_ARMED: "not-armed",
}
_ORIGIN_LABEL = {
    "agent-side": "Agent-side · how it manages its own context and actions",
    "protocol-side": "Protocol-side · money, secrets, authority, identity",
}


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _counts(results: Sequence[TripwireResult]) -> tuple[int, int, int]:
    sprung = sum(1 for r in results if r.status is TripwireStatus.SPRUNG)
    held = sum(1 for r in results if r.status is TripwireStatus.HELD)
    not_armed = sum(1 for r in results if r.status is TripwireStatus.NOT_ARMED)
    return sprung, held, not_armed


def _plain_trace(events: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-trap plain-language material: the decisive hostile probe and the reply.

    Returns ``{trap_id: {"hostile": <text>, "effect": Effect}}`` read off the
    trace's ``send`` events, for the non-engineer-legible narrative.
    """
    out: dict[str, dict[str, Any]] = {}
    for ev in events:
        if ev.get("kind") != "send":
            continue
        raw = ev.get("msg", "")
        if not isinstance(raw, str):
            continue
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        o = cast("dict[str, Any]", obj)
        trap = o.get("trap")
        if not isinstance(trap, str):
            continue
        slot = out.setdefault(trap, {"hostile": "", "effect": None})
        if o.get("g") == "probe" and o.get("decisive"):
            a2a = o.get("a2a")
            if isinstance(a2a, dict):
                slot["hostile"] = str(cast("dict[str, Any]", a2a).get("text", ""))
        elif o.get("g") == "reply" and o.get("decisive"):
            decision = o.get("decision")
            if isinstance(decision, dict):
                slot["effect"] = Effect.from_record(cast("dict[str, Any]", decision))
    return out


def _human_response(effect: Effect | None) -> str:
    """A plain sentence describing what the agent did, for the trace."""
    if effect is None:
        return "no decisive response was recorded."
    prose = effect.text.strip()
    if effect.name:
        base = f"The agent {effect.describe()}."
        return f"{base} (reply: {prose})" if prose else base
    return (
        f'The agent {effect.describe()}: "{prose}"' if prose else f"The agent {effect.describe()}."
    )


def _row(result: TripwireResult, has_trace: bool) -> str:
    tw = result.tripwire
    status = result.status
    cls = _STATUS_CLASS[status]
    label = _STATUS_LABEL[status]
    trace_cell = ""
    if status is TripwireStatus.SPRUNG and has_trace:
        trace_cell = f'<a class="trace" href="#trace-{_esc(tw.id)}">what happened →</a>'
    return (
        f'<tr class="row {cls}">'
        f'<td class="tw"><span class="tw-title">{_esc(tw.title)}</span>'
        f'<span class="tw-line">{_esc(tw.one_liner)}</span></td>'
        f'<td class="status"><span class="pill {cls}">{label}</span></td>'
        f'<td class="detail">{_esc(result.detail)}{trace_cell}</td>'
        "</tr>"
    )


def _section(results: Sequence[TripwireResult], origin: str, has_trace: bool) -> str:
    rows = [_row(r, has_trace) for r in results if r.tripwire.origin == origin]
    if not rows:
        return ""
    heading = _ORIGIN_LABEL.get(origin, origin)
    body = "\n".join(rows)
    return f'<tr class="section"><td colspan="3">{_esc(heading)}</td></tr>\n{body}'


def _coverage_note(coverage: Coverage | None) -> str:
    """A compact arming/unmapped-tool tally rendered under the meter."""
    if coverage is None:
        return ""
    armed = f'<span class="cov-armed">{coverage.armed} of {coverage.total} traps armed</span>'
    if coverage.unmapped_tools:
        tools = ", ".join(_esc(t) for t in coverage.unmapped_tools)
        unmapped = (
            f'<span class="cov-warn">{len(coverage.unmapped_tools)} invoked tool(s) '
            f"unmapped: [{tools}]</span>"
            '<span class="cov-warn-note">These tools were called but no tool_map ties them '
            "to a trap, so no verdict covers them — untested, not held.</span>"
        )
    else:
        unmapped = '<span class="cov-ok">0 invoked tool(s) unmapped</span>'
    return f'<div class="coverage">Coverage: {armed} · {unmapped}</div>'


def _verdict_strength_note(results: Sequence[TripwireResult]) -> str:
    """A factual verdict-strength tally rendered under the meter (a count, not a score)."""
    mapped, self_named, total = verdict_strength(results)
    if total == 0:
        body = "no holds to weigh (nothing held)"
    else:
        body = (
            f'<span class="cov-armed">{mapped} of {total}</span> holds from mapped tool calls, '
            f"{self_named} from self-named effects"
        )
    return f'<div class="coverage vstrength">Verdict strength: {body}.</div>'


_BASIS_ORDER = ("mapped_tool", "flag", "self_named")


def _trust_basis(results: Sequence[TripwireResult]) -> str:
    """Disclose every hold's trust basis, keyed off provenance, split into three families.

    Extends the self-attested-hold caveat from the three flag traps to all eight:
    every HELD is grouped under the honest family of evidence it rests on -- a
    mapped tool call, a self-set flag, or a bare self-named effect -- so no green
    is silently trusted.
    """
    holds = [r for r in results if r.status is TripwireStatus.HELD]
    if not holds:
        return ""
    blocks: list[str] = []
    for fam in _BASIS_ORDER:
        members = [r for r in holds if r.hold_basis == fam]
        if not members:
            continue
        names = ", ".join(_esc(r.tripwire.title) for r in members)
        blocks.append(
            f"<li><b>{_esc(HOLD_BASIS_LABEL[fam])}.</b> {_esc(HOLD_BASIS_NOTE[fam])}"
            f'<span class="basis-traps">{names}</span></li>'
        )
    return (
        '<details class="scope" open><summary>How far to trust each green — '
        "every hold&rsquo;s basis</summary>"
        f'<ul class="covers basis">{"".join(blocks)}</ul></details>'
    )


def _coverage_list(results: Sequence[TripwireResult]) -> str:
    items = "\n".join(
        f"<li><b>{_esc(r.tripwire.title)}.</b> {_esc(r.tripwire.covers)}</li>" for r in results
    )
    return (
        '<details class="scope"><summary>What these 8 traps do and do not cover</summary>'
        f'<ul class="covers">{items}</ul></details>'
    )


def _trace_narrative(results: Sequence[TripwireResult], plain: dict[str, dict[str, Any]]) -> str:
    """The plain-language 'What happened' section: sprung summary + per-trap prose."""
    sprung = [r for r in results if r.status is TripwireStatus.SPRUNG]
    summary = ""
    if sprung:
        lines = "\n".join(
            f'<li><a href="#trace-{_esc(r.id)}">{_esc(r.tripwire.title)}</a> — '
            f"{_esc(_human_response(cast('Effect | None', plain.get(r.id, {}).get('effect'))))}</li>"
            for r in sprung
        )
        summary = (
            '<div class="sprung-summary"><b>What sprang, in one line each:</b>'
            f"<ul>{lines}</ul></div>"
        )
    blocks: list[str] = []
    for r in results:
        info = plain.get(r.id)
        if not info or (not info.get("hostile") and info.get("effect") is None):
            continue
        cls = _STATUS_CLASS[r.status]
        hostile = str(info.get("hostile", "")) or "(no decisive hostile probe recorded)"
        response = _human_response(cast("Effect | None", info.get("effect")))
        blocks.append(
            f'<div class="tblock" id="trace-{_esc(r.id)}">'
            f'<div class="tbhead"><span class="pill {cls}">{_STATUS_LABEL[r.status]}</span>'
            f"<b>{_esc(r.tripwire.title)}</b></div>"
            f'<div class="turn hostile"><span class="who">Hostile counterparty said</span>'
            f"<p>{_esc(hostile)}</p></div>"
            f'<div class="turn agent"><span class="who">Your agent</span>'
            f"<p>{_esc(response)}</p></div>"
            "</div>"
        )
    if not summary and not blocks:
        return ""
    body = summary + "\n".join(blocks)
    return f'<section class="trace-narrative"><h2>What happened</h2>{body}</section>'


def _meter(sprung: int, held: int, not_armed: int) -> str:
    total = max(1, sprung + held + not_armed)
    seg: list[str] = []
    if held:
        seg.append(f'<span class="seg held" style="flex:{held}" title="{held} held"></span>')
    if sprung:
        seg.append(
            f'<span class="seg sprung" style="flex:{sprung}" title="{sprung} sprung"></span>'
        )
    if not_armed:
        seg.append(
            f'<span class="seg not-armed" style="flex:{not_armed}" '
            f'title="{not_armed} not armed"></span>'
        )
    bar = "".join(seg) or f'<span class="seg not-armed" style="flex:{total}"></span>'
    return (
        f'<div class="meter">{bar}</div>'
        f'<div class="legend">'
        f'<span><i class="dot held"></i>{held} held</span>'
        f'<span><i class="dot sprung"></i>{sprung} sprung</span>'
        f'<span><i class="dot not-armed"></i>{not_armed} not armed</span>'
        f"</div>"
    )


def render_report(
    results: Sequence[TripwireResult],
    *,
    endpoint: str,
    seed: int,
    trace_path: str,
    replay_cmd: str,
    events: Sequence[dict[str, Any]] | None = None,
    coverage: Coverage | None = None,
    trials: int = 1,
) -> str:
    """Return a standalone, shareable survival-report HTML document.

    Pass ``trials`` > 1 to note that the verdict is **fail-closed over N trials**
    of a stochastic agent (per-tripwire prevalence rides in each result's detail).

    Pass ``events`` (the trace) to render the plain-language "What happened"
    section -- the hostile message and the agent's response in prose, with a
    one-line human summary of each sprung tripwire linked from its row.

    Example::

        html = render_report(results, endpoint="fixture:naive", seed=42,
                             trace_path="t.jsonl", replay_cmd="crucible run ...", events=events)
    """
    sprung, held, not_armed = _counts(results)
    passed = sprung == 0
    verdict_cls = "pass" if passed else "fail"
    verdict_txt = "SURVIVED" if passed else "DID NOT SURVIVE"
    verdict_sub = (
        "No tripwire sprang. Your agent held every hostile counterparty in this run."
        if passed
        else f"{sprung} tripwire(s) sprang — your agent tripped an observable failure."
    )
    if trials > 1:
        verdict_sub += (
            f" Fail-closed over {trials} trials of a stochastic agent: a tripwire is SPRUNG if it"
            " leaked in any trial. Per-tripwire prevalence is shown below (evidence, not a score)."
        )
    plain = _plain_trace(events) if events else {}
    has_trace = bool(plain)
    sections = "\n".join(
        s
        for s in (
            _section(results, "agent-side", has_trace),
            _section(results, "protocol-side", has_trace),
        )
        if s
    )
    scope_note = (
        "SURVIVED = none of these 8 specific traps sprang — a floor, not a certification, and "
        "not a statement that the agent is safe to ship."
        if passed
        else "This is a floor, not a certification: the 8 traps below are a minimum, not the "
        "whole of safety."
    )
    narrative = _trace_narrative(results, plain)

    return f"""<title>Crucible Survival Report</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg:#f6f7f9; --panel:#fff; --panel-2:#fbfbfc; --ink:#14181f; --soft:#4a5461;
    --faint:#8a94a2; --line:#e6e9ee; --held:#1f9e6f; --sprung:#c0392b; --na:#9aa4b0;
    --accent:#3355ff; --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg:#0f1319; --panel:#171c24; --panel-2:#1b212a; --ink:#e6eaf0; --soft:#a7b0bd;
      --faint:#6b7480; --line:#2a323c; --held:#3fd39a; --sprung:#e0685c; --na:#6b7480;
      --accent:#8fa4ff;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg:#0f1319; --panel:#171c24; --panel-2:#1b212a; --ink:#e6eaf0; --soft:#a7b0bd;
    --faint:#6b7480; --line:#2a323c; --held:#3fd39a; --sprung:#e0685c; --na:#6b7480;
    --accent:#8fa4ff;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,Segoe UI,system-ui,sans-serif; line-height:1.5; }}
  main {{ max-width:56rem; margin:0 auto; padding:2.5rem 1.25rem 4rem; }}
  .head {{ display:flex; flex-wrap:wrap; gap:.4rem 1.4rem; align-items:baseline;
    font-family:var(--mono); font-size:.76rem; letter-spacing:.02em; color:var(--faint); }}
  .head .brand {{ color:var(--soft); font-weight:600; }}
  h1 {{ font-size:1.7rem; margin:.5rem 0 1.3rem; text-wrap:balance; }}
  .verdict {{ background:var(--panel); border:1px solid var(--line); border-radius:12px;
    padding:1.2rem 1.4rem; margin:0 0 1.4rem; }}
  .verdict.pass {{ border-left:6px solid var(--held); }}
  .verdict.fail {{ border-left:6px solid var(--sprung); }}
  .verdict b {{ font-size:1.35rem; letter-spacing:.01em; }}
  .verdict.pass b {{ color:var(--held); }}
  .verdict.fail b {{ color:var(--sprung); }}
  .verdict p {{ margin:.4rem 0 0; color:var(--soft); }}
  .meter {{ display:flex; height:.7rem; border-radius:999px; overflow:hidden;
    margin:1.1rem 0 .5rem; background:var(--panel-2); border:1px solid var(--line); }}
  .seg.held {{ background:var(--held); }} .seg.sprung {{ background:var(--sprung); }}
  .seg.not-armed {{ background:var(--na); opacity:.55; }}
  .legend {{ display:flex; gap:1.1rem; font-family:var(--mono); font-size:.75rem;
    color:var(--faint); }}
  .legend i.dot {{ display:inline-block; width:.6rem; height:.6rem; border-radius:50%;
    margin-right:.35rem; vertical-align:baseline; }}
  .dot.held {{ background:var(--held); }} .dot.sprung {{ background:var(--sprung); }}
  .dot.not-armed {{ background:var(--na); }}
  table {{ width:100%; border-collapse:collapse; background:var(--panel);
    border:1px solid var(--line); border-radius:12px; overflow:hidden; margin-top:.4rem; }}
  td {{ padding:.7rem .9rem; border-top:1px solid var(--line); vertical-align:top; }}
  tr.section td {{ background:var(--panel-2); font-family:var(--mono); font-size:.72rem;
    letter-spacing:.04em; text-transform:uppercase; color:var(--faint); border-top:1px solid var(--line); }}
  .tw-title {{ display:block; font-weight:600; }}
  .tw-line {{ display:block; font-size:.85rem; color:var(--soft); }}
  .status {{ width:7rem; }}
  .pill {{ display:inline-block; font-family:var(--mono); font-size:.72rem; font-weight:700;
    padding:.15rem .55rem; border-radius:999px; border:1px solid currentColor; }}
  .pill.sprung {{ color:var(--sprung); }} .pill.held {{ color:var(--held); }}
  .pill.not-armed {{ color:var(--na); }}
  .detail {{ font-size:.85rem; color:var(--soft); }}
  .trace {{ display:inline-block; margin-left:.5rem; font-family:var(--mono);
    font-size:.78rem; color:var(--accent); }}
  footer {{ margin-top:1.8rem; padding-top:1.1rem; border-top:1px solid var(--line);
    color:var(--faint); font-size:.82rem; }}
  footer .replay {{ display:block; font-family:var(--mono); color:var(--ink);
    background:var(--panel); border:1px solid var(--line); border-radius:8px;
    padding:.6rem .8rem; margin:.4rem 0 .8rem; overflow-x:auto; }}
  .refusal {{ font-style:italic; }}
  .coverage {{ margin:.6rem 0 0; font-family:var(--mono); font-size:.76rem; color:var(--soft); }}
  .coverage .cov-armed {{ color:var(--ink); font-weight:600; }}
  .coverage .cov-ok {{ color:var(--held); }}
  .coverage .cov-warn {{ color:var(--sprung); font-weight:600; }}
  .coverage .cov-warn-note {{ display:block; margin-top:.2rem; color:var(--soft);
    font-family:-apple-system,Segoe UI,system-ui,sans-serif; font-weight:400; }}
  .scope-note {{ margin:.7rem 0 0; padding:.6rem .8rem; border-radius:8px;
    background:var(--panel-2); border:1px dashed var(--line); color:var(--soft);
    font-size:.82rem; }}
  details.scope {{ margin:.6rem 0 1.4rem; font-size:.85rem; color:var(--soft); }}
  details.scope summary {{ cursor:pointer; color:var(--accent); font-family:var(--mono);
    font-size:.78rem; }}
  ul.covers {{ margin:.6rem 0 0; padding-left:1.1rem; }}
  ul.covers li {{ margin:.35rem 0; }}
  .coverage.vstrength {{ margin-top:.3rem; }}
  ul.basis li {{ margin:.5rem 0; }}
  ul.basis .basis-traps {{ display:block; margin-top:.15rem; font-family:var(--mono);
    font-size:.74rem; color:var(--faint); }}
  .trace-narrative {{ margin:2rem 0 0; }}
  .trace-narrative h2 {{ font-size:1.15rem; margin:0 0 .8rem; }}
  .sprung-summary {{ background:var(--panel); border:1px solid var(--line);
    border-left:6px solid var(--sprung); border-radius:10px; padding:.8rem 1rem; margin:0 0 1.2rem; }}
  .sprung-summary ul {{ margin:.5rem 0 0; padding-left:1.1rem; }}
  .sprung-summary li {{ margin:.3rem 0; }}
  .tblock {{ background:var(--panel); border:1px solid var(--line); border-radius:10px;
    padding:.9rem 1rem; margin:0 0 .9rem; scroll-margin-top:1rem; }}
  .tbhead {{ display:flex; gap:.6rem; align-items:center; margin-bottom:.6rem; }}
  .turn {{ margin:.4rem 0; }}
  .turn .who {{ display:block; font-family:var(--mono); font-size:.68rem; letter-spacing:.05em;
    text-transform:uppercase; color:var(--faint); }}
  .turn p {{ margin:.2rem 0 0; }}
  .turn.hostile p {{ color:var(--soft); }}
  .turn.agent p {{ color:var(--ink); }}
</style>
<main>
  <div class="head">
    <span class="brand">CRUCIBLE · SURVIVAL REPORT</span>
    <span>endpoint: {_esc(endpoint)}</span>
    <span>seed: {seed}</span>
    <span>deterministic · replayable</span>
  </div>
  <h1>Did your agent survive the storm?</h1>
  <div class="verdict {verdict_cls}">
    <b>{verdict_txt}</b>
    <p>{_esc(verdict_sub)}</p>
    {_meter(sprung, held, not_armed)}
    {_coverage_note(coverage)}
    {_verdict_strength_note(results)}
    <div class="scope-note">{_esc(scope_note)}</div>
  </div>
  {_trust_basis(results)}
  {_coverage_list(results)}
  <table>
    {sections}
  </table>
  {narrative}
  <footer>
    Replay this exact run (same seed → byte-identical trace):
    <code class="replay">{_esc(replay_cmd)}</code>
    <div class="refusal">A fitness gate, not a debugger — no advice, no score.</div>
  </footer>
</main>
"""


def summary_json(
    results: Sequence[TripwireResult],
    *,
    endpoint: str,
    seed: int,
    trace_path: str,
    trials: int = 1,
    prevalence: dict[str, dict[str, int]] | None = None,
) -> dict[str, object]:
    """Return a machine-readable summary of a run (for CI, dashboards, metrics).

    Pass ``trials`` and ``prevalence`` (from :mod:`crucible.trials`) to record a
    fail-closed multi-trial run: ``trials`` is the sample size and each tripwire
    gains a ``prevalence`` block (``sprang in k of N``) — evidence, not a score.

    Example::

        data = summary_json(results, endpoint="fixture:naive", seed=42, trace_path="t.jsonl")
    """
    sprung, held, not_armed = _counts(results)
    mapped, self_named, total_holds = verdict_strength(results)
    prev = prevalence or {}
    return {
        "product": "crucible",
        "endpoint": endpoint,
        "seed": seed,
        "trace": trace_path,
        "trials": trials,
        "passed": sprung == 0,
        "counts": {"sprung": sprung, "held": held, "not_armed": not_armed},
        "verdict_strength": {
            "holds": total_holds,
            "from_mapped_tool": mapped,
            "from_self_named": self_named,
        },
        "tripwires": [
            {
                "id": r.id,
                "origin": r.tripwire.origin,
                "status": r.status.value,
                "detail": r.detail,
                "provenance": r.provenance,
                "hold_basis": r.hold_basis,
                **({"prevalence": prev[r.id]} if r.id in prev else {}),
            }
            for r in results
        ],
    }


def summary_line(results: Sequence[TripwireResult]) -> str:
    """A one-line, shareable summary (for CI logs / step summaries).

    Example::

        summary_line(results)  # 'Crucible: SURVIVED — 8 held, 0 sprung, 0 n/a'
    """
    sprung, held, not_armed = _counts(results)
    verdict = "SURVIVED" if sprung == 0 else "DID NOT SURVIVE"
    return f"Crucible: {verdict} — {held} held, {sprung} sprung, {not_armed} n/a"


def render_badge(results: Sequence[TripwireResult]) -> str:
    """Return a self-contained flat SVG status badge (no hosted service).

    Green "survived", red "N sprung", grey "not run". Commit the SVG and
    reference it from a README -- no shields.io, no endpoint, no account.

    Example::

        Path("badge.svg").write_text(render_badge(results))
    """
    sprung, held, _ = _counts(results)
    if sprung:
        value, color = (f"{sprung} sprung", "#c0392b")
    elif held:
        value, color = ("survived", "#1f9e6f")
    else:
        value, color = ("not run", "#9aa4b0")

    label = "crucible"
    # ~6.5px per char at 11px font; keep it simple and legible.
    lw = 8 + len(label) * 6.5
    vw = 12 + len(value) * 6.5
    total = lw + vw
    lx = lw / 2
    vx = lw + vw / 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total:.0f}" height="20" '
        f'role="img" aria-label="{label}: {value}">'
        f'<linearGradient id="s" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<rect rx="3" width="{total:.0f}" height="20" fill="#555"/>'
        f'<rect rx="3" x="{lw:.0f}" width="{vw:.0f}" height="20" fill="{color}"/>'
        f'<rect rx="3" width="{total:.0f}" height="20" fill="url(#s)"/>'
        f'<g fill="#fff" text-anchor="middle" '
        f'font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{lx:.0f}" y="15" fill="#010101" fill-opacity=".3">{label}</text>'
        f'<text x="{lx:.0f}" y="14">{label}</text>'
        f'<text x="{vx:.0f}" y="15" fill="#010101" fill-opacity=".3">{value}</text>'
        f'<text x="{vx:.0f}" y="14">{value}</text>'
        f"</g></svg>"
    )


def write_json(path: str, data: dict[str, object]) -> None:
    """Write the summary JSON to *path* (helper for the CLI)."""
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))
