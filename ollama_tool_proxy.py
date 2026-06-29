#!/usr/bin/env python3
"""
Ollama Tool-Call Proxy for Hermes Agent.

Sits between Hermes and the OVH Ollama endpoint.  When Qwen3-coder emits
XML-style tool calls in plain text (instead of structured JSON tool_calls),
this proxy parses the XML and rewrites the response so Hermes sees proper
tool_calls.

Usage:
    python3 ollama_tool_proxy.py [--port PORT] [--target URL]

Then point Hermes at  http://127.0.0.1:<PORT>/v1
"""

import argparse
import json
import re
import sys
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import requests

# ---------------------------------------------------------------------------
# Configuration (overridable via CLI args)
# ---------------------------------------------------------------------------
DEFAULT_PORT = 11435
DEFAULT_TARGET = (
    "https://4d985b5d-cc47-4111-ae73-4fc72ded9990"
    ".app.gra.ai.cloud.ovh.net"
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ollama-proxy")

# ---------------------------------------------------------------------------
# XML Tool-Call Parser
# ---------------------------------------------------------------------------
_FUNC_RE = re.compile(
    r"<function=(\w+)>(.*?)</function>",
    re.DOTALL,
)
_PARAM_RE = re.compile(
    r"<parameter=(\w+)>\s*(.*?)\s*</parameter>",
    re.DOTALL,
)

_call_counter = 0


def parse_xml_tool_calls(content: str) -> list[dict] | None:
    """Parse Qwen3-style XML tool calls from assistant content.

    Returns a list of OpenAI-format tool_call dicts, or None if no
    XML tool calls were found.
    """
    global _call_counter

    matches = _FUNC_RE.findall(content)
    if not matches:
        # Also try without </function> (sometimes truncated)
        # Pattern: <function=name> ... (to end of string or </tool_call>)
        alt = re.findall(
            r"<function=(\w+)>(.*?)(?:</tool_call>|$)",
            content,
            re.DOTALL,
        )
        if alt:
            matches = alt
        else:
            return None

    tool_calls = []
    for func_name, func_body in matches:
        params = {}
        for param_name, param_value in _PARAM_RE.findall(func_body):
            # Try to parse JSON values (booleans, numbers, etc.)
            stripped = param_value.strip()
            try:
                params[param_name] = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                params[param_name] = stripped

        _call_counter += 1
        tool_calls.append({
            "id": f"call_proxy_{_call_counter:04d}",
            "index": len(tool_calls),
            "type": "function",
            "function": {
                "name": func_name,
                "arguments": json.dumps(params),
            },
        })

    return tool_calls if tool_calls else None


def rewrite_response(data: dict) -> bool:
    """Mutate *data* in-place: convert XML tool calls → structured tool_calls.

    Returns True if any rewriting happened.
    """
    changed = False
    for choice in data.get("choices", []):
        msg = choice.get("message", {})
        content = msg.get("content") or ""
        existing_tc = msg.get("tool_calls")

        # Only rewrite when there are no structured tool_calls yet
        if existing_tc:
            continue

        tool_calls = parse_xml_tool_calls(content)
        if tool_calls:
            msg["tool_calls"] = tool_calls
            # Remove the XML from content (keep any text before/after)
            cleaned = _FUNC_RE.sub("", content)
            cleaned = re.sub(r"</tool_call>", "", cleaned)
            cleaned = re.sub(r"<tool_call>", "", cleaned)
            msg["content"] = cleaned.strip()
            choice["finish_reason"] = "tool_calls"
            changed = True
            log.info(
                "✅ Rewrote %d XML tool call(s) → JSON: %s",
                len(tool_calls),
                ", ".join(tc["function"]["name"] for tc in tool_calls),
            )
    return changed


# ---------------------------------------------------------------------------
# HTTP Proxy Handler
# ---------------------------------------------------------------------------
class ProxyHandler(BaseHTTPRequestHandler):
    target_base: str = DEFAULT_TARGET

    def log_message(self, format, *args):
        """Override to use our logger."""
        log.debug(format, *args)

    # -- Helpers -------------------------------------------------------------

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _forward_headers(self) -> dict:
        """Build headers dict for the upstream request."""
        out = {}
        for key in ("Authorization", "Content-Type", "Accept"):
            val = self.headers.get(key)
            if val:
                out[key] = val
        return out

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy_raw(self, method: str):
        """Forward any request transparently (GET, POST, etc.)."""
        url = self.target_base + self.path
        body = self._read_body()
        headers = self._forward_headers()

        try:
            resp = requests.request(
                method, url,
                headers=headers,
                data=body,
                timeout=600,
                stream=False,
            )
        except Exception as exc:
            log.error("Upstream error: %s", exc)
            self._send_json(502, {"error": str(exc)})
            return

        # Return upstream response as-is
        self.send_response(resp.status_code)
        for key, val in resp.headers.items():
            if key.lower() not in ("transfer-encoding", "content-length",
                                    "connection"):
                self.send_header(key, val)
        body_out = resp.content
        self.send_header("Content-Length", str(len(body_out)))
        self.end_headers()
        self.wfile.write(body_out)

    # -- HTTP verbs ----------------------------------------------------------

    def do_GET(self):
        self._proxy_raw("GET")

    def do_POST(self):
        url = self.target_base + self.path
        body = self._read_body()
        headers = self._forward_headers()

        # Only intercept chat/completions
        if "/chat/completions" not in self.path:
            self._proxy_raw_post(url, body, headers)
            return

        # Parse the request — force stream=false so we can intercept
        # and rewrite XML tool calls from Qwen3.
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        was_streaming = req_data.get("stream", False)
        if was_streaming:
            req_data["stream"] = False
            body = json.dumps(req_data).encode()
            log.info("📡 Forced stream:true → stream:false for rewriting")
        else:
            log.info("📡 Non-streaming chat/completions → forwarding")

        try:
            resp = requests.post(
                url,
                headers=headers,
                data=body,
                timeout=600,
            )
        except Exception as exc:
            log.error("Upstream error: %s", exc)
            self._send_json(502, {"error": str(exc)})
            return

        if resp.status_code != 200:
            log.warning("Upstream returned %d", resp.status_code)
            self.send_response(resp.status_code)
            self.send_header("Content-Type", "application/json")
            body_out = resp.content
            self.send_header("Content-Length", str(len(body_out)))
            self.end_headers()
            self.wfile.write(body_out)
            return

        try:
            data = resp.json()
        except Exception as exc:
            log.error("Failed to parse upstream JSON: %s", exc)
            self._send_json(502, {"error": f"Bad upstream JSON: {exc}"})
            return

        # ── Rewrite XML tool calls ──
        rewrite_response(data)

        if was_streaming:
            # Convert the non-streaming JSON response into SSE chunks
            # that Hermes expects when it sent stream:true.
            self._send_as_sse(data)
        else:
            self._send_json(200, data)

    def _send_as_sse(self, data: dict):
        """Convert a chat.completion JSON response into SSE stream chunks."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        comp_id = data.get("id", "chatcmpl-proxy")
        created = data.get("created", 0)
        model = data.get("model", "")

        for choice in data.get("choices", []):
            msg = choice.get("message", {})
            finish_reason = choice.get("finish_reason")
            index = choice.get("index", 0)

            # 1) Role chunk
            role_chunk = {
                "id": comp_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{
                    "index": index,
                    "delta": {"role": msg.get("role", "assistant")},
                    "finish_reason": None,
                }],
            }
            self.wfile.write(f"data: {json.dumps(role_chunk)}\n\n".encode())

            # 2) Content chunk (if any)
            content = msg.get("content")
            if content:
                content_chunk = {
                    "id": comp_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{
                        "index": index,
                        "delta": {"content": content},
                        "finish_reason": None,
                    }],
                }
                self.wfile.write(
                    f"data: {json.dumps(content_chunk)}\n\n".encode()
                )

            # 3) Tool call chunks (if any)
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    # First chunk: id + function name
                    tc_init_chunk = {
                        "id": comp_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{
                            "index": index,
                            "delta": {
                                "tool_calls": [{
                                    "index": tc.get("index", 0),
                                    "id": tc["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tc["function"]["name"],
                                        "arguments": "",
                                    },
                                }],
                            },
                            "finish_reason": None,
                        }],
                    }
                    self.wfile.write(
                        f"data: {json.dumps(tc_init_chunk)}\n\n".encode()
                    )

                    # Second chunk: arguments
                    tc_args_chunk = {
                        "id": comp_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{
                            "index": index,
                            "delta": {
                                "tool_calls": [{
                                    "index": tc.get("index", 0),
                                    "function": {
                                        "arguments":
                                            tc["function"]["arguments"],
                                    },
                                }],
                            },
                            "finish_reason": None,
                        }],
                    }
                    self.wfile.write(
                        f"data: {json.dumps(tc_args_chunk)}\n\n".encode()
                    )

            # 4) Finish chunk
            finish_chunk = {
                "id": comp_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{
                    "index": index,
                    "delta": {},
                    "finish_reason": finish_reason,
                }],
            }
            self.wfile.write(
                f"data: {json.dumps(finish_chunk)}\n\n".encode()
            )

        # 5) [DONE] sentinel
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True
        log.info("✅ Sent SSE response (%d choices)", len(data.get("choices", [])))

    def _proxy_raw_post(self, url, body, headers):
        try:
            resp = requests.post(
                url,
                headers=headers,
                data=body,
                timeout=600,
                stream=False,
            )
        except Exception as exc:
            log.error("Upstream error: %s", exc)
            self._send_json(502, {"error": str(exc)})
            return

        self.send_response(resp.status_code)
        for key, val in resp.headers.items():
            if key.lower() not in ("transfer-encoding", "content-length",
                                    "connection"):
                self.send_header(key, val)
        body_out = resp.content
        self.send_header("Content-Length", str(len(body_out)))
        self.end_headers()
        self.wfile.write(body_out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
import signal

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Local port (default {DEFAULT_PORT})")
    parser.add_argument("--target", default=DEFAULT_TARGET,
                        help="Upstream OVH base URL")
    parser.add_argument("--bind", default="0.0.0.0",
                        help="IP address to bind to (default 0.0.0.0)")
    args = parser.parse_args()

    ProxyHandler.target_base = args.target.rstrip("/")

    server = HTTPServer((args.bind, args.port), ProxyHandler)
    log.info("🚀 Ollama Tool-Call Proxy running on http://%s:%d", args.bind, args.port)
    log.info("   Upstream: %s", ProxyHandler.target_base)

    # Clean shutdown on SIGTERM (Docker container stop)
    def sigterm_handler(signum, frame):
        log.info("Received SIGTERM. Shutting down...")
        server.server_close()
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, sigterm_handler)

    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
