"""Join the parent's owned Windows job before starting a native tool."""
import ctypes as C
from ctypes import wintypes as W
import subprocess
import sys


def main():
    api=C.WinDLL('kernel32', use_last_error=True)
    api.GetCurrentProcess.restype=W.HANDLE
    api.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE]
    api.AssignProcessToJobObject.restype=W.BOOL
    api.CloseHandle.argtypes=[W.HANDLE]
    api.CloseHandle.restype=W.BOOL
    handle=int(sys.argv[1])
    try:
        if not api.AssignProcessToJobObject(handle,api.GetCurrentProcess()):
            raise C.WinError(C.get_last_error())
    finally:
        api.CloseHandle(handle)  # Only the application retains the owning handle.
    return subprocess.call(sys.argv[2:],stdin=subprocess.DEVNULL,
                           stdout=sys.stdout,stderr=subprocess.STDOUT,
                           creationflags=subprocess.CREATE_NO_WINDOW)


if __name__=='__main__':sys.exit(main())
