import json

import httpx

from parable.paypal import PayPalClient


class Recorder:
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        handler = self.routes.get(key)
        if handler is None:
            return httpx.Response(404, json={"name": "NOT_FOUND"})
        return handler(request) if callable(handler) else handler

    def sent(self, method, path):
        return [r for r in self.requests if r.method == method and r.url.path == path]


def token_response(expires_in=32400, token="tok-1"):
    return httpx.Response(200, json={"access_token": token, "expires_in": expires_in})


def build(routes, **options):
    recorder = Recorder({("POST", "/v1/oauth2/token"): token_response(), **routes})
    http = httpx.Client(transport=httpx.MockTransport(recorder))
    client = PayPalClient(client_id="cid", client_secret="secret", env="sandbox", http=http, **options)
    return client, recorder


def body_of(request):
    return json.loads(request.content)
