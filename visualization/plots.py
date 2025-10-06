"""
Matplotlib visualization module for network measurements.

Generates publication-quality plots for latency, jitter, packet loss,
throughput, congestion analysis, and comparative multi-host views.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for headless rendering
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.ticker import FuncFormatter

from utils import format_bps, logger


# Consistent style
plt.style.use("seaborn-v0_8-whitegrid") if "seaborn-v0_8-whitegrid" in plt.style.available else None
COLORS = ["#2196F3", "#FF5722", "#4CAF50", "#9C27B0", "#FF9800", "#607D8B"]


class NetworkPlotter:
    """
    Creates matplotlib visualizations for network measurement data.

    All plot methods accept data in dictionary form (as returned by
    measurement result .to_dict() methods) and save to the specified
    output directory.

    Usage:
        plotter = NetworkPlotter(output_dir="plots/")
        plotter.plot_latency(latency_result.to_dict())
        plotter.plot_throughput_timeline(throughput_result.to_dict())
    """

    def __init__(self, output_dir: str = "plots", dpi: int = 150, figsize: tuple = (12, 6)):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.dpi = dpi
        self.figsize = figsize

    def plot_latency(self, data: Dict[str, Any], filename: str = "latency.png") -> str:
        """
        Generate a comprehensive latency plot with:
        - Time series of RTT samples
        - Histogram of RTT distribution
        - Percentile markers
        """
        rtt = data.get("rtt_samples_ms", [])
        if not rtt:
            logger.warning("No RTT samples to plot")
            return ""

        fig, axes = plt.subplots(1, 2, figsize=(self.figsize[0], self.figsize[1]))

        # Time series
        ax1 = axes[0]
        ax1.plot(rtt, color=COLORS[0], linewidth=0.8, alpha=0.7)
        mean_val = data.get("mean_rtt_ms", np.mean(rtt))
        p95_val = data.get("p95_rtt_ms", np.percentile(rtt, 95))
        ax1.axhline(y=mean_val, color=COLORS[2], linestyle="--", linewidth=1.5, label=f"Mean: {mean_val:.2f} ms")
        ax1.axhline(y=p95_val, color=COLORS[1], linestyle=":", linewidth=1.5, label=f"P95: {p95_val:.2f} ms")
        ax1.set_xlabel("Probe Number")
        ax1.set_ylabel("RTT (ms)")
        ax1.set_title(f"Latency to {data.get('host', 'unknown')}")
        ax1.legend(loc="upper right", fontsize=9)

        # Histogram
        ax2 = axes[1]
        ax2.hist(rtt, bins=40, color=COLORS[0], alpha=0.7, edgecolor="white")
        ax2.axvline(x=mean_val, color=COLORS[2], linestyle="--", linewidth=1.5, label=f"Mean: {mean_val:.2f} ms")
        ax2.axvline(x=p95_val, color=COLORS[1], linestyle=":", linewidth=1.5, label=f"P95: {p95_val:.2f} ms")
        ax2.set_xlabel("RTT (ms)")
        ax2.set_ylabel("Frequency")
        ax2.set_title("RTT Distribution")
        ax2.legend(fontsize=9)

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        logger.info("Latency plot saved to %s", path)
        return str(path)

    def plot_jitter(self, data: Dict[str, Any], filename: str = "jitter.png") -> str:
        """
        Generate jitter visualization with:
        - IPDV time series
        - Jitter distribution histogram
        - RFC 3550 smoothed jitter overlay
        """
        ipdv = data.get("ipdv_samples_ms", [])
        rtt = data.get("rtt_samples_ms", [])
        if not ipdv:
            logger.warning("No jitter samples to plot")
            return ""

        fig, axes = plt.subplots(1, 2, figsize=self.figsize)

        # IPDV time series
        ax1 = axes[0]
        ax1.plot(ipdv, color=COLORS[3], linewidth=0.8, alpha=0.7, label="IPDV")
        mean_j = data.get("mean_jitter_ms", np.mean(ipdv))
        ax1.axhline(y=mean_j, color=COLORS[2], linestyle="--", linewidth=1.5, label=f"Mean: {mean_j:.3f} ms")

        # Compute and overlay RFC 3550 smoothed jitter
        j_smooth = [0.0]
        for d in ipdv:
            j_smooth.append(j_smooth[-1] + (abs(d) - j_smooth[-1]) / 16.0)
        ax1.plot(j_smooth[1:], color=COLORS[1], linewidth=1.5, alpha=0.8, label="RFC 3550 smoothed")

        ax1.set_xlabel("Probe Pair Index")
        ax1.set_ylabel("Jitter (ms)")
        ax1.set_title(f"Jitter to {data.get('host', 'unknown')}")
        ax1.legend(fontsize=9)

        # Histogram
        ax2 = axes[1]
        ax2.hist(ipdv, bins=40, color=COLORS[3], alpha=0.7, edgecolor="white")
        ax2.set_xlabel("IPDV (ms)")
        ax2.set_ylabel("Frequency")
        ax2.set_title("Jitter Distribution")

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        logger.info("Jitter plot saved to %s", path)
        return str(path)

    def plot_packet_loss(self, data: Dict[str, Any], filename: str = "packet_loss.png") -> str:
        """
        Generate packet loss visualization with:
        - Probe success/failure timeline
        - Loss burst analysis bar chart
        - Cumulative loss rate
        """
        timeline = data.get("probe_timeline", [])
        if not timeline:
            logger.warning("No probe timeline to plot")
            return ""

        fig, axes = plt.subplots(2, 1, figsize=(self.figsize[0], self.figsize[1] * 1.3))

        # Success/failure timeline (scatter)
        ax1 = axes[0]
        seqs = [p["seq"] for p in timeline]
        success = [1 if p["success"] else 0 for p in timeline]
        colors = [COLORS[2] if s else COLORS[1] for s in success]
        ax1.scatter(seqs, success, c=colors, s=8, alpha=0.7, edgecolors="none")
        ax1.set_yticks([0, 1])
        ax1.set_yticklabels(["Lost", "OK"])
        ax1.set_xlabel("Probe Sequence")
        ax1.set_title(
            f"Packet Loss Timeline - {data.get('host', 'unknown')} "
            f"({data.get('loss_percent', 0):.2f}% loss)"
        )

        # Cumulative loss rate
        ax2 = axes[1]
        cumulative_loss = []
        lost_so_far = 0
        for i, p in enumerate(timeline):
            if not p["success"]:
                lost_so_far += 1
            cumulative_loss.append(lost_so_far / (i + 1) * 100.0)

        ax2.plot(seqs, cumulative_loss, color=COLORS[1], linewidth=1.5)
        ax2.set_xlabel("Probe Sequence")
        ax2.set_ylabel("Cumulative Loss Rate (%)")
        ax2.set_title("Cumulative Packet Loss Rate")
        ax2.set_ylim(bottom=0)

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        logger.info("Packet loss plot saved to %s", path)
        return str(path)

    def plot_throughput(self, data: Dict[str, Any], filename: str = "throughput.png") -> str:
        """
        Generate throughput visualization with:
        - Throughput over time (bar chart per interval)
        - Mean/max markers
        """
        samples = data.get("samples", [])
        if not samples:
            logger.warning("No throughput samples to plot")
            return ""

        fig, ax = plt.subplots(figsize=self.figsize)

        intervals = list(range(len(samples)))
        bps_values = [s["bps"] for s in samples]

        # Convert to Mbps for display
        mbps_values = [b / 1_000_000 for b in bps_values]

        ax.bar(intervals, mbps_values, color=COLORS[0], alpha=0.7, edgecolor="white", width=0.8)

        mean_mbps = np.mean(mbps_values)
        max_mbps = np.max(mbps_values)
        ax.axhline(y=mean_mbps, color=COLORS[2], linestyle="--", linewidth=1.5, label=f"Mean: {mean_mbps:.2f} Mbps")
        ax.axhline(y=max_mbps, color=COLORS[1], linestyle=":", linewidth=1.0, label=f"Max: {max_mbps:.2f} Mbps")

        ax.set_xlabel("Interval (seconds)")
        ax.set_ylabel("Throughput (Mbps)")
        ax.set_title(
            f"{data.get('protocol', 'TCP').upper()} Throughput to {data.get('host', 'unknown')} "
            f"- {data.get('total_throughput', '')}"
        )
        ax.legend(fontsize=10)
        ax.set_ylim(bottom=0)

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        logger.info("Throughput plot saved to %s", path)
        return str(path)

    def plot_congestion_analysis(
        self,
        rtt_samples: List[float],
        congestion_events: List[Dict[str, Any]],
        filename: str = "congestion.png",
    ) -> str:
        """
        Generate congestion analysis visualization with:
        - RTT time series with congestion events highlighted
        - Moving average overlay
        """
        if not rtt_samples:
            return ""

        fig, ax = plt.subplots(figsize=self.figsize)

        ax.plot(rtt_samples, color=COLORS[0], linewidth=0.6, alpha=0.5, label="RTT")

        # Moving average
        window = min(20, len(rtt_samples) // 4)
        if window > 1:
            kernel = np.ones(window) / window
            ma = np.convolve(rtt_samples, kernel, mode="valid")
            offset = window // 2
            ax.plot(range(offset, offset + len(ma)), ma, color=COLORS[5], linewidth=2, label=f"MA({window})")

        # Highlight congestion events
        for event in congestion_events:
            start = event.get("start_index", 0)
            end = event.get("end_index", 0)
            severity = event.get("severity", "mild")
            color_map = {"mild": "#FFEB3B", "moderate": "#FF9800", "severe": "#F44336"}
            ax.axvspan(start, end, alpha=0.25, color=color_map.get(severity, "#FFEB3B"))

        ax.set_xlabel("Sample Index")
        ax.set_ylabel("RTT (ms)")
        ax.set_title("Congestion Analysis - RTT with Detected Events")
        ax.legend(fontsize=10)

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        logger.info("Congestion analysis plot saved to %s", path)
        return str(path)

    def plot_traffic_profile(
        self,
        send_rates: List[float],
        profile_name: str = "",
        filename: str = "traffic_profile.png",
    ) -> str:
        """Plot traffic generation rate over time."""
        if not send_rates:
            return ""

        fig, ax = plt.subplots(figsize=self.figsize)
        ax.plot(send_rates, color=COLORS[4], linewidth=2)
        ax.fill_between(range(len(send_rates)), send_rates, alpha=0.2, color=COLORS[4])
        ax.set_xlabel("Time (seconds)")
        ax.set_ylabel("Send Rate (packets/sec)")
        ax.set_title(f"Traffic Generation Profile: {profile_name}")
        ax.set_ylim(bottom=0)

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        return str(path)

    def plot_comparative_latency(
        self,
        host_results: Dict[str, Dict[str, Any]],
        filename: str = "comparative_latency.png",
    ) -> str:
        """
        Generate a comparative latency box plot across multiple hosts.

        Args:
            host_results: Dict mapping host labels to their latency result dicts.
        """
        if not host_results:
            return ""

        fig, ax = plt.subplots(figsize=self.figsize)

        labels = list(host_results.keys())
        data = [host_results[label].get("rtt_samples_ms", []) for label in labels]

        bp = ax.boxplot(
            data, labels=labels, patch_artist=True,
            medianprops={"color": "white", "linewidth": 2},
        )
        for i, box in enumerate(bp["boxes"]):
            box.set_facecolor(COLORS[i % len(COLORS)])
            box.set_alpha(0.7)

        ax.set_ylabel("RTT (ms)")
        ax.set_title("Comparative Latency Across Hosts")

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        return str(path)

    def plot_dashboard(
        self,
        latency_data: Optional[Dict] = None,
        jitter_data: Optional[Dict] = None,
        loss_data: Optional[Dict] = None,
        throughput_data: Optional[Dict] = None,
        filename: str = "dashboard.png",
    ) -> str:
        """
        Generate a 2x2 dashboard with all four measurement types.
        """
        fig = plt.figure(figsize=(16, 12))
        gs = gridspec.GridSpec(2, 2, hspace=0.35, wspace=0.3)

        # Latency
        ax1 = fig.add_subplot(gs[0, 0])
        if latency_data and latency_data.get("rtt_samples_ms"):
            rtt = latency_data["rtt_samples_ms"]
            ax1.plot(rtt, color=COLORS[0], linewidth=0.8, alpha=0.7)
            ax1.axhline(y=latency_data.get("mean_rtt_ms", 0), color=COLORS[2], linestyle="--")
            ax1.set_title(f"Latency ({latency_data.get('mean_rtt_ms', 0):.2f} ms mean)")
        else:
            ax1.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax1.transAxes)
            ax1.set_title("Latency")
        ax1.set_xlabel("Probe #")
        ax1.set_ylabel("RTT (ms)")

        # Jitter
        ax2 = fig.add_subplot(gs[0, 1])
        if jitter_data and jitter_data.get("ipdv_samples_ms"):
            ipdv = jitter_data["ipdv_samples_ms"]
            ax2.plot(ipdv, color=COLORS[3], linewidth=0.8, alpha=0.7)
            ax2.axhline(y=jitter_data.get("mean_jitter_ms", 0), color=COLORS[2], linestyle="--")
            ax2.set_title(f"Jitter ({jitter_data.get('mean_jitter_ms', 0):.3f} ms mean)")
        else:
            ax2.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax2.transAxes)
            ax2.set_title("Jitter")
        ax2.set_xlabel("Probe Pair #")
        ax2.set_ylabel("IPDV (ms)")

        # Packet Loss
        ax3 = fig.add_subplot(gs[1, 0])
        if loss_data and loss_data.get("probe_timeline"):
            timeline = loss_data["probe_timeline"]
            seqs = [p["seq"] for p in timeline]
            success_vals = [1 if p["success"] else 0 for p in timeline]
            colors_list = [COLORS[2] if s else COLORS[1] for s in success_vals]
            ax3.scatter(seqs, success_vals, c=colors_list, s=6, alpha=0.6, edgecolors="none")
            ax3.set_yticks([0, 1])
            ax3.set_yticklabels(["Lost", "OK"])
            ax3.set_title(f"Packet Loss ({loss_data.get('loss_percent', 0):.2f}%)")
        else:
            ax3.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax3.transAxes)
            ax3.set_title("Packet Loss")
        ax3.set_xlabel("Probe #")

        # Throughput
        ax4 = fig.add_subplot(gs[1, 1])
        if throughput_data and throughput_data.get("samples"):
            samples = throughput_data["samples"]
            mbps = [s["bps"] / 1_000_000 for s in samples]
            ax4.bar(range(len(mbps)), mbps, color=COLORS[0], alpha=0.7, edgecolor="white")
            ax4.set_title(f"Throughput ({throughput_data.get('total_throughput', '')})")
        else:
            ax4.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax4.transAxes)
            ax4.set_title("Throughput")
        ax4.set_xlabel("Interval (s)")
        ax4.set_ylabel("Mbps")

        fig.suptitle("Network Performance Dashboard", fontsize=16, fontweight="bold", y=0.98)

        path = self.output_dir / filename
        fig.savefig(path, dpi=self.dpi, bbox_inches="tight")
        plt.close(fig)
        logger.info("Dashboard saved to %s", path)
        return str(path)
