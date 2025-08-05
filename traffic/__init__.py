"""
Traffic generation modules.

Provides TCP and UDP traffic generators with configurable load profiles
for network stress testing and congestion analysis.
"""

from traffic.tcp_generator import TCPTrafficGenerator
from traffic.udp_generator import UDPTrafficGenerator
from traffic.load_profiles import LoadProfile, SteadyProfile, RampProfile, BurstProfile

__all__ = [
    "TCPTrafficGenerator",
    "UDPTrafficGenerator",
    "LoadProfile",
    "SteadyProfile",
    "RampProfile",
    "BurstProfile",
]
