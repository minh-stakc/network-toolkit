"""
Congestion detection and analysis module.

Analyzes network measurement data to detect congestion events,
characterize congestion patterns, and provide actionable insights.
Uses RTT inflation, loss spikes, and throughput degradation as signals.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from utils import logger


@dataclass
class CongestionEvent:
    """A detected congestion event with timing and severity."""
    start_index: int
    end_index: int
    duration_samples: int
    severity: str            # "mild", "moderate", "severe"
    signal: str              # "rtt_inflation", "loss_spike", "throughput_drop"
    peak_value: float        # peak RTT, loss rate, or throughput drop %
    baseline_value: float    # reference value before congestion
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_index": self.start_index,
            "end_index": self.end_index,
            "duration_samples": self.duration_samples,
            "severity": self.severity,
            "signal": self.signal,
            "peak_value": round(self.peak_value, 4),
            "baseline_value": round(self.baseline_value, 4),
            "details": self.details,
        }


@dataclass
class CongestionReport:
    """Summary report of congestion analysis."""
    events: List[CongestionEvent] = field(default_factory=list)
    total_events: int = 0
    mild_events: int = 0
    moderate_events: int = 0
    severe_events: int = 0
    congestion_ratio: float = 0.0  # fraction of samples in congestion
    max_severity: str = "none"
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_events": self.total_events,
            "mild_events": self.mild_events,
            "moderate_events": self.moderate_events,
            "severe_events": self.severe_events,
            "congestion_ratio": round(self.congestion_ratio, 4),
            "max_severity": self.max_severity,
            "events": [e.to_dict() for e in self.events],
            "recommendations": self.recommendations,
        }


class CongestionAnalyzer:
    """
    Analyzes measurement data for congestion indicators.

    Detection signals:
    - RTT inflation: sustained increase above baseline RTT
    - Loss spikes: sudden increases in packet loss rate
    - Throughput degradation: sustained drop below baseline throughput

    Usage:
        analyzer = CongestionAnalyzer()
        report = analyzer.analyze_rtt(rtt_samples)
        report = analyzer.full_analysis(rtt=rtt_samples, loss=loss_flags, throughput=tp_samples)
    """

    def __init__(
        self,
        rtt_inflation_threshold: float = 2.0,    # factor above baseline
        loss_spike_threshold: float = 5.0,         # percent loss in window
        throughput_drop_threshold: float = 0.5,    # fraction of baseline
        window_size: int = 10,                      # samples per analysis window
    ):
        self.rtt_inflation_threshold = rtt_inflation_threshold
        self.loss_spike_threshold = loss_spike_threshold
        self.throughput_drop_threshold = throughput_drop_threshold
        self.window_size = window_size

    def analyze_rtt(self, rtt_samples: List[float]) -> CongestionReport:
        """
        Detect congestion from RTT inflation patterns.

        Establishes a baseline from the first window of samples, then
        flags windows where the mean RTT exceeds the threshold.
        """
        report = CongestionReport()
        arr = np.array(rtt_samples, dtype=np.float64)
        n = len(arr)

        if n < self.window_size * 2:
            report.recommendations.append("Insufficient samples for RTT congestion analysis.")
            return report

        # Establish baseline from first window (assumed uncongested)
        baseline = float(np.median(arr[:self.window_size]))
        threshold = baseline * self.rtt_inflation_threshold
        total_congested = 0

        in_event = False
        event_start = 0

        for i in range(0, n - self.window_size + 1, self.window_size):
            window = arr[i:i + self.window_size]
            window_mean = float(np.mean(window))
            window_max = float(np.max(window))

            if window_mean > threshold:
                total_congested += self.window_size
                if not in_event:
                    in_event = True
                    event_start = i
            else:
                if in_event:
                    event_end = i
                    peak = float(np.max(arr[event_start:event_end]))
                    inflation = peak / baseline if baseline > 0 else 0
                    severity = self._classify_rtt_severity(inflation)

                    report.events.append(CongestionEvent(
                        start_index=event_start,
                        end_index=event_end,
                        duration_samples=event_end - event_start,
                        severity=severity,
                        signal="rtt_inflation",
                        peak_value=peak,
                        baseline_value=baseline,
                        details=f"RTT inflated {inflation:.1f}x above baseline ({baseline:.2f} ms)",
                    ))
                    in_event = False

        # Close trailing event
        if in_event:
            event_end = n
            peak = float(np.max(arr[event_start:event_end]))
            inflation = peak / baseline if baseline > 0 else 0
            severity = self._classify_rtt_severity(inflation)
            report.events.append(CongestionEvent(
                start_index=event_start,
                end_index=event_end,
                duration_samples=event_end - event_start,
                severity=severity,
                signal="rtt_inflation",
                peak_value=peak,
                baseline_value=baseline,
                details=f"RTT inflated {inflation:.1f}x (ongoing at end of test)",
            ))

        self._finalize_report(report, n, total_congested)
        return report

    def analyze_loss(self, loss_flags: List[bool]) -> CongestionReport:
        """
        Detect congestion from packet loss patterns.

        Analyzes loss flags (True = lost) in windows, flagging windows
        where loss rate exceeds the threshold.
        """
        report = CongestionReport()
        arr = np.array(loss_flags, dtype=bool)
        n = len(arr)

        if n < self.window_size:
            report.recommendations.append("Insufficient samples for loss congestion analysis.")
            return report

        total_congested = 0
        in_event = False
        event_start = 0
        baseline_loss = 0.0  # assume zero baseline loss

        for i in range(0, n - self.window_size + 1, self.window_size):
            window = arr[i:i + self.window_size]
            loss_pct = float(np.sum(window)) / self.window_size * 100.0

            if loss_pct > self.loss_spike_threshold:
                total_congested += self.window_size
                if not in_event:
                    in_event = True
                    event_start = i
            else:
                if in_event:
                    event_end = i
                    # Find peak loss window in the event
                    peak_loss = 0.0
                    for j in range(event_start, event_end, self.window_size):
                        w = arr[j:j + self.window_size]
                        wl = float(np.sum(w)) / len(w) * 100.0
                        peak_loss = max(peak_loss, wl)

                    severity = self._classify_loss_severity(peak_loss)
                    report.events.append(CongestionEvent(
                        start_index=event_start,
                        end_index=event_end,
                        duration_samples=event_end - event_start,
                        severity=severity,
                        signal="loss_spike",
                        peak_value=peak_loss,
                        baseline_value=baseline_loss,
                        details=f"Peak loss {peak_loss:.1f}% over {event_end - event_start} samples",
                    ))
                    in_event = False

        if in_event:
            event_end = n
            peak_loss = 0.0
            for j in range(event_start, event_end, self.window_size):
                w = arr[j:j + self.window_size]
                wl = float(np.sum(w)) / len(w) * 100.0
                peak_loss = max(peak_loss, wl)
            severity = self._classify_loss_severity(peak_loss)
            report.events.append(CongestionEvent(
                start_index=event_start,
                end_index=event_end,
                duration_samples=event_end - event_start,
                severity=severity,
                signal="loss_spike",
                peak_value=peak_loss,
                baseline_value=baseline_loss,
                details=f"Peak loss {peak_loss:.1f}% (ongoing at end of test)",
            ))

        self._finalize_report(report, n, total_congested)
        return report

    def analyze_throughput(self, throughput_samples: List[float]) -> CongestionReport:
        """
        Detect congestion from throughput degradation.

        Establishes a baseline from peak throughput, then flags windows
        where throughput drops below the threshold fraction.
        """
        report = CongestionReport()
        arr = np.array(throughput_samples, dtype=np.float64)
        n = len(arr)

        if n < self.window_size:
            report.recommendations.append("Insufficient samples for throughput congestion analysis.")
            return report

        baseline = float(np.percentile(arr, 90))  # use 90th percentile as "achievable" baseline
        threshold = baseline * self.throughput_drop_threshold
        total_congested = 0

        in_event = False
        event_start = 0

        for i in range(n):
            if arr[i] < threshold:
                total_congested += 1
                if not in_event:
                    in_event = True
                    event_start = i
            else:
                if in_event:
                    event_end = i
                    trough = float(np.min(arr[event_start:event_end]))
                    drop_pct = (1.0 - trough / baseline) * 100 if baseline > 0 else 0
                    severity = self._classify_throughput_severity(drop_pct)

                    report.events.append(CongestionEvent(
                        start_index=event_start,
                        end_index=event_end,
                        duration_samples=event_end - event_start,
                        severity=severity,
                        signal="throughput_drop",
                        peak_value=drop_pct,
                        baseline_value=baseline,
                        details=f"Throughput dropped {drop_pct:.1f}% below baseline",
                    ))
                    in_event = False

        if in_event:
            event_end = n
            trough = float(np.min(arr[event_start:event_end]))
            drop_pct = (1.0 - trough / baseline) * 100 if baseline > 0 else 0
            severity = self._classify_throughput_severity(drop_pct)
            report.events.append(CongestionEvent(
                start_index=event_start,
                end_index=event_end,
                duration_samples=event_end - event_start,
                severity=severity,
                signal="throughput_drop",
                peak_value=drop_pct,
                baseline_value=baseline,
                details=f"Throughput dropped {drop_pct:.1f}% (ongoing)",
            ))

        self._finalize_report(report, n, total_congested)
        return report

    def full_analysis(
        self,
        rtt: Optional[List[float]] = None,
        loss: Optional[List[bool]] = None,
        throughput: Optional[List[float]] = None,
    ) -> CongestionReport:
        """
        Run congestion analysis across all available signal types.

        Merges events from RTT, loss, and throughput analyses into
        a unified report.
        """
        combined = CongestionReport()

        if rtt and len(rtt) >= self.window_size * 2:
            rtt_report = self.analyze_rtt(rtt)
            combined.events.extend(rtt_report.events)

        if loss and len(loss) >= self.window_size:
            loss_report = self.analyze_loss(loss)
            combined.events.extend(loss_report.events)

        if throughput and len(throughput) >= self.window_size:
            tp_report = self.analyze_throughput(throughput)
            combined.events.extend(tp_report.events)

        # Sort events by start index
        combined.events.sort(key=lambda e: e.start_index)

        total_samples = max(
            len(rtt) if rtt else 0,
            len(loss) if loss else 0,
            len(throughput) if throughput else 0,
        )
        total_congested = sum(e.duration_samples for e in combined.events)
        self._finalize_report(combined, total_samples, total_congested)

        # Generate recommendations
        combined.recommendations = self._generate_recommendations(combined)

        return combined

    def _classify_rtt_severity(self, inflation_factor: float) -> str:
        if inflation_factor > 5.0:
            return "severe"
        elif inflation_factor > 3.0:
            return "moderate"
        return "mild"

    def _classify_loss_severity(self, loss_pct: float) -> str:
        if loss_pct > 20.0:
            return "severe"
        elif loss_pct > 10.0:
            return "moderate"
        return "mild"

    def _classify_throughput_severity(self, drop_pct: float) -> str:
        if drop_pct > 80.0:
            return "severe"
        elif drop_pct > 50.0:
            return "moderate"
        return "mild"

    def _finalize_report(self, report: CongestionReport, total_samples: int, total_congested: int):
        """Fill in summary fields of a congestion report."""
        report.total_events = len(report.events)
        report.mild_events = sum(1 for e in report.events if e.severity == "mild")
        report.moderate_events = sum(1 for e in report.events if e.severity == "moderate")
        report.severe_events = sum(1 for e in report.events if e.severity == "severe")
        report.congestion_ratio = total_congested / total_samples if total_samples > 0 else 0.0

        if report.severe_events > 0:
            report.max_severity = "severe"
        elif report.moderate_events > 0:
            report.max_severity = "moderate"
        elif report.mild_events > 0:
            report.max_severity = "mild"
        else:
            report.max_severity = "none"

    def _generate_recommendations(self, report: CongestionReport) -> List[str]:
        """Generate actionable recommendations based on detected congestion."""
        recs = []

        rtt_events = [e for e in report.events if e.signal == "rtt_inflation"]
        loss_events = [e for e in report.events if e.signal == "loss_spike"]
        tp_events = [e for e in report.events if e.signal == "throughput_drop"]

        if not report.events:
            recs.append("No congestion detected. Network path appears healthy.")
            return recs

        if report.severe_events > 0:
            recs.append("CRITICAL: Severe congestion detected. Immediate investigation recommended.")

        if rtt_events and loss_events:
            recs.append(
                "RTT inflation with concurrent packet loss indicates buffer-bloat or "
                "link saturation. Consider implementing AQM (e.g., CoDel, FQ-CoDel)."
            )

        if rtt_events and not loss_events:
            recs.append(
                "RTT inflation without loss suggests bufferbloat. Deep packet buffers "
                "are absorbing excess traffic but adding latency."
            )

        if loss_events and not rtt_events:
            recs.append(
                "Packet loss without RTT inflation suggests tail-drop at a shallow buffer. "
                "Consider increasing buffer sizes or enabling ECN."
            )

        if tp_events:
            recs.append(
                "Throughput degradation detected. Possible causes: link saturation, "
                "TCP congestion window reduction, or upstream rate limiting."
            )

        if report.congestion_ratio > 0.5:
            recs.append(
                f"Congestion affects {report.congestion_ratio*100:.0f}% of samples. "
                "Consider upgrading link capacity or redistributing traffic."
            )

        return recs
