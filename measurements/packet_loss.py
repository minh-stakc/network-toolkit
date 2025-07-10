"""
Packet loss detection and reporting module.

Measures packet loss rates using configurable probe sequences.
Supports both continuous and burst-mode probing to detect different
loss patterns (random vs. burst loss).
"""

import socket
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from utils import high_res_timer, validate_host, validate_port, logger


@dataclass
class ProbeRecord:
    """Record of a single probe attempt."""
    sequence: int
    timestamp: float
    success: bool
    rtt_ms: Optional[float] = None


@dataclass
class PacketLossResult:
    """Container for packet loss measurement results."""
    host: str
    resolved_ip: str
    total_sent: int
    total_received: int
    total_lost: int
    loss_percent: float
    probe_records: List[ProbeRecord] = field(default_factory=list)
    burst_loss_events: List[Tuple[int, int]] = field(default_factory=list)  # (start_seq, length)
    max_burst_loss: int = 0
    mean_loss_burst_length: float = 0.0

    def analyze_bursts(self):
        """Identify consecutive loss bursts from probe records."""
        self.burst_loss_events = []
        current_burst_start = None
        current_burst_len = 0

        for record in self.probe_records:
            if not record.success:
                if current_burst_start is None:
                    current_burst_start = record.sequence
                    current_burst_len = 1
                else:
                    current_burst_len += 1
            else:
                if current_burst_start is not None:
                    self.burst_loss_events.append((current_burst_start, current_burst_len))
                    current_burst_start = None
                    current_burst_len = 0

        # Close any trailing burst
        if current_burst_start is not None:
            self.burst_loss_events.append((current_burst_start, current_burst_len))

        if self.burst_loss_events:
            burst_lengths = [length for _, length in self.burst_loss_events]
            self.max_burst_loss = max(burst_lengths)
            self.mean_loss_burst_length = float(np.mean(burst_lengths))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "host": self.host,
            "resolved_ip": self.resolved_ip,
            "total_sent": self.total_sent,
            "total_received": self.total_received,
            "total_lost": self.total_lost,
            "loss_percent": round(self.loss_percent, 4),
            "burst_loss_events": self.burst_loss_events,
            "max_burst_loss": self.max_burst_loss,
            "mean_loss_burst_length": round(self.mean_loss_burst_length, 4),
            "probe_timeline": [
                {
                    "seq": r.sequence,
                    "success": r.success,
                    "rtt_ms": round(r.rtt_ms, 4) if r.rtt_ms is not None else None,
                }
                for r in self.probe_records
            ],
        }


class PacketLossMeasurer:
    """
    Measures packet loss using TCP connect probes.

    Supports continuous probing and burst-mode probing to characterize
    both average loss rate and burst loss behavior.

    Usage:
        measurer = PacketLossMeasurer(host="192.168.1.1", count=200)
        result = measurer.run()
        print(f"Loss: {result.loss_percent}%")
    """

    def __init__(
        self,
        host: str,
        count: int = 200,
        timeout: float = 2.0,
        interval: float = 0.05,
        port: int = 80,
        burst_size: int = 10,
    ):
        self.host = host
        self.resolved_ip = validate_host(host)
        self.count = count
        self.timeout = timeout
        self.interval = interval
        self.port = validate_port(port)
        self.burst_size = burst_size

    def run(self) -> PacketLossResult:
        """Execute continuous packet loss measurement."""
        result = PacketLossResult(
            host=self.host,
            resolved_ip=self.resolved_ip,
            total_sent=self.count,
            total_received=0,
            total_lost=0,
            loss_percent=0.0,
        )

        for seq in range(self.count):
            record = self._probe_tcp(seq)
            result.probe_records.append(record)

            if record.success:
                result.total_received += 1
            else:
                result.total_lost += 1

            if seq < self.count - 1:
                time.sleep(self.interval)

        result.loss_percent = (
            (result.total_lost / result.total_sent) * 100.0
            if result.total_sent > 0
            else 0.0
        )
        result.analyze_bursts()
        return result

    def run_burst_mode(self) -> PacketLossResult:
        """
        Execute burst-mode packet loss measurement.

        Sends packets in bursts of `burst_size` with minimal inter-packet
        delay within each burst, and `interval` delay between bursts.
        This reveals congestion-induced burst loss patterns.
        """
        total_probes = self.count
        result = PacketLossResult(
            host=self.host,
            resolved_ip=self.resolved_ip,
            total_sent=total_probes,
            total_received=0,
            total_lost=0,
            loss_percent=0.0,
        )

        seq = 0
        while seq < total_probes:
            burst_end = min(seq + self.burst_size, total_probes)

            # Send a burst with minimal delay
            for i in range(seq, burst_end):
                record = self._probe_tcp(i)
                result.probe_records.append(record)
                if record.success:
                    result.total_received += 1
                else:
                    result.total_lost += 1

            seq = burst_end

            # Inter-burst delay
            if seq < total_probes:
                time.sleep(self.interval)

        result.loss_percent = (
            (result.total_lost / result.total_sent) * 100.0
            if result.total_sent > 0
            else 0.0
        )
        result.analyze_bursts()
        return result

    def _probe_tcp(self, sequence: int) -> ProbeRecord:
        """Send a single TCP connect probe and record the result."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        timestamp = time.time()
        try:
            start = high_res_timer()
            sock.connect((self.resolved_ip, self.port))
            end = high_res_timer()
            rtt_ms = (end - start) * 1000.0
            return ProbeRecord(
                sequence=sequence,
                timestamp=timestamp,
                success=True,
                rtt_ms=rtt_ms,
            )
        except (socket.timeout, OSError) as exc:
            logger.debug("Loss probe %d failed: %s", sequence, exc)
            return ProbeRecord(
                sequence=sequence,
                timestamp=timestamp,
                success=False,
            )
        finally:
            sock.close()

    def run_udp(self, server_port: int = 5002) -> PacketLossResult:
        """
        Measure packet loss using UDP probes.

        Sends numbered UDP packets and tracks which receive responses.
        Requires a UDP echo server on the target.
        """
        result = PacketLossResult(
            host=self.host,
            resolved_ip=self.resolved_ip,
            total_sent=self.count,
            total_received=0,
            total_lost=0,
            loss_percent=0.0,
        )

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)

        try:
            for seq in range(self.count):
                payload = seq.to_bytes(4, byteorder="big")
                timestamp = time.time()
                try:
                    start = high_res_timer()
                    sock.sendto(payload, (self.resolved_ip, server_port))
                    data, addr = sock.recvfrom(1024)
                    end = high_res_timer()
                    rtt_ms = (end - start) * 1000.0
                    result.probe_records.append(
                        ProbeRecord(sequence=seq, timestamp=timestamp, success=True, rtt_ms=rtt_ms)
                    )
                    result.total_received += 1
                except socket.timeout:
                    result.probe_records.append(
                        ProbeRecord(sequence=seq, timestamp=timestamp, success=False)
                    )
                    result.total_lost += 1
                except OSError as exc:
                    logger.debug("UDP loss probe %d error: %s", seq, exc)
                    result.probe_records.append(
                        ProbeRecord(sequence=seq, timestamp=timestamp, success=False)
                    )
                    result.total_lost += 1

                if seq < self.count - 1:
                    time.sleep(self.interval)
        finally:
            sock.close()

        result.loss_percent = (
            (result.total_lost / result.total_sent) * 100.0
            if result.total_sent > 0
            else 0.0
        )
        result.analyze_bursts()
        return result
