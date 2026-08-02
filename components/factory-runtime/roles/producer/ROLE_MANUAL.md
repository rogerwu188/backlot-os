# producer minimal worker manual

Run exactly one bounded tick: `python3 worker.py --root <runtime> --once`. The worker communicates only through shared files, ignores stdout, atomically claims at most one task, resumes `running` before considering a new claim, writes checkpoint/artifact before terminal state, and emits heartbeat when idle. Public cron registration is outside this package and requires explicit operator action.
