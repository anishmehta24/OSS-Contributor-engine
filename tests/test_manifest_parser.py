"""Deterministic tests for the manifest parsers.

These exercise real-world manifest snippets so we know what the Skill
Profiler will see in practice. Pure functions = easy to test exhaustively.
"""
from __future__ import annotations

import pytest

from app.agents.profiles.manifest_parser import (
    parse_cargo_toml,
    parse_composer_json,
    parse_gemfile,
    parse_go_mod,
    parse_manifest,
    parse_package_json,
    parse_pipfile,
    parse_pom_xml,
    parse_pyproject_toml,
    parse_requirements_txt,
)

# ---------------------------------------------------------------------------
# package.json
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_package_json_basic():
    content = """{
        "name": "x",
        "dependencies": { "react": "^18.0.0", "next": "^14" },
        "devDependencies": { "typescript": "5.0.0" }
    }"""
    assert parse_package_json(content) == ["next", "react", "typescript"]


@pytest.mark.unit
def test_package_json_includes_peer_deps():
    content = """{
        "peerDependencies": { "react-dom": "*" }
    }"""
    assert parse_package_json(content) == ["react-dom"]


@pytest.mark.unit
def test_package_json_malformed_returns_empty():
    assert parse_manifest("package.json", "{not json") == []


# ---------------------------------------------------------------------------
# requirements.txt
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_requirements_txt_basic():
    content = """fastapi>=0.110
sqlalchemy==2.0.0
pydantic
# a comment
-r other.txt
git+https://github.com/foo/bar.git
"""
    assert parse_requirements_txt(content) == ["fastapi", "pydantic", "sqlalchemy"]


@pytest.mark.unit
def test_requirements_txt_strips_extras_and_markers():
    content = "uvicorn[standard]>=0.30 ; python_version>='3.10'"
    assert parse_requirements_txt(content) == ["uvicorn"]


# ---------------------------------------------------------------------------
# pyproject.toml
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pyproject_pep621():
    content = """
[project]
name = "x"
dependencies = ["fastapi>=0.110", "sqlalchemy"]

[project.optional-dependencies]
dev = ["pytest", "ruff"]
"""
    assert parse_pyproject_toml(content) == ["fastapi", "pytest", "ruff", "sqlalchemy"]


@pytest.mark.unit
def test_pyproject_poetry_style():
    content = """
[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.110"
sqlalchemy = "^2.0"

[tool.poetry.dev-dependencies]
pytest = "^8"
"""
    assert parse_pyproject_toml(content) == ["fastapi", "pytest", "sqlalchemy"]


# ---------------------------------------------------------------------------
# Cargo.toml
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_cargo_toml_extracts_deps():
    content = """
[package]
name = "x"

[dependencies]
tokio = { version = "1", features = ["full"] }
serde = "1"

[dev-dependencies]
mockito = "1.6"
"""
    assert parse_cargo_toml(content) == ["mockito", "serde", "tokio"]


# ---------------------------------------------------------------------------
# go.mod
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_go_mod_block_form():
    content = """module example.com/x

go 1.22

require (
    github.com/gin-gonic/gin v1.10.0
    github.com/go-redis/redis/v9 v9.5.0
)
"""
    assert parse_go_mod(content) == [
        "github.com/gin-gonic/gin",
        "github.com/go-redis/redis/v9",
    ]


@pytest.mark.unit
def test_go_mod_single_line_form():
    content = "require github.com/foo/bar v1.0.0"
    assert parse_go_mod(content) == ["github.com/foo/bar"]


# ---------------------------------------------------------------------------
# Pipfile
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pipfile_extracts_packages():
    content = """
[packages]
fastapi = "*"
sqlalchemy = "*"

[dev-packages]
pytest = "*"
"""
    assert parse_pipfile(content) == ["fastapi", "pytest", "sqlalchemy"]


# ---------------------------------------------------------------------------
# Gemfile
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_gemfile_extracts_gems():
    content = """source "https://rubygems.org"
gem 'rails', '~> 7.1'
gem "puma"
# gem "commented_out"
group :development do
  gem "pry"
end
"""
    assert parse_gemfile(content) == ["pry", "puma", "rails"]


# ---------------------------------------------------------------------------
# composer.json
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_composer_json_basic():
    content = """{
        "require": { "php": ">=8.1", "laravel/framework": "^11.0" },
        "require-dev": { "phpunit/phpunit": "^10.5" }
    }"""
    assert parse_composer_json(content) == ["laravel/framework", "phpunit/phpunit"]


# ---------------------------------------------------------------------------
# pom.xml
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pom_xml_extracts_artifact_ids():
    content = """<project>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <artifactId>junit-jupiter</artifactId>
    </dependency>
  </dependencies>
</project>"""
    assert parse_pom_xml(content) == ["junit-jupiter", "spring-boot-starter-web"]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_parse_manifest_unknown_filename():
    assert parse_manifest("Makefile", "anything") == []


@pytest.mark.unit
def test_parse_manifest_routes_to_correct_parser():
    assert parse_manifest("requirements.txt", "fastapi") == ["fastapi"]
    assert parse_manifest("package.json", '{"dependencies":{"react":"^18"}}') == ["react"]


@pytest.mark.unit
def test_parsers_normalize_case():
    assert parse_requirements_txt("FastAPI") == ["fastapi"]
    assert parse_package_json('{"dependencies":{"React":"*"}}') == ["react"]
