"""Pure functions to extract framework signals from common manifest files.

We don't try to be exhaustive — we extract enough to answer:
    "Is this person a Python+FastAPI dev? Or Rust+Tokio? Or Go+gRPC?"

Each parser returns a list of framework/library names (lowercased).
Unknown formats return [] silently (never raise).
"""
from __future__ import annotations

import json
import re
import tomllib

# Manifest filenames we recognize. Keys map to a parser function below.
KNOWN_MANIFESTS = (
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "composer.json",
    "pom.xml",
)


def parse_manifest(filename: str, content: str) -> list[str]:
    """Dispatch to the right parser based on filename. Always returns a list."""
    parsers = {
        "package.json": parse_package_json,
        "requirements.txt": parse_requirements_txt,
        "pyproject.toml": parse_pyproject_toml,
        "Pipfile": parse_pipfile,
        "Cargo.toml": parse_cargo_toml,
        "go.mod": parse_go_mod,
        "Gemfile": parse_gemfile,
        "composer.json": parse_composer_json,
        "pom.xml": parse_pom_xml,
    }
    parser = parsers.get(filename)
    if parser is None:
        return []
    try:
        return parser(content)
    except Exception:
        return []  # never let a malformed manifest break profiling


# ---------------------------------------------------------------------------
# Per-format parsers
# ---------------------------------------------------------------------------

def parse_package_json(content: str) -> list[str]:
    data = json.loads(content)
    deps: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            deps.update(section)
    return sorted({_normalize(name) for name in deps if name})


def parse_requirements_txt(content: str) -> list[str]:
    out: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-", "git+", "http://", "https://")):
            continue
        # Strip extras, version specifiers, env markers
        # e.g. "fastapi[all]>=0.110 ; python_version>=3.10" -> "fastapi"
        name = re.split(r"[\s\[<>=!~;]", line, maxsplit=1)[0]
        if name:
            out.add(_normalize(name))
    return sorted(out)


def parse_pyproject_toml(content: str) -> list[str]:
    data = tomllib.loads(content)
    out: set[str] = set()

    # PEP 621 (modern, project-style)
    project = data.get("project", {}) or {}
    for dep in project.get("dependencies", []) or []:
        if isinstance(dep, str):
            out.add(_pep_dep_name(dep))
    for group in (project.get("optional-dependencies") or {}).values():
        for dep in group:
            if isinstance(dep, str):
                out.add(_pep_dep_name(dep))

    # Poetry style
    poetry = (data.get("tool", {}) or {}).get("poetry", {}) or {}
    for section_name in ("dependencies", "dev-dependencies"):
        section = poetry.get(section_name) or {}
        for name in section:
            if name.lower() != "python":
                out.add(_normalize(name))

    return sorted(o for o in out if o)


def parse_pipfile(content: str) -> list[str]:
    data = tomllib.loads(content)
    out: set[str] = set()
    for key in ("packages", "dev-packages"):
        section = data.get(key) or {}
        for name in section:
            out.add(_normalize(name))
    return sorted(out)


def parse_cargo_toml(content: str) -> list[str]:
    data = tomllib.loads(content)
    out: set[str] = set()
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        section = data.get(key) or {}
        for name in section:
            out.add(_normalize(name))
    return sorted(out)


def parse_go_mod(content: str) -> list[str]:
    """Extract module paths from a go.mod's `require` blocks."""
    out: set[str] = set()
    in_require_block = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("require ("):
            in_require_block = True
            continue
        if in_require_block:
            if line.startswith(")"):
                in_require_block = False
                continue
            parts = line.split()
            if parts and parts[0] and not parts[0].startswith("//"):
                out.add(parts[0])
        elif line.startswith("require "):
            # `require <path> <version>` single-line form
            parts = line.split()
            if len(parts) >= 2:
                out.add(parts[1])
    return sorted(out)


def parse_gemfile(content: str) -> list[str]:
    pattern = re.compile(r"^\s*gem\s+['\"]([^'\"]+)['\"]")
    out: set[str] = set()
    for line in content.splitlines():
        m = pattern.match(line)
        if m:
            out.add(_normalize(m.group(1)))
    return sorted(out)


def parse_composer_json(content: str) -> list[str]:
    data = json.loads(content)
    out: set[str] = set()
    for key in ("require", "require-dev"):
        section = data.get(key) or {}
        for name in section:
            if name != "php":
                out.add(_normalize(name))
    return sorted(out)


def parse_pom_xml(content: str) -> list[str]:
    """Very loose extraction — full XML parse is overkill for fingerprinting."""
    pattern = re.compile(
        r"<artifactId>\s*([\w.\-]+)\s*</artifactId>", re.IGNORECASE
    )
    return sorted({_normalize(m) for m in pattern.findall(content)})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pep_dep_name(spec: str) -> str:
    """Pull the package name out of a PEP-508 dependency string."""
    return _normalize(re.split(r"[\s\[<>=!~;]", spec, maxsplit=1)[0])


def _normalize(name: str) -> str:
    return name.strip().lower()
