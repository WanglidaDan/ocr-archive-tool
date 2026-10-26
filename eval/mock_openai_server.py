"""OpenAI-compatible stand-in. Not a vision model and not 昆仑.

The stand-in only copies substrings out of the OCR text in the request.
It never reads ``truth.json``. Mode ``hallucinate`` deliberately appends text
that is not in the OCR so the grounding filter can be measured.
"""
from __future__ import annotations

import base64
import io
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

from rules_plus import ORG, SECRET, TITLE_END

NUMBER = re.compile(r"[\u4e00-\u9fffA-Za-z]{1,20}[〔\[【(]\s*\d{4}\s*[〕\]】)]\s*第?\s*\d{1,8}\s*号")
DATE = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|[〇零○ＯO一二三四五六七八九]{4}年[一二三四五六七八九十]{1,3}月[一二三四五六七八九十]{1,3}日")


def _text_of(body: dict) -> tuple[str, int]:
    messages = body.get("messages") or []
    chunks = []
    images = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    chunks.append(part.get("text") or "")
                elif part.get("type") == "image_url":
                    images += 1
    return "\n".join(chunks), images


def _ocr_material(blob: str) -> str:
    """Pull the OCR material out of the user JSON. The system prompt is not OCR text."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(blob):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(blob[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("材料"), str):
            return obj["材料"]
    return blob


def propose(ocr_text: str, mode: str) -> dict:
    lines = [line.strip() for line in ocr_text.splitlines() if line.strip() and not line.startswith("---")]
    number = ""
    matched = NUMBER.search(ocr_text)
    if matched and matched.group(0) in ocr_text:
        number = matched.group(0)
    title = ""
    for line in lines:
        compact = re.sub(r"\s+", "", line)
        if "关于" in compact and TITLE_END.search(compact) and compact in ocr_text:
            title = compact
            break
    if not title:
        for line in lines:
            compact = re.sub(r"\s+", "", line)
            if TITLE_END.search(compact) and 4 <= len(compact) <= 40 and compact in ocr_text and not compact.endswith("文件"):
                title = compact
                break
    org = ""
    for line in reversed(lines):
        compact = re.sub(r"\s+", "", line)
        if ORG.fullmatch(compact) and compact in ocr_text:
            org = compact
            break
    if not org:
        for line in lines:
            compact = re.sub(r"\s+", "", line)
            header = re.fullmatch(r"(.{2,40})文件", compact)
            if header and header.group(1) in ocr_text:
                org = header.group(1)
                break
    date = ""
    dates = [item.group(0) for item in DATE.finditer(ocr_text)]
    if dates:
        date = dates[-1]
    secret = ""
    for line in lines[:6]:
        compact = re.sub(r"\s+", "", line).replace("*", "★")
        found = SECRET.search(compact)
        if found and found.group(1) in ocr_text and compact.startswith(found.group(1)):
            secret = found.group(1)
            break
    values = {"题名": title, "责任者": org, "文件日期": date, "文号": number, "密级": secret}
    if mode == "hallucinate":
        values["题名"] = (title or "题名") + "（补写）"
        values["文件日期"] = "1999年1月1日"
    return values


class _Server(ThreadingHTTPServer):
    def __init__(self, server_address, handler, mode: str, expect_key: str):
        super().__init__(server_address, handler)
        self.mode = mode
        self.expect_key = expect_key
        self.stats = {
            "requests": 0,
            "image_parts": 0,
            "requests_with_image": 0,
            "auth_ok": 0,
            "auth_missing": 0,
            "unauthorized": 0,
            "images_decoded": 0,
            "image_decode_errors": 0,
        }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        server: _Server = self.server  # type: ignore[assignment]
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        path = self.path.split("?", 1)[0].rstrip("/")
        if path not in {"/v1/chat/completions", "/chat/completions"}:
            self._send(404, {"error": "not found"})
            return
        header = self.headers.get("Authorization", "")
        if server.expect_key:
            if header == "Bearer " + server.expect_key:
                server.stats["auth_ok"] += 1
            else:
                server.stats["unauthorized"] += 1
                if not header:
                    server.stats["auth_missing"] += 1
                self._send(401, {"error": "unauthorized"})
                return
        elif header:
            server.stats["auth_ok"] += 1
        else:
            server.stats["auth_missing"] += 1
        body = json.loads(raw.decode())
        blob, images = _text_of(body)
        server.stats["requests"] += 1
        server.stats["image_parts"] += images
        if images:
            server.stats["requests_with_image"] += 1
        _decode_images(body, server)
        ocr = _ocr_material(blob)
        values = propose(ocr, server.mode)
        payload = {"choices": [{"message": {"role": "assistant", "content": json.dumps(values, ensure_ascii=False)}}]}
        self._send(200, payload)

    def _send(self, status: int, payload: dict):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _decode_images(body: dict, server: _Server) -> None:
    for message in body.get("messages") or []:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            url = (part.get("image_url") or {}).get("url") or ""
            if "," not in url:
                server.stats["image_decode_errors"] += 1
                continue
            try:
                Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).verify()
                server.stats["images_decoded"] += 1
            except Exception:
                server.stats["image_decode_errors"] += 1


def start(mode: str = "grounded", expect_key: str = "", host: str = "127.0.0.1", port: int = 0) -> tuple[_Server, str]:
    server = _Server((host, port), _Handler, mode, expect_key)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, actual = server.server_address[:2]
    return server, f"http://{host}:{actual}/v1"
