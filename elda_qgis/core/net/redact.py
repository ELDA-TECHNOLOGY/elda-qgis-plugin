from __future__ import annotations

import re

_MASK = "***"
_RULES = (
    (re.compile(r"(?i)(bearer\s+)[^\s\"',;]+"), r"\1" + _MASK),
    # the lookbehind anchors each try at a token start: without it a run of "eyJ" costs quadratic time
    (re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), _MASK),
    (re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=]+"), r"\1" + _MASK),
    (
        re.compile(r"""(?i)(["'](?:password|token|accessToken|refreshToken)["']\s*:\s*)(["'])(?:(?!\2)[^\\]|\\.)*\2"""),
        r"\1\2" + _MASK + r"\2",
    ),
    (re.compile(r"(?i)\b((?:password|token|accessToken|refreshToken|refresh_token|access_token|signature)=)[^&\s\"']+"), r"\1" + _MASK),
    (
        re.compile(r"(?i)(X-Amz-(?:Signature|Credential|Security-Token)(?:=|%3D))[^&\s\"']+"),
        r"\1" + _MASK,
    ),
)


def scrub(text: str) -> str:
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text


_PATHS = (
    re.compile(r"\\\\[^\n:]+"),
    re.compile(r"[A-Za-z]:\\(?:[^\\\n:]+\\)*[^\\\n:]*"),
    re.compile(r"(?<![\w.])/(?:[^\n:/]+/)+[^\n:]*"),
)


def without_paths(text: str) -> str:
    """Third-party error text keeps its reason but loses file paths, which name the user's home."""
    for pattern in _PATHS:
        text = pattern.sub("[…]", text)
    return text
