# Eve Store Concurrency Contract

Status: active
Last reviewed: 2026-08-23
Current authority: `eve_store.py`
Supersedes: none
Superseded by: none

Eve's JSON and JSONL helpers serialize same-path writers with a reentrant
in-process lock and a process-level lock: `flock` on Unix-like systems and a
one-byte `msvcrt.locking` region on Windows. Lock files and state files are
owner-only.

The process lock lifecycle is fail-safe:

- nested same-thread acquisition does not reacquire the kernel lock;
- failure to create, secure, or acquire the kernel lock always releases the
  in-process lock and thread-depth record;
- closing the lock descriptor releases the kernel lock;
- cleanup failure does not replace an exception from the protected operation;
- platforms with `O_NOFOLLOW` refuse a symlink lock path rather than following
  and truncating another file.

This contract protects writer serialization. It does not turn JSON files into a
transactional database, repair malformed records, or provide a distributed
lock across machines.
