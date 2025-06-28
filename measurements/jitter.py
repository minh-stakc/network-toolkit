"""
Jitter measurement and analysis module.

Measures inter-packet delay variation (IPDV) and packet delay variation (PDV)
using sequential UDP or ICMP probes. Computes jitter statistics per RFC 3550.
"""

import socket
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np

from utils import high_res_timer, validate_host, validate_port, logger


@dataclass
class JitterResult:
    """Container for jitter measurement results."""
    host: str
    resolved_ip: str
    probe_count: int
    successful_probes: int
    rtt_samples: List[float] = field(default_factory=list)
    ipdv_samples: List[float] = field(default_factory=list)  # inter-packet delay variation
    mean_jitter: float = 0.0
    max_jitter: float = 0.0
    min_jitter: float = 0.0
    stddev_jitter: float = 0.0
    p95_jitter: float = 0.0
    p99_jitter: float = 0.0
    rfc3550_jitter: float = 0.0  # smoothed jitter per RFC 3550

    def compute_stats(self):
        """Compute jitter statistics from RTT samples."""
        if len(self.rtt_samples) < 2:
            return

        # Compute inter-packet delay variation (difference in consecutive RTTs)
        rtt_arr = np.array(self.rtt_samples)
        self.ipdv_samples = list(np.abs(np.diff(rtt_arr)))

        if not self.ipdv_samples:
            return

        ipdv_arr = np.array(self.ipdv_samples)
        self.mean_jitter = float(np.mean(ipdv_arr))
        self.max_jitter = float(np.max(ipdv_arr))
        self.min_jitter = float(np.min(ipdv_arr))
        self.stddev_jitter = float(np.std(ipdv_arr))
        self.p95_jitter = float(np.percentile(ipdv_arr, 95))
        self.p99_jitter = float(np.percentile(ipdv_arr, 99))

        # RFC 3550 smoothed jitter: J(i) = J(i-1) + (|D(i)| - J(i-1)) / 16
        j = 0.0
        for d in self.ipdv_samples:
            j = j + (abs(d) - j) / 16.0
        self.rfc3550_jitter = j

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "host": self.host,
            "resolved_ip": self.resolved_ip,
            "probe_count": self.probe_count,
            "successful_probes": self.successful_probes,
            "rtt_samples_ms": [round(r, 4) for r in self.rtt_samples],
            "ipdv_samples_ms": [round(j, 4) for j in self.ipdv_samples],
            "mean_jitter_ms": round(self.mean_jitter, 4),
            "max_jitter_ms": round(self.max_jitter, 4),
            "min_jitter_ms": round(self.min_jitter, 4),
            "stddev_jitter_ms": round(self.stddev_jitter, 4),
            "p95_jitter_ms": round(self.p95_jitter, 4),
            "p99_jitter_ms": round(self.p99_jitter, 4),
            "rfc3550_jitter_ms": round(self.rfc3550_jitter, 4),
        }


class JitterMeasurer:
    """
    Measures network jitter by sending sequential TCP probes and
    computing inter-packet delay variation from RTT differences.

    Usage:
        measurer = JitterMeasurer(host="8.8.8.8", count=50)
        result = measurer.run()
        print(result.mean_jitter)
    """

    def __init__(
        self,
        host: str,
        count: int = 100,
        interval: float = 0.05,
        timeout: float = 2.0,
        port: int = 80,
    ):
        self.host = host
        self.resolved_ip = validate_host(host)
        self.count = count
        self.interval = interval
        self.timeout = timeout
        self.port = validate_port(port)

    def run(self) -> JitterResult:
        """Execute jitter measurement using TCP connect probes."""
        result = JitterResult(
            host=self.host,
            resolved_ip=self.resolved_ip,
            probe_count=self.count,
            successful_probes=0,
        )

        for seq in range(self.count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            try:
                start = high_res_timer()
                sock.connect((self.resolved_ip, self.port))
                end = high_res_timer()
                rtt_ms = (end - start) * 1000.0
                result.rtt_samples.append(rtt_ms)
                result.successful_probes += 1
            except (socket.timeout, OSError) as exc:
                logger.debug("Jitter probe %d failed: %s", seq, exc)
            finally:
                sock.close()

            if seq < self.count - 1:
                time.sleep(self.interval)

        result.compute_stats()
        return result

    def run_udp(self, server_port: int = 5002) -> JitterResult:
        """
        Measure jitter using UDP echo probes.

        Requires a UDP echo server running on the target host.
        Each probe sends a timestamped packet and measures the RTT.
        """
        result = JitterResult(
            host=self.host,
            resolved_ip=self.resolved_ip,
            probe_count=self.count,
            successful_probes=0,
        )

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)

        try:
            for seq in range(self.count):
                payload = seq.to_bytes(4, byteorder="big") + time.time_ns().to_bytes(8, byteorder="big")
                try:
                    start = high_res_timer()
                    sock.sendto(payload, (self.resolved_ip, server_port))
                    data, addr = sock.recvfrom(1024)
                    end = high_res_timer()
                    rtt_ms = (end - start) * 1000.0
                    result.rtt_samples.append(rtt_ms)
                    result.successful_probes += 1
                except socket.timeout:
                    logger.debug("UDP jitter probe %d timed out", seq)
                except OSError as exc:
                    logger.debug("UDP jitter probe %d error: %s", seq, exc)

                if seq < self.count - 1:
                    time.sleep(self.interval)
        finally:
            sock.close()

        result.compute_stats()
        return result
