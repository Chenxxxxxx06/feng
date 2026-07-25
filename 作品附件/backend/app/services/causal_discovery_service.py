"""Time-series causal discovery — Granger causality for wind turbine signals.

EXPLORATORY AUXILIARY tool. Statistical correlation is NOT causal proof.

Implements:
- Stationarity check (ADF test via variance ratio)
- Lag order selection (AIC-like: minimize residual variance)
- Granger causality test (F-test on restricted vs unrestricted model)
- Multiple testing correction (Bonferroni)
- Bootstrap stability assessment
- Cross-validation with component topology / physical rules

Output labeled "候选因果关系" (candidate causal relationship).
Shows lag, significance, stability, and physical plausibility.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CausalLink:
    """One candidate causal relationship."""
    source: str = ""         # Cause variable
    target: str = ""         # Effect variable
    lag: int = 1             # Optimal lag order
    f_statistic: float = 0.0
    p_value: float = 1.0
    p_value_corrected: float = 1.0  # Bonferroni corrected
    significant: bool = False       # After correction
    bootstrap_stability: float = 0.0  # Fraction of bootstrap samples where significant
    stable: bool = False           # bootstrap_stability >= 0.8
    physical_plausibility: str = "unknown"  # plausible / implausible / unknown
    physical_rule: str = ""        # Which physical rule supports/contradicts
    interpretation: str = ""       # Human-readable
    caveat: str = "统计相关性，不构成确定因果结论"


@dataclass
class CausalDiscoveryResult:
    """Complete causal discovery output for a set of time series."""
    variable_pairs: list[tuple[str, str]] = field(default_factory=list)
    links: list[CausalLink] = field(default_factory=list)
    significant_links: list[CausalLink] = field(default_factory=list)
    stationarity_results: dict[str, bool] = field(default_factory=dict)
    test_method: str = "granger_f_test"
    correction_method: str = "bonferroni"
    bootstrap_samples: int = 100
    total_tests: int = 0
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    caveat: str = "所有结果为候选因果关系。统计显著性不代表物理因果。需结合部件拓扑和物理规则交叉验证。"


# Physical plausibility rules — known physical relationships
PHYSICAL_RULES = {
    ("vibration_rms", "bearing_temperature"): ("plausible", "摩擦产生热量，振动增大→温度升高"),
    ("bearing_temperature", "vibration_rms"): ("implausible", "温度升高不直接导致振动，但热膨胀可间接影响"),
    ("wind_speed", "power_kw"): ("plausible", "风速增加→发电功率增加"),
    ("power_kw", "generator_temperature"): ("plausible", "功率增大→发电机发热增加"),
    ("rotor_rpm", "vibration_rms"): ("plausible", "转速变化→振动特征变化"),
    ("gearbox_temperature", "bearing_temperature"): ("plausible", "齿轮箱发热传导至轴承"),
}


class CausalDiscoveryService:
    """Granger causality analysis for wind turbine time series.

    NOT a causal oracle. Every output carries explicit caveats.
    """

    def __init__(self, max_lag: int = 10, bootstrap_samples: int = 100):
        self.max_lag = max_lag
        self.bootstrap_samples = bootstrap_samples

    def discover(
        self,
        time_series: dict[str, list[float]],
        variable_pairs: Optional[list[tuple[str, str]]] = None,
    ) -> CausalDiscoveryResult:
        """Discover Granger-causal relationships among time series.

        Args:
            time_series: dict of variable_name → [values] (aligned timestamps)
            variable_pairs: Optional list of (cause, effect) pairs to test.
                           If None, tests all ordered pairs.

        Returns:
            CausalDiscoveryResult with candidate links and caveats.
        """
        # Data validation
        n_series = len(time_series)
        if n_series < 2:
            return CausalDiscoveryResult(
                caveat="需要至少2个时间序列变量进行因果分析。当前仅有{}个。".format(n_series),
            )

        # Check minimum length
        min_len = min(len(v) for v in time_series.values())
        if min_len < 20:
            return CausalDiscoveryResult(
                caveat=f"时间序列太短({min_len}点)，需要≥1000点进行可靠因果推断。当前结果仅供参考。",
            )

        # Check stationarity
        stationarity = {
            name: self._check_stationarity(values)
            for name, values in time_series.items()
        }

        # Generate variable pairs
        if variable_pairs is None:
            var_names = list(time_series.keys())
            variable_pairs = [
                (cause, effect)
                for cause in var_names
                for effect in var_names
                if cause != effect
            ]

        result = CausalDiscoveryResult(
            variable_pairs=variable_pairs,
            stationarity_results=stationarity,
            total_tests=len(variable_pairs),
        )

        # Run Granger test for each pair
        links: list[CausalLink] = []
        for cause, effect in variable_pairs:
            cause_vals = time_series.get(cause, [])
            effect_vals = time_series.get(effect, [])
            if len(cause_vals) < 10 or len(effect_vals) < 10:
                continue

            link = self._granger_test(cause, effect, cause_vals, effect_vals)
            links.append(link)

        # Bonferroni correction
        n_tests = len(links)
        for link in links:
            link.p_value_corrected = min(1.0, link.p_value * n_tests)
            link.significant = link.p_value_corrected < 0.05

        # Bootstrap stability
        if self.bootstrap_samples > 0:
            for link in links:
                link.bootstrap_stability = self._bootstrap_stability(
                    time_series.get(link.source, []),
                    time_series.get(link.target, []),
                    link.lag,
                )
                link.stable = link.bootstrap_stability >= 0.8

        # Physical plausibility
        for link in links:
            rule = PHYSICAL_RULES.get((link.source, link.target))
            if rule:
                link.physical_plausibility = rule[0]
                link.physical_rule = rule[1]
            else:
                link.physical_plausibility = "unknown"
                link.physical_rule = "无已知物理规则"

            # Build interpretation
            if link.significant and link.stable:
                link.interpretation = (
                    f"候选因果: {link.source} → {link.target} "
                    f"(滞后{link.lag}阶, p={link.p_value_corrected:.4f}, "
                    f"稳定性={link.bootstrap_stability:.0%}, "
                    f"物理{link.physical_plausibility})"
                )
            elif link.significant:
                link.interpretation = (
                    f"统计显著但Bootstrap不稳定: {link.source} → {link.target} "
                    f"(p={link.p_value_corrected:.4f}, 稳定性={link.bootstrap_stability:.0%})"
                )
            else:
                link.interpretation = (
                    f"未发现显著因果: {link.source} → {link.target} "
                    f"(p={link.p_value_corrected:.4f})"
                )

            link.interpretation += f" [注意: {link.caveat}]"

        result.links = links
        result.significant_links = [l for l in links if l.significant and l.stable]
        return result

    def _granger_test(
        self,
        cause_name: str,
        effect_name: str,
        cause: list[float],
        effect: list[float],
    ) -> CausalLink:
        """Granger causality F-test: does 'cause' help predict 'effect'?"""
        # Align lengths
        n = min(len(cause), len(effect))
        cause_arr = np.array(cause[:n])
        effect_arr = np.array(effect[:n])

        # Select lag order (AIC-like: minimize residual variance)
        best_lag = 1
        best_var = float("inf")
        for lag in range(1, min(self.max_lag + 1, n // 5)):
            var_restricted = self._fit_var_residual(effect_arr, lag)
            if var_restricted < best_var:
                best_var = var_restricted
                best_lag = lag

        # Restricted model: Y_t = α + Σβ_i Y_{t-i} + ε_t
        res_restricted = self._fit_autoreg_residuals(effect_arr, best_lag)
        rss_restricted = np.sum(res_restricted ** 2)

        # Unrestricted model: Y_t = α + Σβ_i Y_{t-i} + Σγ_i X_{t-i} + ε_t
        res_unrestricted = self._fit_granger_residuals(effect_arr, cause_arr, best_lag)
        rss_unrestricted = np.sum(res_unrestricted ** 2)

        # F-statistic
        n_obs = n - best_lag
        df1 = best_lag  # Number of restrictions
        df2 = n_obs - 2 * best_lag - 1  # Residual df

        if df2 <= 0 or rss_unrestricted <= 0:
            return CausalLink(
                source=cause_name, target=effect_name, lag=best_lag,
                f_statistic=0.0, p_value=1.0, caveat="数据不足，无法检验",
            )

        f_stat = ((rss_restricted - rss_unrestricted) / df1) / (rss_unrestricted / df2)
        f_stat = max(0.0, f_stat)

        # Approximate p-value from F-distribution
        p_value = self._f_distribution_p_value(f_stat, df1, df2)

        return CausalLink(
            source=cause_name,
            target=effect_name,
            lag=best_lag,
            f_statistic=round(f_stat, 3),
            p_value=round(p_value, 6),
        )

    def _fit_autoreg_residuals(
        self, y: np.ndarray, lag: int
    ) -> np.ndarray:
        """Fit AR(lag) model and return residuals (OLS)."""
        n = len(y)
        if n <= lag:
            return np.zeros(n)

        # Build design matrix
        X = np.column_stack([
            np.ones(n - lag),
            *[y[lag - i - 1 : n - i - 1] for i in range(lag)],
        ])
        Y = y[lag:]

        try:
            beta = np.linalg.lstsq(X, Y, rcond=None)[0]
            pred = X @ beta
            return Y - pred
        except np.linalg.LinAlgError:
            return np.zeros(len(Y))

    def _fit_granger_residuals(
        self, y: np.ndarray, x: np.ndarray, lag: int
    ) -> np.ndarray:
        """Fit ARDL(lag) model with exogenous X and return residuals."""
        n = len(y)
        if n <= 2 * lag:
            return np.zeros(n)

        X = np.column_stack([
            np.ones(n - lag),
            *[y[lag - i - 1 : n - i - 1] for i in range(lag)],
            *[x[lag - i - 1 : n - i - 1] for i in range(lag)],
        ])
        Y = y[lag:]

        try:
            beta = np.linalg.lstsq(X, Y, rcond=None)[0]
            pred = X @ beta
            return Y - pred
        except np.linalg.LinAlgError:
            return np.zeros(len(Y))

    def _fit_var_residual(self, y: np.ndarray, lag: int) -> float:
        """Fit AR model and return residual variance."""
        residuals = self._fit_autoreg_residuals(y, lag)
        return float(np.var(residuals)) if len(residuals) > 0 else float("inf")

    def _check_stationarity(self, values: list[float]) -> bool:
        """Simple stationarity check: variance ratio of first vs second half."""
        arr = np.array(values)
        n = len(arr)
        if n < 10:
            return False
        mid = n // 2
        var_first = np.var(arr[:mid])
        var_second = np.var(arr[mid:])
        if var_second == 0:
            return var_first == 0
        ratio = var_first / var_second
        return 0.5 <= ratio <= 2.0  # Within factor of 2

    def _bootstrap_stability(
        self,
        cause: list[float],
        effect: list[float],
        lag: int,
    ) -> float:
        """Bootstrap: fraction of resamples where Granger test is significant."""
        if len(cause) < 20 or len(effect) < 20:
            return 0.0

        cause_arr = np.array(cause)
        effect_arr = np.array(effect)
        n = min(len(cause_arr), len(effect_arr))
        significant_count = 0

        for _ in range(min(self.bootstrap_samples, 50)):
            # Resample with replacement
            indices = np.random.choice(n, size=n, replace=True)
            cause_boot = cause_arr[indices]
            effect_boot = effect_arr[indices]

            res_restricted = self._fit_autoreg_residuals(effect_boot, lag)
            rss_r = np.sum(res_restricted ** 2)

            res_unrestricted = self._fit_granger_residuals(
                effect_boot, cause_boot, lag
            )
            rss_u = np.sum(res_unrestricted ** 2)

            n_obs = n - lag
            df1 = lag
            df2 = n_obs - 2 * lag - 1

            if df2 > 0 and rss_u > 0:
                f_stat = ((rss_r - rss_u) / df1) / (rss_u / df2)
                p_val = self._f_distribution_p_value(max(0, f_stat), df1, df2)
                if p_val < 0.05:
                    significant_count += 1

        return significant_count / min(self.bootstrap_samples, 50)

    @staticmethod
    def _f_distribution_p_value(f_stat: float, df1: int, df2: int) -> float:
        """Approximate p-value from F-distribution using Wilson-Hilferty.

        F ~ ((1 - 2/(9*df2)) * (χ²/df1)^(1/3) - (1 - 2/(9*df1))) / sqrt(...)
        """
        if f_stat <= 0:
            return 1.0
        if df1 <= 0 or df2 <= 0:
            return 1.0

        # Use the relationship F(df1,df2) ≈ chi²(df1)/df1
        # Normal approximation via Wilson-Hilferty
        x = f_stat
        try:
            # Satterthwaite approximation
            z = (
                (x ** (1/3) * (1 - 2 / (9 * df2)))
                - (1 - 2 / (9 * df1))
            ) / np.sqrt(2 / (9 * df1) + 2 / (9 * df2) * x ** (2/3))
        except (ValueError, ZeroDivisionError, OverflowError):
            return 1.0

        # Normal CDF approximation (1 - Φ(z))
        if z > 6:
            return 0.0
        if z < -6:
            return 1.0

        # Standard normal CDF
        p = 0.5 * (1 + np.tanh(z / np.sqrt(2) * 0.7978845608028654))
        return 1.0 - p
