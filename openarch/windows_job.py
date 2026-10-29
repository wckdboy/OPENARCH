"""Windows 8+ nested job containment for this application's worker processes.

https://learn.microsoft.com/windows/win32/procthread/job-objects
The inheriting supervisor attaches itself before launching CAD or PDF tools.
"""
import ctypes as C
from ctypes import wintypes as W
import os


class BasicLimits(C.Structure):
    _fields_ = [('PerProcessUserTimeLimit', C.c_longlong), ('PerJobUserTimeLimit', C.c_longlong),
                ('LimitFlags', W.DWORD), ('MinimumWorkingSetSize', C.c_size_t),
                ('MaximumWorkingSetSize', C.c_size_t), ('ActiveProcessLimit', W.DWORD),
                ('Affinity', C.c_size_t), ('PriorityClass', W.DWORD), ('SchedulingClass', W.DWORD)]


class IoCounters(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in ['ReadOperationCount', 'WriteOperationCount',
                'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount']]


class ExtendedLimits(C.Structure):
    _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters),
                ('ProcessMemoryLimit', C.c_size_t), ('JobMemoryLimit', C.c_size_t),
                ('PeakProcessMemoryUsed', C.c_size_t), ('PeakJobMemoryUsed', C.c_size_t)]


class Job:
    def __init__(self):
        self.api = C.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [C.c_void_p, W.LPCWSTR]
        self.api.CreateJobObjectW.restype = W.HANDLE
        self.api.SetInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
        self.api.SetInformationJobObject.restype = W.BOOL
        self.api.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
        self.api.TerminateJobObject.restype = W.BOOL
        self.api.CloseHandle.argtypes = [W.HANDLE]
        self.api.CloseHandle.restype = W.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:raise C.WinError(C.get_last_error())
        try:
            limits = ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            if not self.api.SetInformationJobObject(self.handle, 9, C.byref(limits), C.sizeof(limits)):
                raise C.WinError(C.get_last_error())
            os.set_handle_inheritable(self.handle, True)
        except BaseException:
            self.close()
            raise

    def terminate(self):
        if not self.api.TerminateJobObject(self.handle, 1):raise C.WinError(C.get_last_error())

    def close(self):
        if self.handle:
            if not self.api.CloseHandle(self.handle):raise C.WinError(C.get_last_error())
            self.handle = None
