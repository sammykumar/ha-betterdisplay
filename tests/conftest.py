"""Shared fixtures.

The payloads here are captured from a real BetterDisplay 4.3.6 install rather
than written from the documentation, so the parser is exercised against the
quirks the API actually has.

Requests go through a real aiohttp test server instead of a mocking library:
BetterDisplay's oddities are all in how it encodes queries and bodies, and a
stub that accepts whatever the client sends would not catch a regression there.
"""

from __future__ import annotations

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from yarl import URL

from custom_components.betterdisplay.api import BetterDisplayClient

# `/get?identifiers` answers with comma-separated objects and no array wrapper,
# and includes non-display devices that have to be filtered out.
IDENTIFIERS_PAYLOAD = """{
  "UUID" : "2AACFE96-FD70-4864-A835-00B570AECA49",
  "alphanumericSerial" : "H1AK000000",
  "deviceType" : "Display",
  "displayID" : "2",
  "model" : "3996",
  "name" : "C49RG9x",
  "originalName" : "C49RG9x",
  "productName" : "C49RG9x",
  "serial" : "0",
  "tagID" : "4",
  "vendor" : "19501",
  "weekOfManufacture" : "43",
  "yearOfManufacture" : "2018"
},{
  "UUID" : "711AB070-01BD-4906-84F3-E907E4BDE416",
  "alphanumericSerial" : "HNTWC00000",
  "deviceType" : "Display",
  "displayID" : "5",
  "model" : "29816",
  "name" : "Odyssey G95NC",
  "originalName" : "Odyssey G95NC",
  "productName" : "Odyssey G95NC",
  "serial" : "100000000",
  "tagID" : "1019",
  "vendor" : "19501",
  "weekOfManufacture" : "50",
  "yearOfManufacture" : "2023"
},{
  "deviceType" : "DisplayGroup",
  "name" : "Default Group",
  "tagID" : "-1001"
}"""

# Every DDC-addressable input, not the ports the panel actually has.
INPUT_SOURCE_LIST = """1 - DisplayPort 1 [DDCController]
2 - DisplayPort 2 [DDCController]
3 - HDMI 1 [DDCController]
4 - HDMI 2 [DDCController]
5 - HDMI 3 [DDCController]
6 - USB-C / TB 1 [DDCController]
7 - USB-C / TB 2 [DDCController]
8 - USB-C / TB 3 [DDCController]
9 - USB-C / TB 4 [DDCController]
10 - DVI 1 [DDCController]
11 - DVI 2 [DDCController]
12 - VGA 1 [DDCController]"""

UUID_C49 = "2AACFE96-FD70-4864-A835-00B570AECA49"
UUID_G95 = "711AB070-01BD-4906-84F3-E907E4BDE416"


class FakeBetterDisplay:
    """A stand-in for BetterDisplay's HTTP server that records what it got."""

    def __init__(self) -> None:
        self.body: str = ""
        self.status: int = 200
        self.requests: list[URL] = []
        self.host: str = ""
        self.port: int = 0

    def respond(self, body: str, status: int = 200) -> None:
        """Set the reply for subsequent requests."""
        self.body = body
        self.status = status

    @property
    def last_query(self) -> dict[str, str]:
        """Query parameters of the most recent request."""
        return dict(self.requests[-1].query)

    async def handle(self, request: web.Request) -> web.Response:
        """Record the request and reply with whatever was configured."""
        self.requests.append(request.rel_url)
        return web.Response(text=self.body, status=self.status)


@pytest.fixture
async def fake_server():
    """Run a fake BetterDisplay HTTP server on a free port."""
    fake = FakeBetterDisplay()
    app = web.Application()
    app.router.add_get("/get", fake.handle)
    app.router.add_get("/set", fake.handle)
    server = TestServer(app)
    await server.start_server()
    fake.host = server.host
    fake.port = server.port
    yield fake
    await server.close()


@pytest.fixture
async def session():
    """A client session shared by the tests."""
    async with ClientSession() as client_session:
        yield client_session


@pytest.fixture
def make_client(session, fake_server):
    """Build a client pointed at the fake server."""

    def _make(token: str | None = None) -> BetterDisplayClient:
        return BetterDisplayClient(session, fake_server.host, fake_server.port, token)

    return _make
