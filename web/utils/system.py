"""
System and hardware utility functions.
"""
import os
import platform

def check_lse_support() -> bool:
    """
    Check if the current ARM system supports Large System Extensions (LSE).
    Required for MongoDB 5.0+.
    """
    if platform.machine() != "aarch64":
        return True  # Not ARM64, assume compatible or handled by other checks
        
    try:
        # Check /proc/cpuinfo for lse flag
        with open("/proc/cpuinfo", "r") as f:
            content = f.read()
            if "lse" in content.lower():
                return True
    except Exception:
        pass
        
    return False

def check_mongodb_compatibility() -> tuple:
    """
    Check if the current system is compatible with the bundled MongoDB (5.0+).
    Returns (is_compatible, error_message)
    """
    if platform.machine() == "aarch64":
        if not check_lse_support():
            return False, "ARM hardware lacks LSE support (required for MongoDB 5.0+). Use Flatfile storage or MongoDB 4.4."
            
    return True, ""

def get_system_warnings() -> list:
    """Collect system-level warnings (hardware, config, etc.)"""
    warnings = []
    
    # Check MongoDB compatibility if enabled or potentially usable
    is_compat, msg = check_mongodb_compatibility()
    if not is_compat:
        warnings.append({
            "id": "mongodb_compat",
            "severity": "danger",
            "message": msg,
            "affected_component": "Database"
        })
        
    return warnings
