"""Authenticated loopback Streamable HTTP transport for the five demo-only tools."""
from __future__ import annotations

import argparse
import hmac
import os
from pathlib import Path
import secrets
import stat

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from . import mcp_server as controller

DEFAULT_TOKEN_FILE = Path.home() / ".config" / "harness2" / "mcp-http.token"


def load_token(token_file: Path | None = None) -> str:
    value = os.environ.get("HARNESS2_MCP_HTTP_TOKEN")
    if not value:
        path = token_file or Path(os.environ.get("HARNESS2_MCP_HTTP_TOKEN_FILE", DEFAULT_TOKEN_FILE))
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ValueError("Token file must be a regular file owned by this user")
            if stat.S_IMODE(metadata.st_mode) != 0o600:
                raise ValueError("Token file permissions must be 0600")
            with os.fdopen(descriptor, "r", closefd=False) as stream:
                value = stream.read(4096).strip()
        finally:
            os.close(descriptor)
    if len(value) < 32 or any(char.isspace() for char in value):
        raise ValueError("HTTP bearer token must have at least 32 non-whitespace characters")
    return value


def initialize_token(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(secrets.token_urlsafe(48) + "\n")


class BearerAuth:
    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = [(key.lower(), value) for key, value in scope["headers"]]
        supplied = [value for key, value in headers if key == b"authorization"]
        expected = ("Bearer " + self.token).encode()
        if len(supplied) != 1 or not hmac.compare_digest(supplied[0], expected):
            response = JSONResponse(
                {"error": "unauthorized"}, status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="harness2"'})
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


def create_app(token: str):
    if len(token) < 32:
        raise ValueError("A strong bearer token is required")
    server = MCPServer("Harness2 authenticated local controller")
    for function in (controller.harness2_status, controller.harness2_start_demo,
                     controller.harness2_run_status, controller.harness2_results,
                     controller.harness2_cancel, controller.harness2_plan_run,
                     controller.harness2_start_run, controller.harness2_start_judge,
                     controller.harness2_report, controller.harness2_start_rf_run):
        server.tool(structured_output=True)(controller._sdk_tool(function))
    allowed_hosts = ["127.0.0.1:*", "localhost:*"]
    tunnel_host = os.environ.get("HARNESS2_MCP_ALLOWED_HOST")
    if tunnel_host:
        if any(character in tunnel_host for character in ("/", "*", " ", "\n")):
            raise ValueError("HARNESS2_MCP_ALLOWED_HOST must be one exact host[:port]")
        allowed_hosts.append(tunnel_host)
    application = server.streamable_http_app(
        json_response=True, stateless_http=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=allowed_hosts,
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]),
        host="127.0.0.1")
    # Preserve the SDK app's session-manager lifespan.
    application.add_middleware(BearerAuth, token=token)
    return application


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8796)
    parser.add_argument("--init-token", action="store_true")
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    if args.init_token:
        initialize_token(args.token_file or DEFAULT_TOKEN_FILE)
        print("Token file created with mode 0600; token value was not printed.")
        return
    import uvicorn
    uvicorn.run(create_app(load_token(args.token_file)), host="127.0.0.1",
                port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
