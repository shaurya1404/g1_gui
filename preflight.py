"""
Preflight checks: network routing, robot ping, CycloneDDS topics.
Each check returns (passed: bool, message: str).
"""

import subprocess
import shlex


def check_usb_adapter(adapter_name: str) -> tuple[bool, str]:
    """Detect whether the problematic USB adapter is present."""
    try:
        result = subprocess.run(
            ["ip", "addr"],
            capture_output=True, text=True, timeout=5,
        )
        if adapter_name in result.stdout:
            return False, f"USB adapter '{adapter_name}' detected — routing fix required."
        return True, f"USB adapter '{adapter_name}' not present — no fix needed."
    except Exception as e:
        return False, f"Error running 'ip addr': {e}"


def fix_routing(adapter_name: str, subnet: str) -> tuple[bool, str]:
    """Remove the incorrect route through the USB adapter."""
    try:
        result = subprocess.run(
            ["sudo", "ip", "route", "del", subnet, "dev", adapter_name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True, f"Route via '{adapter_name}' removed successfully."
        return False, f"Failed to remove route: {result.stderr.strip()}"
    except Exception as e:
        return False, f"Error fixing route: {e}"


def verify_routing(robot_ip: str, interface: str) -> tuple[bool, str]:
    """Verify traffic to the robot goes through the correct interface."""
    try:
        result = subprocess.run(
            ["ip", "route", "get", robot_ip],
            capture_output=True, text=True, timeout=5,
        )
        output = result.stdout.strip()
        if interface in output:
            return True, f"Routing OK: {output}"
        return False, f"Routing NOT via {interface}: {output}"
    except Exception as e:
        return False, f"Error checking route: {e}"


def ping_robot(robot_ip: str, interface: str) -> tuple[bool, str]:
    """Ping the robot over the specified interface."""
    try:
        result = subprocess.run(
            ["ping", "-I", interface, "-c", "3", "-W", "2", robot_ip],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip()
        if "0% packet loss" in output:
            return True, f"Robot reachable at {robot_ip} via {interface}."
        return False, f"Ping failed:\n{output}"
    except Exception as e:
        return False, f"Ping error: {e}"


def check_cyclonedds(setup_cmd: str) -> tuple[bool, str]:
    """Source the CycloneDDS workspace and run 'cyclonedds ps'."""
    try:
        full_cmd = f"bash -c '{setup_cmd} && cyclonedds ps 2>&1'"
        result = subprocess.run(
            full_cmd, shell=True,
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout.strip()
        if not output or "no participants" in output.lower():
            return False, f"No CycloneDDS topics found.\n{output}"
        return True, f"CycloneDDS topics detected:\n{output}"
    except Exception as e:
        return False, f"CycloneDDS check error: {e}"
