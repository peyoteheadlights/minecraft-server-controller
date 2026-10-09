"""Rule-based crash analysis.

The analyzer matches patterns against console output and crash reports and
returns a category plus the exact lines that produced the match.

Four confidence levels, and the difference between them matters:

  confirmed  the log contains the error itself, so the category is a fact
             (an OutOfMemoryError line *is* an out-of-memory error)
  likely     strong evidence, but the printed error may be a symptom of
             something else - a mixin failure usually means a version
             mismatch, but not always
  possible   the pattern matched, but it is commonly incidental
  unknown    nothing matched; no cause is claimed at all

The analyzer never names a mod as "the cause". It lists the mods that appear
in the matched evidence, which is a different and weaker statement.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

CATEGORIES = [
    "OutOfMemoryError",
    "JavaHeapError",
    "FabricLoaderError",
    "ModDependencyError",
    "MissingMod",
    "IncompatibleMod",
    "MixinError",
    "ClassNotFoundException",
    "NoSuchMethodError",
    "ServerThreadCrash",
    "WorldChunkError",
    "NetworkError",
    "DiskStorageError",
    "JavaVersionIncompatible",
    "PortInUse",
    "EulaNotAccepted",
    "Unknown",
]

MOD_ID_RE = re.compile(r"\b(?:mod|modid|mod id)[ '\"]*([a-z0-9_\-]{2,40})", re.IGNORECASE)
QUOTED_MOD_RE = re.compile(r"'([a-z0-9_\-]{2,40})'")


@dataclass
class Rule:
    category: str
    confidence: str  # confirmed | likely | possible
    summary: str
    patterns: list[re.Pattern]
    advice: str = ""
    weight: int = 10

    def match(self, lines: Iterable[str]) -> list[str]:
        hits: list[str] = []
        for line in lines:
            for pattern in self.patterns:
                if pattern.search(line):
                    hits.append(line.strip())
                    break
        return hits


def _p(*patterns: str) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


RULES: list[Rule] = [
    Rule(
        "OutOfMemoryError",
        "confirmed",
        "The server ran out of memory allocated to the Java heap.",
        _p(r"java\.lang\.OutOfMemoryError", r"GC overhead limit exceeded"),
        advice="Raise -Xmx (currently set in the launch arguments), or reduce view distance, "
        "entity counts and memory-heavy mods.",
        weight=100,
    ),
    Rule(
        "JavaHeapError",
        "confirmed",
        "The Java heap could not be allocated or sized.",
        _p(
            r"Could not reserve enough space for .* object heap",
            r"Error occurred during initialization of VM",
            r"Invalid maximum heap size",
        ),
        advice="The -Xmx value is larger than the memory Windows can give the JVM. "
        "Lower it, or install more RAM.",
        weight=95,
    ),
    Rule(
        "JavaVersionIncompatible",
        "confirmed",
        "The Java version does not match what this Minecraft or Fabric build needs.",
        _p(
            r"UnsupportedClassVersionError",
            r"has been compiled by a more recent version of the Java Runtime",
            r"requires Java (\d+)",
            r"class file version \d+\.\d+",
        ),
        advice="Minecraft 1.20.5+ needs Java 21; 1.17-1.20.4 needs Java 17. "
        "Point server.java at the right JDK.",
        weight=95,
    ),
    Rule(
        "ModDependencyError",
        "likely",
        "A mod is missing a dependency, or a dependency version does not match.",
        _p(
            r"requires (?:any )?version",
            r"which is missing",
            r"Incompatible mods found",
            r"ModResolutionException",
            r"unmet dependency listing",
            r"requires .* of .*, which is missing",
        ),
        advice="Install the required dependency at the version shown, or remove the mod that needs it.",
        weight=90,
    ),
    Rule(
        "MissingMod",
        "likely",
        "A mod was referenced but is not installed.",
        _p(r"Could not find required mod", r"Missing mod", r"mod .* is missing"),
        advice="Install the named mod, or remove whatever depends on it.",
        weight=85,
    ),
    Rule(
        "IncompatibleMod",
        "likely",
        "Two mods declared that they cannot run together, or a mod refuses this Minecraft version.",
        _p(
            r"is incompatible with",
            r"breaks mod",
            r"conflicts with",
            r"Mod .* requires minecraft [^,]*, which is incompatible",
        ),
        advice="Remove or downgrade one of the two mods named in the evidence.",
        weight=85,
    ),
    Rule(
        "MixinError",
        "likely",
        "A mod's Mixin failed to apply. This usually means the mod does not match this "
        "Minecraft version, or two mods patched the same code.",
        _p(
            r"org\.spongepowered\.asm\.mixin",
            r"Mixin apply for mod",
            r"InjectionError",
            r"MixinApplyError",
            r"MixinTransformerError",
            r"was not found in ",
        ),
        advice="Update the mod named in the mixin line, or disable it to confirm.",
        weight=88,
    ),
    Rule(
        "FabricLoaderError",
        "likely",
        "Fabric Loader itself refused to start the server.",
        _p(
            r"net\.fabricmc\.loader\.impl\.FormattedException",
            r"Fabric Loader .* is not compatible",
            r"An error occurred while loading mods",
            r"FabricMC .* crashed",
        ),
        advice="Check the Fabric Loader version against the Minecraft version, then check mod compatibility.",
        weight=80,
    ),
    Rule(
        "ClassNotFoundException",
        "possible",
        "A class was missing at runtime, which usually points at a version mismatch between mods.",
        _p(r"ClassNotFoundException", r"NoClassDefFoundError"),
        advice="Usually a mod built for a different Minecraft or Fabric API version.",
        weight=60,
    ),
    Rule(
        "NoSuchMethodError",
        "possible",
        "A method was missing at runtime, which usually points at mismatched mod versions.",
        _p(r"NoSuchMethodError", r"NoSuchFieldError", r"AbstractMethodError"),
        advice="Update Fabric API and the mods listed in the stack trace to matching versions.",
        weight=60,
    ),
    Rule(
        "WorldChunkError",
        "possible",
        "The crash happened while loading or saving world data.",
        _p(
            r"Exception (?:generating|loading|saving) new chunk",
            r"ChunkSerializer",
            r"Chunk file at .* is missing",
            r"Failed to save chunk",
            r"level\.dat",
            r"ReportedException: (?:Loading|Saving) entity",
        ),
        advice="A chunk or region file may be damaged. Restore a backup of the affected dimension.",
        weight=55,
    ),
    Rule(
        "DiskStorageError",
        "confirmed",
        "The server could not write to disk.",
        _p(
            r"No space left on device",
            r"There is not enough space on the disk",
            r"IOException.*(?:disk|space)",
            r"Failed to write.*lock",
            r"Access is denied",
        ),
        advice="Free disk space on the server drive, or check that the agent has write permission.",
        weight=90,
    ),
    Rule(
        "PortInUse",
        "confirmed",
        "The Minecraft port is already in use, so the server could not bind it.",
        _p(r"Address already in use", r"FAILED TO BIND TO PORT", r"BindException"),
        advice="Another Minecraft process is probably still running. Check for a stray java.exe.",
        weight=95,
    ),
    Rule(
        "EulaNotAccepted",
        "confirmed",
        "The Minecraft EULA has not been accepted.",
        _p(r"You need to agree to the EULA", r"eula\.txt"),
        advice="Set eula=true in eula.txt in the server folder.",
        weight=95,
    ),
    Rule(
        "NetworkError",
        "possible",
        "A networking problem appeared around the crash.",
        _p(
            r"java\.net\.(?:SocketException|ConnectException|UnknownHostException)",
            r"Connection reset by peer",
            r"Internal Exception: io\.netty",
        ),
        advice="Often harmless on its own; look for another cause before acting on this.",
        weight=35,
    ),
    Rule(
        "ServerThreadCrash",
        "possible",
        "The main server thread threw an exception.",
        _p(
            r"Exception in server tick loop",
            r"Encountered an unexpected exception",
            r"ReportedException",
            r"Exception in thread \"Server thread\"",
            r"The game crashed whilst",
            r"watchdog",
            r"Considering it to be crashed",
        ),
        advice="Read the stack trace for the mod package that appears first.",
        weight=45,
    ),
]


@dataclass
class Analysis:
    category: str = "Unknown"
    confidence: str = "unknown"  # confirmed | likely | possible | unknown
    summary: str = "The cause could not be determined from the available logs."
    advice: str = ""
    evidence: list[str] = field(default_factory=list)
    suspect_mods: list[str] = field(default_factory=list)
    other_matches: list[dict[str, Any]] = field(default_factory=list)
    exception: str | None = None
    evidence_basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "summary": self.summary,
            "advice": self.advice,
            "evidence": self.evidence,
            "suspect_mods": self.suspect_mods,
            "other_matches": self.other_matches,
            "exception": self.exception,
            "evidence_basis": self.evidence_basis,
            "disclaimer": (
                "This is a pattern match against the log text. "
                "The evidence lines are shown so you can judge it yourself."
            ),
        }


EXCEPTION_RE = re.compile(
    r"((?:[a-z][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_$]*(?:Error|Exception))(?::\s*(.*))?"
)


def find_exception(lines: Iterable[str]) -> str | None:
    for line in lines:
        if m := EXCEPTION_RE.search(line):
            detail = (m.group(2) or "").strip()
            return f"{m.group(1)}: {detail}" if detail else m.group(1)
    return None


def guess_mods(lines: Iterable[str], known_mod_ids: Iterable[str] = ()) -> list[str]:
    """List installed mods whose id appears anywhere in the analysed log.

    This is an observation, not an accusation: a mod's package showing up in a
    stack frame often means it was merely the code running when an unrelated
    problem surfaced. Callers must present this as "mods mentioned", never as
    "the cause".
    """
    known = {m.lower() for m in known_mod_ids}
    found: list[str] = []
    for line in lines:
        lowered = line.lower()
        for mod_id in known:
            if mod_id and re.search(rf"\b{re.escape(mod_id)}\b", lowered) and mod_id not in found:
                found.append(mod_id)
        if not known:
            for match in QUOTED_MOD_RE.findall(line):
                if match not in found and match not in {"minecraft", "java", "fabricloader"}:
                    found.append(match)
    return found[:5]


def unknown_cause(lines: Iterable[str], exit_code: int | None = None) -> Analysis:
    """A Bedrock server's crash: the last lines and the exit code, with the
    cause left Unknown. Its console doesn't print enough to name one."""
    lines = [ln for ln in lines if ln and ln.strip()]
    analysis = Analysis()
    analysis.summary = (
        "The cause can't be read from a Bedrock server's console, so none is claimed."
        + (f" It exited with code {exit_code}." if exit_code is not None else "")
    )
    analysis.evidence = lines[-8:]
    analysis.evidence_basis = "Bedrock servers print too little when they stop to identify a cause."
    return analysis


