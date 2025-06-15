"""
Latency measurement module.

Supports ICMP Echo (ping) and TCP SYN-based latency probing with
full RTT statistics: min, max, mean, median, stddev, percentiles.
"""

import socket
import struct
import time
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import numpy as np

from utils import (
    build_icmp_echo_request,
    parse_icmp_echo_reply,
    high_res_timer,
    validate_host,
    validate_port,
    logger,
)


@dataclass
class LatencyResult:
    """Container for latency measurement results."""
    host: str
    resolved_ip: str
    probe_count: int
    successful_probes: int
    failed_probes: int
    rtt_samples: List[float] = field(default_factory=list)  # in milliseconds
    min_rtt: float = 0.0
    max_rtt: float = 0.0
    mean_rtt: float = 0.0
    median_rtt: float = 0.0
    stddev_rtt: float = 0.0
    p95_rtt: float = 0.0
    p99_rtt: float = 0.0
    loss_percent: float = 0.0

    def compute_stats(self):
        """Compute aggregate statistics from RTT samples."""
        if not self.rtt_samples:
            return
        arr = np.array(self.rtt_samples)
        self.min_rtt = float(np.min(arr))
        self.max_rtt = float(np.max(arr))
        self.mean_rtt = float(np.mean(arr))
        self.median_rtt = float(np.median(arr))
        self.stddev_rtt = float(np.std(arr))
        self.p95_rtt = float(np.percentile(arr, 95))
        self.p99_rtt = float(np.percentile(arr, 99))
        self.loss_percent = (
            (self.failed_probes / self.probe_count) * 100.0
            if self.probe_count > 0
            else 0.0
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "host": self.host,
            "resolved_ip": self.resolved_ip,
            "probe_count": self.probe_count,
            "successful_probes": self.successful_probes,
            "failed_probes": self.failed_probes,
            "rtt_samples_ms": self.rtt_samples,
            "min_rtt_ms": round(self.min_rtt, 4),
            "max_rtt_ms": round(self.max_rtt, 4),
            "mean_rtt_ms": round(self.mean_rtt, 4),
            "median_rtt_ms": round(self.median_rtt, 4),
            "stddev_rtt_ms": round(self.stddev_rtt, 4),
            "p95_rtt_ms": round(self.p95_rtt, 4),
            "p99_rtt_ms": round(self.p99_rtt, 4),
            "loss_percent": round(self.loss_percent, 2),
        }


class LatencyMeasurer:
    """
    Measures network latency using ICMP Echo or TCP SYN probes.

    Usage:
        measurer = LatencyMeasurer(host="8.8.8.8", count=100)
        result = measurer.run()
        print(result.mean_rtt)
    """

    def __init__(
        self,
        host: str,
        count: int = 100,
        timeout: float = 2.0,
        interval: float = 0.1,
        payload_size: int = 64,
        use_tcp: bool = False,
        tcp_port: int = 80,
    ):
        self.host = host
        self.resolved_ip = validate_host(host)
        self.count = count
        self.timeout = timeout
        self.interval = interval
        self.payload_size = payload_size
        self.use_tcp = use_tcp
        self.tcp_port = validate_port(tcp_port)

    def run(self) -> LatencyResult:
        """Execute the latency measurement and return results."""
        if self.use_tcp:
            return self._run_tcp()
        return self._run_icmp()

    def _run_icmp(self) -> LatencyResult:
        """Perform ICMP-based latency measurement using raw sockets."""
        result = LatencyResult(
            host=self.host,
            resolved_ip=self.resolved_ip,
            probe_count=self.count,
            successful_probes=0,
            failed_probes=0,
        )

        identifier = os.getpid() & 0xFFFF

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            sock.settimeout(self.timeout)
        except PermissionError:
            logger.error(
                "Raw socket creation failed. ICMP probes require root/admin privileges. "
                "Falling back to TCP probe on port %d.",
                self.tcp_port,
            )
            self.use_tcp = True
            return self._run_tcp()

        try:
            for seq in range(self.count):
                packet = build_icmp_echo_request(identifier, seq, self.payload_size)
                try:
                    send_time = high_res_timer()
                    sock.sendto(packet, (self.resolved_ip, 0))

                    while True:
                        data, addr = sock.recvfrom(4096)
                        recv_time = high_res_timer()
                        parsed = parse_icmp_echo_reply(data)
                        # Verify this is our reply
                        if (
                            parsed["type"] == 0
                            and parsed["identifier"] == identifier
                            and parsed["sequence"] == seq
                        ):
                            rtt_ms = (recv_time - send_time) * 1000.0
                            result.rtt_samples.append(rtt_ms)
                            result.successful_probes += 1
                            break
                except socket.timeout:
                    result.failed_probes += 1
                    logger.debug("ICMP probe %d timed out", seq)
                except OSError as exc:
                    result.failed_probes += 1
                    logger.debug("ICMP probe %d error: %s", seq, exc)

                if seq < self.count - 1:
                    time.sleep(self.interval)
        finally:
            sock.close()

        result.compute_stats()
        return result

    def _run_tcp(self) -> LatencyResult:
        """
        Perform TCP SYN-based latency measurement.

        Measures the time to complete a TCP handshake (connect + close).
        Does not require root privileges.
        """
        result = LatencyResult(
            host=self.host,
            resolved_ip=self.resolved_ip,
            probe_count=self.count,
            successful_probes=0,
            failed_probes=0,
        )

        for seq in range(self.count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            try:
                start = high_res_timer()
                sock.connect((self.resolved_ip, self.tcp_port))
                end = high_res_timer()
                rtt_ms = (end - start) * 1000.0
                result.rtt_samples.append(rtt_ms)
                result.successful_probes += 1
            except (socket.timeout, OSError) as exc:
                result.failed_probes += 1
                logger.debug("TCP probe %d to %s:%d failed: %s", seq, self.resolved_ip, self.tcp_port, exc)
            finally:
                sock.close()

            if seq < self.count - 1:
                time.sleep(self.interval)

        result.compute_stats()
        return result
