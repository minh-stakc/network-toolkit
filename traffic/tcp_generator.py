"""
TCP traffic generation module.

Generates TCP traffic with configurable patterns and load profiles.
Supports connection-per-request and persistent-connection modes,
with detailed statistics collection.
"""

import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils import high_res_timer, validate_host, validate_port, format_bytes, logger
from traffic.load_profiles import LoadProfile


@dataclass
class TCPTrafficStats:
    """Statistics collected during TCP traffic generation."""
    total_connections: int = 0
    successful_connections: int = 0
    failed_connections: int = 0
    total_bytes_sent: int = 0
    total_bytes_received: int = 0
    connection_times: List[float] = field(default_factory=list)  # ms
    send_timestamps: List[float] = field(default_factory=list)   # epoch
    send_rates: List[float] = field(default_factory=list)        # connections/sec snapshots
    errors: List[str] = field(default_factory=list)
    duration: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        import numpy as np
        conn_arr = np.array(self.connection_times) if self.connection_times else np.array([0.0])
        return {
            "total_connections": self.total_connections,
            "successful_connections": self.successful_connections,
            "failed_connections": self.failed_connections,
            "total_bytes_sent": self.total_bytes_sent,
            "total_bytes_sent_human": format_bytes(self.total_bytes_sent),
            "duration_sec": round(self.duration, 2),
            "mean_connection_time_ms": round(float(np.mean(conn_arr)), 4),
            "p95_connection_time_ms": round(float(np.percentile(conn_arr, 95)), 4),
            "error_count": len(self.errors),
            "send_rates": [round(r, 2) for r in self.send_rates],
        }


class TCPTrafficGenerator:
    """
    Generates TCP traffic according to a specified load profile.

    Operates in two modes:
    - Connection-per-request: Opens a new TCP connection for each data send.
    - Persistent: Maintains a single connection and sends data repeatedly.

    Usage:
        profile = LoadProfile.from_name("ramp", start_rate=1.0, end_rate=50.0)
        gen = TCPTrafficGenerator(
            host="192.168.1.1", port=5001,
            duration=30.0, profile=profile,
        )
        stats = gen.run()
    """

    def __init__(
        self,
        host: str,
        port: int = 5001,
        duration: float = 30.0,
        payload_size: int = 1024,
        profile: Optional[LoadProfile] = None,
        persistent: bool = False,
    ):
        self.host = host
        self.resolved_ip = validate_host(host)
        self.port = validate_port(port)
        self.duration = duration
        self.payload_size = payload_size
        self.profile = profile
        self.persistent = persistent
        self._stop_event = threading.Event()

    def run(self) -> TCPTrafficStats:
        """Execute TCP traffic generation and return statistics."""
        if self.persistent:
            return self._run_persistent()
        return self._run_connection_per_request()

    def stop(self):
        """Signal the generator to stop."""
        self._stop_event.set()

    def _run_connection_per_request(self) -> TCPTrafficStats:
        """Generate traffic by opening a new connection for each send."""
        stats = TCPTrafficStats()
        payload = bytes(range(256)) * (self.payload_size // 256 + 1)
        payload = payload[:self.payload_size]

        start_time = high_res_timer()
        last_rate_sample = start_time
        interval_connections = 0

        logger.info(
            "Starting TCP traffic generation (connection-per-request) to %s:%d for %.1fs",
            self.resolved_ip, self.port, self.duration,
        )

        while not self._stop_event.is_set():
            elapsed = high_res_timer() - start_time
            if elapsed >= self.duration:
                break

            # Determine current sending rate from profile
            if self.profile:
                delay = self.profile.get_inter_packet_delay(elapsed, self.duration)
            else:
                delay = 0.1  # default 10 connections/sec

            # Attempt a connection and data send
            stats.total_connections += 1
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            try:
                conn_start = high_res_timer()
                sock.connect((self.resolved_ip, self.port))
                conn_time = (high_res_timer() - conn_start) * 1000.0
                stats.connection_times.append(conn_time)

                sent = sock.send(payload)
                stats.total_bytes_sent += sent
                stats.successful_connections += 1
                stats.send_timestamps.append(time.time())
                interval_connections += 1
            except (socket.timeout, OSError) as exc:
                stats.failed_connections += 1
                stats.errors.append(str(exc))
                logger.debug("TCP send failed: %s", exc)
            finally:
                sock.close()

            # Record rate samples every second
            now = high_res_timer()
            if now - last_rate_sample >= 1.0:
                rate = interval_connections / (now - last_rate_sample)
                stats.send_rates.append(rate)
                interval_connections = 0
                last_rate_sample = now

            if delay > 0:
                time.sleep(delay)

        stats.duration = high_res_timer() - start_time
        logger.info(
            "TCP traffic generation complete: %d connections, %s sent in %.1fs",
            stats.successful_connections,
            format_bytes(stats.total_bytes_sent),
            stats.duration,
        )
        return stats

    def _run_persistent(self) -> TCPTrafficStats:
        """Generate traffic over a single persistent TCP connection."""
        stats = TCPTrafficStats()
        payload = bytes(range(256)) * (self.payload_size // 256 + 1)
        payload = payload[:self.payload_size]

        logger.info(
            "Starting TCP traffic generation (persistent) to %s:%d for %.1fs",
            self.resolved_ip, self.port, self.duration,
        )

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(self.duration + 5.0)

        try:
            conn_start = high_res_timer()
            sock.connect((self.resolved_ip, self.port))
            stats.connection_times.append((high_res_timer() - conn_start) * 1000.0)
            stats.total_connections = 1
            stats.successful_connections = 1
        except (socket.timeout, OSError) as exc:
            stats.failed_connections = 1
            stats.errors.append(str(exc))
            logger.error("Persistent connection failed: %s", exc)
            sock.close()
            return stats

        start_time = high_res_timer()
        last_rate_sample = start_time
        interval_bytes = 0
        packets_sent = 0

        try:
            while not self._stop_event.is_set():
                elapsed = high_res_timer() - start_time
                if elapsed >= self.duration:
                    break

                if self.profile:
                    delay = self.profile.get_inter_packet_delay(elapsed, self.duration)
                else:
                    delay = 0.01

                try:
                    sent = sock.send(payload)
                    stats.total_bytes_sent += sent
                    interval_bytes += sent
                    packets_sent += 1
                    stats.send_timestamps.append(time.time())
                except OSError as exc:
                    stats.errors.append(str(exc))
                    logger.debug("Persistent send error: %s", exc)
                    break

                now = high_res_timer()
                if now - last_rate_sample >= 1.0:
                    rate = interval_bytes / (now - last_rate_sample)
                    stats.send_rates.append(rate * 8)  # bits/sec
                    interval_bytes = 0
                    last_rate_sample = now

                if delay > 0:
                    time.sleep(delay)
        finally:
            sock.close()

        stats.duration = high_res_timer() - start_time
        logger.info(
            "Persistent TCP generation complete: %d packets, %s sent in %.1fs",
            packets_sent,
            format_bytes(stats.total_bytes_sent),
            stats.duration,
        )
        return stats
