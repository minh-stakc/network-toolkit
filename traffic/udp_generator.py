"""
UDP traffic generation module.

Generates UDP datagrams at configurable rates with support for
load profiles, payload sizing, and detailed packet-level statistics.
"""

import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils import high_res_timer, validate_host, validate_port, format_bytes, logger
from traffic.load_profiles import LoadProfile


@dataclass
class UDPTrafficStats:
    """Statistics collected during UDP traffic generation."""
    total_packets_sent: int = 0
    total_bytes_sent: int = 0
    send_timestamps: List[float] = field(default_factory=list)
    send_rates: List[float] = field(default_factory=list)  # packets/sec snapshots
    throughput_samples: List[float] = field(default_factory=list)  # bits/sec
    errors: List[str] = field(default_factory=list)
    duration: float = 0.0
    target_rate_profile: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        import numpy as np
        rate_arr = np.array(self.send_rates) if self.send_rates else np.array([0.0])
        tp_arr = np.array(self.throughput_samples) if self.throughput_samples else np.array([0.0])
        return {
            "total_packets_sent": self.total_packets_sent,
            "total_bytes_sent": self.total_bytes_sent,
            "total_bytes_sent_human": format_bytes(self.total_bytes_sent),
            "duration_sec": round(self.duration, 2),
            "mean_send_rate_pps": round(float(np.mean(rate_arr)), 2),
            "max_send_rate_pps": round(float(np.max(rate_arr)), 2),
            "mean_throughput_bps": round(float(np.mean(tp_arr)), 2),
            "max_throughput_bps": round(float(np.max(tp_arr)), 2),
            "error_count": len(self.errors),
            "target_rate_profile": self.target_rate_profile,
            "send_rates_pps": [round(r, 2) for r in self.send_rates],
            "throughput_bps": [round(t, 2) for t in self.throughput_samples],
        }


class UDPTrafficGenerator:
    """
    Generates UDP traffic according to a specified load profile.

    Each packet includes a sequence number and timestamp header for
    receiver-side analysis (loss detection, reordering, jitter).

    Packet format:
        [4 bytes: sequence number][8 bytes: send timestamp ns][payload]

    Usage:
        profile = LoadProfile.from_name("burst", burst_rate=100.0)
        gen = UDPTrafficGenerator(
            host="192.168.1.1", port=5002,
            duration=20.0, profile=profile,
        )
        stats = gen.run()
    """

    HEADER_SIZE = 12  # 4 bytes seq + 8 bytes timestamp

    def __init__(
        self,
        host: str,
        port: int = 5002,
        duration: float = 30.0,
        payload_size: int = 1024,
        profile: Optional[LoadProfile] = None,
        rate: float = 10.0,
    ):
        self.host = host
        self.resolved_ip = validate_host(host)
        self.port = validate_port(port)
        self.duration = duration
        self.payload_size = max(payload_size, self.HEADER_SIZE)
        self.profile = profile
        self.default_rate = rate
        self._stop_event = threading.Event()

    def run(self) -> UDPTrafficStats:
        """Execute UDP traffic generation and return statistics."""
        stats = UDPTrafficStats()
        if self.profile:
            stats.target_rate_profile = self.profile.describe().get("type", "custom")
        else:
            stats.target_rate_profile = f"steady@{self.default_rate}pps"

        # Build payload template (fill beyond header with pattern data)
        payload_body_size = self.payload_size - self.HEADER_SIZE
        payload_body = bytes(range(256)) * (payload_body_size // 256 + 1)
        payload_body = payload_body[:payload_body_size]

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Set send buffer size for high-rate sending
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
        except OSError:
            pass

        logger.info(
            "Starting UDP traffic generation to %s:%d for %.1fs (payload=%d bytes)",
            self.resolved_ip, self.port, self.duration, self.payload_size,
        )

        start_time = high_res_timer()
        last_rate_sample = start_time
        interval_packets = 0
        interval_bytes = 0
        seq = 0

        try:
            while not self._stop_event.is_set():
                elapsed = high_res_timer() - start_time
                if elapsed >= self.duration:
                    break

                # Determine inter-packet delay
                if self.profile:
                    delay = self.profile.get_inter_packet_delay(elapsed, self.duration)
                    current_rate = self.profile.get_rate(elapsed, self.duration)
                else:
                    delay = 1.0 / self.default_rate if self.default_rate > 0 else 0.0
                    current_rate = self.default_rate

                # Skip sending during idle periods (rate == 0)
                if current_rate <= 0:
                    time.sleep(min(delay, 0.1))
                    continue

                # Build packet with header
                header = struct.pack("!IQ", seq, time.time_ns())
                packet = header + payload_body

                try:
                    sent = sock.sendto(packet, (self.resolved_ip, self.port))
                    stats.total_packets_sent += 1
                    stats.total_bytes_sent += sent
                    stats.send_timestamps.append(time.time())
                    interval_packets += 1
                    interval_bytes += sent
                    seq += 1
                except OSError as exc:
                    stats.errors.append(str(exc))
                    logger.debug("UDP send error (seq=%d): %s", seq, exc)

                # Record rate samples every second
                now = high_res_timer()
                sample_elapsed = now - last_rate_sample
                if sample_elapsed >= 1.0:
                    pps = interval_packets / sample_elapsed
                    bps = (interval_bytes * 8) / sample_elapsed
                    stats.send_rates.append(pps)
                    stats.throughput_samples.append(bps)
                    interval_packets = 0
                    interval_bytes = 0
                    last_rate_sample = now

                if delay > 0:
                    time.sleep(delay)
        finally:
            sock.close()

        stats.duration = high_res_timer() - start_time
        logger.info(
            "UDP traffic generation complete: %d packets, %s sent in %.1fs",
            stats.total_packets_sent,
            format_bytes(stats.total_bytes_sent),
            stats.duration,
        )
        return stats

    def stop(self):
        """Signal the generator to stop."""
        self._stop_event.set()

    def run_background(self) -> threading.Thread:
        """Run the generator in a background thread."""
        t = threading.Thread(target=self.run, daemon=True)
        t.start()
        return t


class UDPEchoServer:
    """
    Simple UDP echo server for testing.

    Echoes received packets back to the sender, enabling RTT-based
    jitter and loss measurements.
    """

    def __init__(self, port: int = 5002):
        self.port = validate_port(port)
        self._stop_event = threading.Event()

    def start(self):
        """Run the echo server."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        sock.bind(("0.0.0.0", self.port))
        logger.info("UDP echo server listening on port %d", self.port)

        packets_echoed = 0
        while not self._stop_event.is_set():
            try:
                data, addr = sock.recvfrom(65536)
                sock.sendto(data, addr)
                packets_echoed += 1
            except socket.timeout:
                continue
            except OSError as exc:
                logger.debug("UDP echo error: %s", exc)

        logger.info("UDP echo server stopped. Echoed %d packets.", packets_echoed)
        sock.close()

    def start_background(self) -> threading.Thread:
        """Start the echo server in a background thread."""
        t = threading.Thread(target=self.start, daemon=True)
        t.start()
        return t

    def stop(self):
        """Signal the server to stop."""
        self._stop_event.set()
