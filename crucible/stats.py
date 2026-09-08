# SPDX-License-Identifier: Apache-2.0
"""Confidence on a stochastic rate — the TAQI-Sigma / Cramer-Rao port (C7).

A prevalence like "sprang in k of N trials" is an *estimate* of a latent rate, so
a bare k/N overclaims. Following TAQI-Sigma (Hariprasad, TAIF), we model the rate
as a Beta-Bernoulli posterior and report a credible interval; the Cramer-Rao bound
gives the sample size needed for a target precision.

Prior ``Beta(a0, b0)`` (default uniform ``a0=b0=1``). After ``n`` trials with ``k``
sprung: posterior ``Beta(a0+k, b0+n-k)``; report the posterior mean and a central
credible interval. This is a confidence interval on a *prevalence fact*, never a
grade of the agent (Spine C3): the fail-closed verdict stays binary.

Pure stdlib — the regularized incomplete beta is computed by the Lentz continued
fraction (Numerical Recipes ``betai``); the quantile is a bisection on it.

Example::

    mean, lo, hi = credible_interval(k=8, n=50)   # ~0.173, ~0.08, ~0.28
    cramer_rao_sigma(0.2, 100)                     # ~0.04  (=> ~+/-8pp at 95%)
    trials_for_halfwidth(0.2, 0.05)                # trials needed for +/-5pp
"""

from __future__ import annotations

import math

_FPMIN = 1e-300
_EPS = 3e-16
# z for common two-sided credible levels (standard normal quantiles).
_Z = {0.90: 1.6448536269, 0.95: 1.9599639845, 0.99: 2.5758293035}


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (Lentz's algorithm)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _FPMIN:
        d = _FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def reg_incomplete_beta(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta ``I_x(a, b)`` — the Beta CDF at ``x``.

    Example::

        reg_incomplete_beta(9, 43, 0.173)  # ~0.5
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(ln_beta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_quantile(p: float, a: float, b: float) -> float:
    """Inverse Beta CDF (the ``p``-quantile of ``Beta(a, b)``) by bisection.

    Example::

        beta_quantile(0.5, 9, 43)  # ~0.171 (median)
    """
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if reg_incomplete_beta(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def credible_interval(
    k: int, n: int, *, a0: float = 1.0, b0: float = 1.0, cred: float = 0.95
) -> tuple[float, float, float]:
    """Posterior mean and central credible interval for a rate from ``k``/``n``.

    Returns ``(mean, lo, hi)`` for the ``Beta(a0+k, b0+n-k)`` posterior. With the
    uniform prior this reproduces TAIF's worked example: ``k=8, n=50`` gives
    mean ~0.173 and a 95% interval of ~``[0.08, 0.28]``.

    Example::

        mean, lo, hi = credible_interval(8, 50)
    """
    a = a0 + k
    b = b0 + (n - k)
    mean = a / (a + b)
    tail = (1.0 - cred) / 2.0
    return mean, beta_quantile(tail, a, b), beta_quantile(1.0 - tail, a, b)


def cramer_rao_sigma(theta: float, n: int) -> float:
    """The Cramer-Rao standard-deviation floor for a Bernoulli rate estimate.

    ``sigma_min = sqrt(theta*(1-theta)/n)`` — the tightest a rate estimate can be
    at ``n`` trials. Example: ``theta=0.2, n=100`` -> ~0.04 (about +/-8pp at 95%).

    Example::

        cramer_rao_sigma(0.2, 100)  # ~0.04
    """
    if n <= 0:
        return math.inf
    return math.sqrt(theta * (1.0 - theta) / n)


def trials_for_halfwidth(theta: float, halfwidth: float, *, cred: float = 0.95) -> int:
    """Trials needed for a credible interval half-width of ``halfwidth`` at ``theta``.

    Inverts the Cramer-Rao floor: ``n = theta*(1-theta)*(z/halfwidth)^2``, rounded
    up. Answers "how many adversarial trials until the failure-rate is trustworthy
    to +/- this much" — the sample-size question the book poses.

    Example::

        trials_for_halfwidth(0.2, 0.05)  # trials for +/-5pp at 95%
    """
    if halfwidth <= 0.0:
        return 0
    z = _Z.get(round(cred, 2), 1.9599639845)
    return math.ceil(theta * (1.0 - theta) * (z / halfwidth) ** 2)


def interval_str(k: int, n: int, *, cred: float = 0.95) -> str:
    """A compact "k/N (95% CI lo-hi%)" string for reports.

    Example::

        interval_str(13, 20)  # '13 of 20 (95% CI 46-81%)'
    """
    _, lo, hi = credible_interval(k, n, cred=cred)
    pct = round(cred * 100)
    return f"{k} of {n} ({pct}% CI {lo * 100:.0f}–{hi * 100:.0f}%)"
