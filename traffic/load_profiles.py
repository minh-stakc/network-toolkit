"""
Predefined load profiles for traffic generation.

Each profile controls the packet sending rate over time, enabling
simulation of different traffic patterns: steady state, ramp-up,
and burst scenarios.
"""

import math
from abc import ABC, abstractmethod
from typing import Dict, Any


class LoadProfile(ABC):
    """Base class for traffic load profiles."""

    @abstractmethod
    def get_rate(self, elapsed: float, duration: float) -> float:
        """
        Return the target sending rate (packets/sec) at the given elapsed time.

        Args:
            elapsed: Seconds since the start of the test.
            duration: Total planned duration of the test.

        Returns:
            Target rate in packets per second.
        """

    @abstractmethod
    def get_inter_packet_delay(self, elapsed: float, duration: float) -> float:
        """
        Return the delay in seconds between consecutive packets.

        Args:
            elapsed: Seconds since the start of the test.
            duration: Total planned duration of the test.

        Returns:
            Delay in seconds. Returns 0.0 for unlimited rate.
        """

    @abstractmethod
    def describe(self) -> Dict[str, Any]:
        """Return a dictionary describing this profile's parameters."""

    @staticmethod
    def from_name(name: str, **kwargs) -> "LoadProfile":
        """Factory method to create a profile by name."""
        profiles = {
            "steady": SteadyProfile,
            "ramp": RampProfile,
            "burst": BurstProfile,
            "sine": SineProfile,
            "step": StepProfile,
        }
        name_lower = name.lower()
        if name_lower not in profiles:
            raise ValueError(f"Unknown profile '{name}'. Available: {list(profiles.keys())}")
        return profiles[name_lower](**kwargs)


class SteadyProfile(LoadProfile):
    """
    Constant-rate traffic profile.

    Sends packets at a fixed rate throughout the entire test duration.
    """

    def __init__(self, rate: float = 10.0, **kwargs):
        self.rate = rate

    def get_rate(self, elapsed: float, duration: float) -> float:
        return self.rate

    def get_inter_packet_delay(self, elapsed: float, duration: float) -> float:
        return 1.0 / self.rate if self.rate > 0 else 0.0

    def describe(self) -> Dict[str, Any]:
        return {"type": "steady", "rate_pps": self.rate}


class RampProfile(LoadProfile):
    """
    Linear ramp traffic profile.

    Linearly increases the sending rate from start_rate to end_rate
    over the test duration.
    """

    def __init__(self, start_rate: float = 1.0, end_rate: float = 100.0, **kwargs):
        self.start_rate = start_rate
        self.end_rate = end_rate

    def get_rate(self, elapsed: float, duration: float) -> float:
        if duration <= 0:
            return self.start_rate
        progress = min(elapsed / duration, 1.0)
        return self.start_rate + (self.end_rate - self.start_rate) * progress

    def get_inter_packet_delay(self, elapsed: float, duration: float) -> float:
        rate = self.get_rate(elapsed, duration)
        return 1.0 / rate if rate > 0 else 0.0

    def describe(self) -> Dict[str, Any]:
        return {
            "type": "ramp",
            "start_rate_pps": self.start_rate,
            "end_rate_pps": self.end_rate,
        }


class BurstProfile(LoadProfile):
    """
    Burst traffic profile.

    Alternates between high-rate bursts and idle periods.
    """

    def __init__(
        self,
        burst_rate: float = 100.0,
        burst_duration: float = 1.0,
        idle_duration: float = 4.0,
        **kwargs,
    ):
        self.burst_rate = burst_rate
        self.burst_duration = burst_duration
        self.idle_duration = idle_duration
        self.cycle_duration = burst_duration + idle_duration

    def get_rate(self, elapsed: float, duration: float) -> float:
        phase = elapsed % self.cycle_duration
        if phase < self.burst_duration:
            return self.burst_rate
        return 0.0

    def get_inter_packet_delay(self, elapsed: float, duration: float) -> float:
        rate = self.get_rate(elapsed, duration)
        if rate <= 0:
            return self.idle_duration  # sleep through idle period
        return 1.0 / rate

    def describe(self) -> Dict[str, Any]:
        return {
            "type": "burst",
            "burst_rate_pps": self.burst_rate,
            "burst_duration_sec": self.burst_duration,
            "idle_duration_sec": self.idle_duration,
        }


class SineProfile(LoadProfile):
    """
    Sinusoidal traffic profile.

    Varies the sending rate following a sine wave between min and max rates.
    """

    def __init__(
        self,
        min_rate: float = 5.0,
        max_rate: float = 50.0,
        period: float = 10.0,
        **kwargs,
    ):
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.period = period

    def get_rate(self, elapsed: float, duration: float) -> float:
        amplitude = (self.max_rate - self.min_rate) / 2.0
        midpoint = (self.max_rate + self.min_rate) / 2.0
        return midpoint + amplitude * math.sin(2 * math.pi * elapsed / self.period)

    def get_inter_packet_delay(self, elapsed: float, duration: float) -> float:
        rate = self.get_rate(elapsed, duration)
        return 1.0 / rate if rate > 0 else 0.1

    def describe(self) -> Dict[str, Any]:
        return {
            "type": "sine",
            "min_rate_pps": self.min_rate,
            "max_rate_pps": self.max_rate,
            "period_sec": self.period,
        }


class StepProfile(LoadProfile):
    """
    Step-function traffic profile.

    Increases the rate in discrete steps at equal time intervals.
    """

    def __init__(
        self,
        start_rate: float = 10.0,
        step_size: float = 10.0,
        step_interval: float = 5.0,
        max_rate: float = 100.0,
        **kwargs,
    ):
        self.start_rate = start_rate
        self.step_size = step_size
        self.step_interval = step_interval
        self.max_rate = max_rate

    def get_rate(self, elapsed: float, duration: float) -> float:
        steps = int(elapsed / self.step_interval)
        rate = self.start_rate + steps * self.step_size
        return min(rate, self.max_rate)

    def get_inter_packet_delay(self, elapsed: float, duration: float) -> float:
        rate = self.get_rate(elapsed, duration)
        return 1.0 / rate if rate > 0 else 0.0

    def describe(self) -> Dict[str, Any]:
        return {
            "type": "step",
            "start_rate_pps": self.start_rate,
            "step_size_pps": self.step_size,
            "step_interval_sec": self.step_interval,
            "max_rate_pps": self.max_rate,
        }
