"""The container starts the module the Dockerfile names, on the port compose probes.

A fifth scoring round found the container could not start: the Dockerfile ``CMD``
named ``src.interfaces.tv_cockpit:app``, a module that does not exist, while
``docker-compose.yml`` health-checked ``/v1/health``, a path the server never had,
on a port the server was not told to listen on. None of that needed Docker to be
caught. These tests read the two files, import the module the ``CMD`` names, and
compare every port and path against the application object, so the entrypoint is
checked by ``python -m pytest tests/ -q`` and not by the first person to run
``docker compose up``.
"""
import importlib
import json
import re
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCKERFILE = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICE = next(iter(COMPOSE["services"].values()))


def _cmd() -> list[str]:
    match = re.search(r"^CMD\s+(\[.*\])\s*$", DOCKERFILE, re.MULTILINE)
    assert match, "the Dockerfile has no exec-form CMD"
    return json.loads(match.group(1))


def _cmd_target() -> tuple[str, str]:
    cmd = _cmd()
    assert cmd[0] == "uvicorn", f"the container entrypoint is {cmd[0]}, not uvicorn"
    module, _, attribute = cmd[1].partition(":")
    assert module and attribute, f"uvicorn target {cmd[1]!r} is not module:attribute"
    return module, attribute


def _cmd_port() -> int:
    cmd = _cmd()
    assert "--port" in cmd, "the CMD does not say which port uvicorn listens on"
    return int(cmd[cmd.index("--port") + 1])


def _healthcheck_url() -> str:
    test = SERVICE["healthcheck"]["test"]
    joined = " ".join(test) if isinstance(test, list) else test
    match = re.search(r"https?://[^'\"\s]+", joined)
    assert match, f"the compose healthcheck names no URL: {joined}"
    return match.group(0)


def test_the_module_the_dockerfile_names_imports_and_exposes_the_app():
    module_name, attribute = _cmd_target()
    module = importlib.import_module(module_name)
    app = getattr(module, attribute, None)
    assert isinstance(app, FastAPI), (
        f"the Dockerfile starts {module_name}:{attribute}, which is not a FastAPI application"
    )


def test_the_module_the_dockerfile_names_is_a_file_that_ships_in_the_image():
    """The image copies ``src/``; the module it starts has to live under it."""
    module_name, _ = _cmd_target()
    assert module_name.startswith("src."), f"{module_name} is not under the src/ tree the image copies"
    assert (REPO_ROOT / (module_name.replace(".", "/") + ".py")).exists(), (
        f"{module_name} does not exist as a file in this repository"
    )
    assert re.search(r"^COPY\s+src/\s+/app/src/\s*$", DOCKERFILE, re.MULTILINE), (
        "the runtime stage does not copy src/ beside docs/, so the server would not find "
        "the cockpit page it resolves relative to its own file"
    )


def test_the_compose_healthcheck_path_is_a_route_the_application_serves():
    module_name, attribute = _cmd_target()
    app = getattr(importlib.import_module(module_name), attribute)
    path = re.sub(r"^https?://[^/]+", "", _healthcheck_url()) or "/"
    routes = {route.path for route in app.routes}
    assert path in routes, f"compose probes {path}, the application serves {sorted(routes)}"
    # And an exact match, not the single-segment asset catch-all answering with a 404 body.
    response = TestClient(app).get(path)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_every_port_in_the_dockerfile_and_compose_file_is_the_one_uvicorn_listens_on():
    port = _cmd_port()
    exposed = re.findall(r"^EXPOSE\s+(\d+)", DOCKERFILE, re.MULTILINE)
    assert exposed == [str(port)], f"Dockerfile EXPOSE {exposed} but uvicorn listens on {port}"

    for mapping in SERVICE["ports"]:
        host_port, _, container_port = str(mapping).rpartition(":")
        assert int(container_port) == port, f"compose maps to container port {container_port}, uvicorn listens on {port}"
        assert int(host_port or container_port) == port, (
            f"compose publishes host port {host_port}; the README tells readers to open port {port}"
        )

    health_port = re.search(r":(\d+)/", _healthcheck_url())
    assert health_port and int(health_port.group(1)) == port, (
        f"the compose healthcheck probes {_healthcheck_url()}, uvicorn listens on {port}"
    )


def test_the_container_port_is_the_one_the_readme_tells_readers_to_open():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    port = _cmd_port()
    assert f"127.0.0.1:{port}/" in readme, f"the README never tells the reader to open port {port}"
    assert not re.search(r"127\.0\.0\.1:(?!%d\b)\d+" % port, readme), (
        "the README names a local port other than the one the container listens on"
    )
