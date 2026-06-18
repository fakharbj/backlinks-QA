"""robots.txt parsing & evaluation (RBT-* checks, PRD §8.6 J).

Google's matching rules, implemented faithfully:
  * group selection by most-specific User-agent token (``Googlebot`` beats ``*``);
  * ``Allow``/``Disallow`` with ``*`` wildcards and ``$`` end-anchors;
  * the **longest** matching rule wins; on equal length ``Allow`` wins;
  * ``Crawl-delay`` and ``Sitemap`` captured.

Pure stdlib — the engine injects fetching + caching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(slots=True)
class _Rule:
    allow: bool
    pattern: str
    regex: re.Pattern
    length: int


@dataclass(slots=True)
class _Group:
    agents: list[str]
    rules: list[_Rule] = field(default_factory=list)
    crawl_delay: float | None = None


def _compile(pattern: str) -> re.Pattern:
    """Translate a robots path pattern (``*``/``$``) into a regex."""
    anchored_end = pattern.endswith("$")
    if anchored_end:
        pattern = pattern[:-1]
    out = ["^"]
    for ch in pattern:
        if ch == "*":
            out.append(".*")
        else:
            out.append(re.escape(ch))
    if anchored_end:
        out.append("$")
    return re.compile("".join(out))


class RobotsTxt:
    """Parsed robots.txt with a Googlebot-aware ``allowed`` evaluation."""

    def __init__(self) -> None:
        self.groups: list[_Group] = []
        self.sitemaps: list[str] = []
        self.parse_error = False
        self.empty = True

    # Parsing
    @classmethod
    def parse(cls, content: str) -> "RobotsTxt":
        self = cls()
        try:
            return self._parse(content)
        except Exception:
            self.parse_error = True
            return self

    def _parse(self, content: str) -> "RobotsTxt":
        current: _Group | None = None
        expecting_agents = False
        for raw_line in content.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field_name, _, value = line.partition(":")
            field_name = field_name.strip().lower()
            value = value.strip()

            if field_name == "user-agent":
                self.empty = False
                if current is None or not expecting_agents:
                    current = _Group(agents=[])
                    self.groups.append(current)
                    expecting_agents = True
                current.agents.append(value.lower())
                continue

            expecting_agents = False
            if field_name in ("allow", "disallow"):
                if current is None:
                    current = _Group(agents=["*"])
                    self.groups.append(current)
                if value == "" and field_name == "disallow":
                    continue  # "Disallow:" == allow all → no rule
                current.rules.append(
                    _Rule(
                        allow=(field_name == "allow"),
                        pattern=value,
                        regex=_compile(value),
                        length=len(value.replace("*", "").replace("$", "")),
                    )
                )
            elif field_name == "crawl-delay" and current is not None:
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    pass
            elif field_name == "sitemap":
                self.sitemaps.append(value)
        return self

    # Evaluation
    def _select_group(self, user_agent: str) -> _Group | None:
        ua = user_agent.lower()
        best: _Group | None = None
        best_len = -1
        for group in self.groups:
            for token in group.agents:
                if token == "*":
                    if best is None:
                        best, best_len = group, 0
                elif token in ua and len(token) > best_len:
                    best, best_len = group, len(token)
        return best

    def allowed(self, url: str, user_agent: str = "Googlebot") -> bool:
        """Is ``url`` crawlable by ``user_agent``? Unknown/empty → allow (RBT-02)."""
        group = self._select_group(user_agent)
        if group is None or not group.rules:
            return True
        path = urlsplit(url).path or "/"
        if urlsplit(url).query:
            path += "?" + urlsplit(url).query

        winner: _Rule | None = None
        for rule in group.rules:
            if rule.regex.match(path):
                if winner is None or rule.length > winner.length or (
                    rule.length == winner.length and rule.allow and not winner.allow
                ):
                    winner = rule
        return winner.allow if winner is not None else True

    def crawl_delay(self, user_agent: str = "Googlebot") -> float | None:
        group = self._select_group(user_agent)
        return group.crawl_delay if group else None
