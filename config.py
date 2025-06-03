"""
Configuration for the Network Performance Measurement Toolkit.

Central configuration for target hosts, ports, test parameters, and defaults.
All values can be overridden via CLI flags or environment variables.
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class HostConfig:
    """Configuration for a single target host."""
    address: str
    label: str = ""
    tcp_port: int = 5001
    udp_port: int = 5002

    def __post_init__(self):
        if not self.label:
            self.label = self.address


@dataclass
class LatencyConfig:
    """Parameters for latency measurements."""
    count: int = 100
    timeout: float = 2.0          # seconds per probe
    interval: float = 0.1         # seconds between probes
    payload_size: int = 64        # bytes
    use_tcp: bool = False         # use TCP SYN instead of ICMP
    tcp_port: int = 80


@dataclass
class JitterConfig:
    """Parameters for jitter measurements."""
    count: int = 100
    interval: float = 0.05        # seconds between probes
    payload_size: int = 64
    timeout: float = 2.0


@dataclass
class PacketLossConfig:
    """Parameters for packet loss measurements."""
    count: int = 200
    timeout: float = 2.0
    interval: float = 0.05
    payload_size: int = 64
    burst_size: int = 10          # packets per burst for burst-mode testing


@dataclass
class ThroughputConfig:
    """Parameters for throughput benchmarking."""
    duration: float = 10.0        # seconds
    tcp_port: int = 5001
    udp_port: int = 5002
    buffer_size: int = 131072     # 128 KB send buffer
    window_size: int = 65536      # TCP window size
    parallel_streams: int = 1
    protocol: str = "tcp"         # "tcp" or "udp"
    target_bandwidth: float = 0.0 # 0 = unlimited (TCP), Mbps (UDP)


@dataclass
class TrafficConfig:
    """Parameters for traffic generation."""
    duration: float = 30.0
    tcp_port: int = 5001
    udp_port: int = 5002
    payload_size: int = 1024
    rate: float = 10.0            # packets per second (UDP) or connections/sec (TCP)
    profile: str = "steady"       # "steady", "ramp", "burst"
    ramp_start_rate: float = 1.0
    ramp_end_rate: float = 100.0
    burst_packets: int = 50
    burst_interval: float = 5.0


@dataclass
class ToolkitConfig:
    """Top-level configuration aggregating all sub-configs."""
    targets: List[HostConfig] = field(default_factory=lambda: [
        HostConfig(address="127.0.0.1", label="localhost"),
    ])
    latency: LatencyConfig = field(default_factory=LatencyConfig)
    jitter: JitterConfig = field(default_factory=JitterConfig)
    packet_loss: PacketLossConfig = field(default_factory=PacketLossConfig)
    throughput: ThroughputConfig = field(default_factory=ThroughputConfig)
    traffic: TrafficConfig = field(default_factory=TrafficConfig)
    output_dir: str = "results"
    log_level: str = "INFO"

    def __post_init__(self):
        # Allow environment variable overrides
        self.output_dir = os.environ.get("NETTOOL_OUTPUT_DIR", self.output_dir)
        self.log_level = os.environ.get("NETTOOL_LOG_LEVEL", self.log_level)


# Global default configuration instance
DEFAULT_CONFIG = ToolkitConfig()
