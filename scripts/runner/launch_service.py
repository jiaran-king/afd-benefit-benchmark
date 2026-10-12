"""Shared credential redaction for pre-pressure records, never for public export."""
import re

def redact(values):
    secret=re.compile(r"(?:password|passwd|secret|credential|authorization|access.?key|api.?key|(?:^|_)token(?:_|$)|cookie)",re.I)
    return {k:"<redacted>" if secret.search(k) else re.sub(
        r"(?<=://)[^/@\s]+:[^/@\s]+@","<redacted>@",str(v)) for k,v in sorted(values.items())}
