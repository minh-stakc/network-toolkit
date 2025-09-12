"""
Statistical analysis module for network measurement data.

Provides comprehensive statistical analysis including descriptive stats,
distribution fitting, outlier detection, trend analysis, and
confidence interval computation.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class DescriptiveStats:
    """Standard descriptive statistics for a sample."""
    count: int = 0
    mean: float = 0.0
    median: float = 0.0
    stddev: float = 0.0
    variance: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    range_val: float = 0.0
    p5: float = 0.0
    p25: float = 0.0
    p75: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    iqr: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    coefficient_of_variation: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {k: round(v, 6) if isinstance(v, float) else v for k, v in self.__dict__.items()}


class MeasurementAnalyzer:
    """
    Comprehensive statistical analyzer for network measurements.

    Provides descriptive statistics, outlier detection, trend analysis,
    moving averages, and confidence intervals.

    Usage:
        analyzer = MeasurementAnalyzer(data=[1.2, 1.5, 1.3, ...])
        stats = analyzer.descriptive_stats()
        outliers = analyzer.detect_outliers()
        trend = analyzer.linear_trend()
    """

    def __init__(self, data: List[float]):
        self.data = np.array(data, dtype=np.float64)
        if len(self.data) == 0:
            raise ValueError("Cannot analyze empty dataset")

    def descriptive_stats(self) -> DescriptiveStats:
        """Compute full descriptive statistics."""
        d = self.data
        n = len(d)
        mean = float(np.mean(d))
        stddev = float(np.std(d, ddof=1)) if n > 1 else 0.0
        variance = stddev ** 2

        p25 = float(np.percentile(d, 25))
        p75 = float(np.percentile(d, 75))

        # Skewness (Fisher's definition)
        if stddev > 0 and n > 2:
            skewness = float(np.mean(((d - mean) / stddev) ** 3))
        else:
            skewness = 0.0

        # Excess kurtosis
        if stddev > 0 and n > 3:
            kurtosis = float(np.mean(((d - mean) / stddev) ** 4) - 3.0)
        else:
            kurtosis = 0.0

        cv = (stddev / mean * 100.0) if mean != 0 else 0.0

        return DescriptiveStats(
            count=n,
            mean=mean,
            median=float(np.median(d)),
            stddev=stddev,
            variance=variance,
            min_val=float(np.min(d)),
            max_val=float(np.max(d)),
            range_val=float(np.max(d) - np.min(d)),
            p5=float(np.percentile(d, 5)),
            p25=p25,
            p75=p75,
            p90=float(np.percentile(d, 90)),
            p95=float(np.percentile(d, 95)),
            p99=float(np.percentile(d, 99)),
            iqr=p75 - p25,
            skewness=skewness,
            kurtosis=kurtosis,
            coefficient_of_variation=cv,
        )

    def detect_outliers(self, method: str = "iqr", threshold: float = 1.5) -> Dict[str, Any]:
        """
        Detect outliers using IQR or Z-score method.

        Args:
            method: "iqr" or "zscore"
            threshold: 1.5 for IQR (mild), 3.0 for IQR (extreme),
                       or z-score threshold (typically 2.0 or 3.0).

        Returns:
            Dict with outlier indices, values, count, and bounds.
        """
        if method == "iqr":
            q1 = float(np.percentile(self.data, 25))
            q3 = float(np.percentile(self.data, 75))
            iqr = q3 - q1
            lower = q1 - threshold * iqr
            upper = q3 + threshold * iqr
            mask = (self.data < lower) | (self.data > upper)
        elif method == "zscore":
            mean = np.mean(self.data)
            std = np.std(self.data, ddof=1)
            if std == 0:
                mask = np.zeros(len(self.data), dtype=bool)
                lower, upper = mean, mean
            else:
                z_scores = np.abs((self.data - mean) / std)
                mask = z_scores > threshold
                lower = mean - threshold * std
                upper = mean + threshold * std
        else:
            raise ValueError(f"Unknown method: {method}")

        outlier_indices = np.where(mask)[0].tolist()
        return {
            "method": method,
            "threshold": threshold,
            "lower_bound": round(lower, 6),
            "upper_bound": round(upper, 6),
            "outlier_count": int(np.sum(mask)),
            "outlier_percent": round(float(np.sum(mask)) / len(self.data) * 100, 2),
            "outlier_indices": outlier_indices,
            "outlier_values": [round(float(self.data[i]), 6) for i in outlier_indices],
        }

    def linear_trend(self) -> Dict[str, Any]:
        """
        Fit a linear trend to the data and return slope and R-squared.

        Useful for detecting whether latency or jitter is increasing over time.
        """
        n = len(self.data)
        if n < 2:
            return {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}

        x = np.arange(n, dtype=np.float64)
        coeffs = np.polyfit(x, self.data, 1)
        slope, intercept = float(coeffs[0]), float(coeffs[1])

        # R-squared
        predicted = np.polyval(coeffs, x)
        ss_res = np.sum((self.data - predicted) ** 2)
        ss_tot = np.sum((self.data - np.mean(self.data)) ** 2)
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        return {
            "slope": round(slope, 8),
            "intercept": round(intercept, 6),
            "r_squared": round(r_squared, 6),
            "trend_direction": "increasing" if slope > 0.001 else "decreasing" if slope < -0.001 else "stable",
        }

    def moving_average(self, window: int = 10) -> List[float]:
        """Compute a simple moving average with the given window size."""
        if window >= len(self.data):
            return [float(np.mean(self.data))]
        kernel = np.ones(window) / window
        ma = np.convolve(self.data, kernel, mode="valid")
        return [round(float(v), 6) for v in ma]

    def exponential_moving_average(self, alpha: float = 0.1) -> List[float]:
        """Compute an exponential moving average."""
        ema = [float(self.data[0])]
        for i in range(1, len(self.data)):
            ema.append(alpha * float(self.data[i]) + (1 - alpha) * ema[-1])
        return [round(v, 6) for v in ema]

    def confidence_interval(self, confidence: float = 0.95) -> Tuple[float, float]:
        """
        Compute the confidence interval for the mean using t-distribution approximation.

        Args:
            confidence: Confidence level (e.g., 0.95 for 95%).

        Returns:
            Tuple of (lower_bound, upper_bound).
        """
        n = len(self.data)
        mean = float(np.mean(self.data))
        if n < 2:
            return (mean, mean)

        stderr = float(np.std(self.data, ddof=1) / math.sqrt(n))

        # Approximate t-value for common confidence levels
        t_values = {
            0.90: 1.645,
            0.95: 1.96,
            0.99: 2.576,
        }
        t_val = t_values.get(confidence, 1.96)

        margin = t_val * stderr
        return (round(mean - margin, 6), round(mean + margin, 6))

    def histogram(self, bins: int = 20) -> Dict[str, Any]:
        """Compute histogram data for the measurement samples."""
        counts, edges = np.histogram(self.data, bins=bins)
        return {
            "bin_edges": [round(float(e), 6) for e in edges],
            "counts": counts.tolist(),
            "bins": bins,
        }

    def stability_index(self) -> float:
        """
        Compute a stability index (0-100) for the measurements.

        100 = perfectly stable, 0 = highly variable.
        Based on coefficient of variation and outlier ratio.
        """
        stats = self.descriptive_stats()
        outliers = self.detect_outliers()

        cv_score = max(0, 100 - stats.coefficient_of_variation * 2)
        outlier_score = max(0, 100 - outliers["outlier_percent"] * 5)

        return round((cv_score * 0.7 + outlier_score * 0.3), 2)