def analyze(
    lines: Iterable[str], exit_code: int | None = None, known_mod_ids: Iterable[str] = ()
) -> Analysis:
    lines = [ln for ln in lines if ln and ln.strip()]
    scored: list[tuple[int, Rule, list[str]]] = []
    for rule in RULES:
        hits = rule.match(lines)
        if hits:
            scored.append((rule.weight, rule, hits))
    scored.sort(key=lambda item: item[0], reverse=True)

    analysis = Analysis()
    analysis.exception = find_exception(lines)

    if not scored:
        if exit_code == 0:
            analysis.summary = (
                "The process exited with code 0 but was not asked to stop. "
                "Nothing in the log identifies a cause."
            )
        analysis.evidence = [ln for ln in lines if "ERROR" in ln.upper()][-8:]
        analysis.suspect_mods = guess_mods(analysis.evidence, known_mod_ids)
        analysis.evidence_basis = "No known pattern matched. No cause is being claimed."
        return analysis

    _, best, hits = scored[0]
    analysis.category = best.category
    analysis.confidence = best.confidence
    analysis.summary = best.summary
    analysis.advice = best.advice
    analysis.evidence = hits[-6:]
    analysis.evidence_basis = {
        "confirmed": "The error itself appears in the log, so the category is certain. "
        "What triggered it may still be a separate question.",
        "likely": "Strong evidence, but the printed error is often a symptom of a "
        "different underlying problem.",
        "possible": "The pattern matched, but it is frequently incidental. "
        "Look for another cause before acting on it.",
    }.get(best.confidence, "")
    # Stack frames name the mod package far more often than the matched line
    # does, so they are included in the scan.
    frames = [ln for ln in lines if ln.strip().startswith("at ") or "\tat " in ln]
    analysis.suspect_mods = guess_mods(hits + frames, known_mod_ids)
    analysis.other_matches = [
        {"category": rule.category, "confidence": rule.confidence, "evidence": h[-2:]}
        for _, rule, h in scored[1:4]
    ]
    return analysis
