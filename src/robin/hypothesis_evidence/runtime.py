"""Portable runtime measurements for the evidence factory CLI."""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes


def process_peak_memory_bytes() -> tuple[int | None, str]:
    """Return the OS-maintained process peak, never a sampled approximation."""

    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("page_fault_count", wintypes.DWORD),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        handle = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        ):
            return (
                int(counters.peak_working_set_size),
                "WINDOWS_PEAK_WORKING_SET",
            )
        return None, "WINDOWS_PEAK_WORKING_SET_UNAVAILABLE"

    try:
        import resource
    except ImportError:
        return None, "OS_PROCESS_PEAK_UNAVAILABLE"
    maximum = int(
        resource.getrusage(  # type: ignore[attr-defined]
            resource.RUSAGE_SELF,  # type: ignore[attr-defined]
        ).ru_maxrss
    )
    multiplier = 1 if sys.platform == "darwin" else 1024
    return maximum * multiplier, "RU_MAXRSS"
