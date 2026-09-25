"""Resource limits for the disposable parser, not a security sandbox."""
import os
import sys

_job = None


def apply_limits(memory, seconds, output):
    global _job
    if sys.platform == 'win32':
        import ctypes as c
        from ctypes import wintypes as w

        class Basic(c.Structure):
            _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64),
                        ('flags', w.DWORD), ('min_ws', c.c_size_t), ('max_ws', c.c_size_t),
                        ('active', w.DWORD), ('affinity', c.c_size_t),
                        ('priority', w.DWORD), ('scheduling', w.DWORD)]

        class Extended(c.Structure):
            _fields_ = [('basic', Basic), ('io', c.c_uint64 * 6),
                        ('process_memory', c.c_size_t), ('job_memory', c.c_size_t),
                        ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]

        kernel = c.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        kernel.SetInformationJobObject.restype = w.BOOL
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.AssignProcessToJobObject.restype = w.BOOL
        kernel.GetCurrentProcess.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise c.WinError(c.get_last_error())
        limits = Extended()
        # Job-wide committed memory, job CPU time, and descendant cleanup on exit.
        limits.basic.flags = 0x200 | 0x4 | 0x2000
        limits.basic.job_time = int(seconds + 5) * 10_000_000
        limits.job_memory = memory
        if not kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)):
            error = c.get_last_error()
            kernel.CloseHandle(job)
            raise c.WinError(error)
        if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
            error = c.get_last_error()
            kernel.CloseHandle(job)
            raise c.WinError(error)
        _job = job
    else:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (int(seconds + 5), int(seconds + 5)))
        resource.setrlimit(resource.RLIMIT_FSIZE, (output, output))
        if sys.platform.startswith('linux'):
            # Virtual address space includes mappings; RSS is also monitored by the parent.
            resource.setrlimit(resource.RLIMIT_AS, (memory * 2, memory * 2))


def input_stream():
    if sys.stdin is not None:
        return sys.stdin.buffer
    # Windowed PyInstaller apps discard Python's stdin wrapper, not the inherited pipe.
    if os.name == 'nt':
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
        kernel.GetStdHandle.restype = ctypes.c_void_p
        handle = kernel.GetStdHandle(ctypes.c_ulong(-10))
        return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), 'rb')
    return os.fdopen(0, 'rb')
