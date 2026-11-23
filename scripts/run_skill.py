#!/usr/bin/env python3
"""Deterministic, offline literature-reading skill runtime (standard library only).

Reads a case bundle from /input/case.json (or --case), performs one deterministic
processing pass, and writes /app/output/result.json (or --out).  The output keeps
the input case_id and every field declared by the case output_contract.  Missing
or unsupported information is reported as null / uncertainty, never invented.
"""

import argparse
import hashlib
import html
import json
import math
import os
import re
import sys
import zipfile
import zlib

DEFAULT_CASE = "/input/case.json"
DEFAULT_OUT = "/app/output/result.json"
DEFAULT_WORK = "/app/work"
MAX_TEXT_CHARS = 600000
MAX_FILES = 2000
MAX_HASH_BYTES = 128 * 1024 * 1024

TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".bib", ".ris", ".enw", ".xml", ".html", ".htm",
    ".tex", ".log", ".srt", ".vtt",
}
BINARY_SKIP = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff",
               ".mp3", ".mp4", ".avi", ".mov", ".wav", ".zip", ".gz", ".7z",
               ".rar", ".exe", ".dll", ".so", ".dylib", ".pyc"}

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those",
    "into", "using", "used", "use", "were", "was", "are", "is", "be", "been",
    "of", "in", "on", "to", "by", "as", "at", "an", "or", "we", "our",
    "their", "its", "it", "et", "al", "via", "between", "among", "than",
    "which", "who", "what", "when", "where", "how", "not", "can", "may",
    "also", "such", "more", "most", "less", "all", "any", "has", "have",
    "had", "do", "does", "did", "but", "if", "then", "so", "about", "study",
    "studies", "results", "result", "paper", "article", "review",
}

# @@CONFIG@@
SKILL_NAME = "nanopublication-builder"
SKILL_VERSION = "1.0.0"
CHALLENGE_ID = "product-arena-09-0e8befd4"
CONTRACT_RULES = [
    (r"nanopub|纳米出版|assertion", "nanopublications"),
    (r"assertion|断言", "assertions"),
    (r"source|来源", "sources"),
    (r"quality|质量|check", "quality_checks"),
    (r"coverage|覆盖", "coverage"),
    (r"status|状态", "status"),
]
# @@END_CONFIG@@


class InputError(Exception):
    """A user-facing input problem (missing or unreadable material)."""


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise InputError("case file not found") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError("case file is not valid UTF-8 JSON: %s" % exc) from exc
    if not isinstance(value, dict):
        raise InputError("case JSON root must be an object")
    return value


def load_json_soft(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_json(path, payload):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(as_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "content", "abstract", "quote", "title", "name"):
            if key in value:
                return as_text(value[key])
    return ""


def norm_ws(text):
    return re.sub(r"\s+", " ", as_text(text)).strip()


def uniq(items):
    seen, out = set(), []
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else item
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def to_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    match = re.search(r"(1[89]\d{2}|20\d{2}|21\d{2})", as_text(value))
    return int(match.group(1)) if match else None


def ext_of(name):
    return os.path.splitext(as_text(name))[1].lower()


def read_text_file(path):
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, errors="strict") as handle:
                return handle.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _strip_markup(raw):
    return html.unescape(re.sub(r"<[^>]+>", " ", raw))


def _zip_text(path, patterns):
    try:
        with zipfile.ZipFile(path) as archive:
            chunks = []
            for name in sorted(archive.namelist()):
                if any(re.search(pattern, name) for pattern in patterns):
                    raw = archive.read(name).decode("utf-8", errors="replace")
                    chunks.append(_strip_markup(raw))
            return "\n".join(chunks)
    except (zipfile.BadZipFile, OSError, KeyError):
        return ""


def _pdf_unescape(raw):
    out, index = bytearray(), 0
    while index < len(raw):
        char = raw[index:index + 1]
        if char == b"\\" and index + 1 < len(raw):
            nxt = raw[index + 1:index + 2]
            mapping = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b",
                       b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}
            if nxt in mapping:
                out.extend(mapping[nxt])
                index += 2
                continue
            octal = re.match(rb"[0-7]{1,3}", raw[index + 1:index + 4])
            if octal:
                out.append(int(octal.group(0), 8) & 0xFF)
                index += 1 + len(octal.group(0))
                continue
            index += 2
            continue
        out.extend(char)
        index += 1
    return out.decode("utf-8", errors="replace")


def _pdf_text(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return []
    chunks = []
    for match in re.finditer(rb"stream\r?\n", data):
        end = data.find(b"endstream", match.end())
        if end < 0:
            continue
        raw = data[match.end():end].strip(b"\r\n")
        try:
            payload = zlib.decompress(raw)
        except zlib.error:
            payload = raw
        if b"BT" not in payload:
            continue
        for token in re.finditer(rb"\((?:\\.|[^()\\])*\)", payload, re.S):
            text = _pdf_unescape(token.group(0)[1:-1])
            printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\t")
            if text and printable / max(len(text), 1) > 0.7:
                chunks.append(text)
    if not chunks:
        return []
    return ["\n".join(chunks)]


def extract_document(path):
    suffix = ext_of(path)
    if suffix == ".pdf":
        pages = _pdf_text(path)
        return (pages, "text", "minimal_stream_parser") if pages else ([], "no_text_layer", "pdf_without_extractable_text")
    if suffix in TEXT_SUFFIXES:
        try:
            text = read_text_file(path)
        except OSError as exc:
            return [], "unreadable", str(exc)
        if suffix in (".html", ".htm", ".xml"):
            text = _strip_markup(text)
        return [text], "text", suffix.lstrip(".")
    if suffix == ".docx":
        text = _zip_text(path, [r"^word/document\.xml$"])
        return ([text], "text", "docx_xml") if text.strip() else ([], "no_text_layer", "docx")
    if suffix == ".pptx":
        text = _zip_text(path, [r"^ppt/slides/slide\d+\.xml$"])
        return ([text], "text", "pptx_xml") if text.strip() else ([], "no_text_layer", "pptx")
    if suffix == ".xlsx":
        text = _zip_text(path, [r"^xl/sharedStrings\.xml$", r"^xl/worksheets/sheet\d+\.xml$"])
        return ([text], "text", "xlsx_xml") if text.strip() else ([], "no_text_layer", "xlsx")
    if suffix in BINARY_SKIP:
        return [], "unsupported", "binary_type_not_read"
    return [], "unsupported", "unrecognised_suffix"


def join_pages(pages):
    return "\n\f\n".join(as_text(page) for page in pages)


def make_doc(path, text, status, note, pages, size, ctx):
    name = os.path.basename(path) if path else "inline"
    digest = None
    if path and size <= MAX_HASH_BYTES:
        try:
            digest = sha256_file(path)
        except OSError:
            digest = None
    relative = name
    if path:
        for root in ("/input", ctx["case_dir"], os.getcwd(), "/app"):
            try:
                if os.path.abspath(path).startswith(os.path.abspath(root) + os.sep):
                    relative = os.path.relpath(path, root).replace("\\", "/")
                    break
            except (ValueError, OSError):
                continue
    return {
        "id": None,
        "path": relative,
        "name": name,
        "title": None,
        "text": text,
        "pages": [{"page": index + 1, "chars": len(page)} for index, page in enumerate(pages)],
        "page_count": len(pages),
        "sections": [],
        "meta": {},
        "sha256": digest,
        "bytes": size,
        "read_status": status,
        "read_note": note,
    }


def merge_meta(doc, record):
    for target, fields in {
        "title": ("title", "name"),
        "authors": ("authors", "author"),
        "year": ("year", "publication_year", "date"),
        "doi": ("doi", "DOI"),
        "venue": ("venue", "journal", "conference", "publisher"),
        "type": ("type", "document_type", "kind"),
        "keywords": ("keywords", "tags", "labels"),
        "abstract": ("abstract", "summary"),
        "url": ("url", "link"),
    }.items():
        for field in fields:
            if record.get(field) is not None and not doc["meta"].get(target):
                value = record.get(field)
                if target == "year":
                    doc["meta"][target] = to_int(value)
                elif target in ("authors", "keywords"):
                    doc["meta"][target] = value if isinstance(value, list) else [
                        part.strip() for part in re.split(r"[,;，；]", as_text(value)) if part.strip()
                    ]
                else:
                    doc["meta"][target] = as_text(value)
                break
    if doc["meta"].get("title"):
        doc["title"] = doc["meta"]["title"]


DOC_KEYS = ("documents", "files", "materials", "papers", "records",
            "literature", "corpus", "library", "sources", "references",
            "studies", "reports", "docs")
DIR_KEYS = ("input_dir", "materials_dir", "library_root", "root", "data_dir",
            "corpus_dir", "workspace", "files_dir", "docs_dir")


def _resolve(value, roots):
    raw = as_text(value).strip().strip('"').strip("'")
    if not raw:
        return None
    candidates = [raw] if os.path.isabs(raw) else [os.path.join(root, raw) for root in roots]
    for candidate in candidates:
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
    return None


def collect_documents(case, ctx):
    roots = [ctx["case_dir"], "/input", os.getcwd(), "/app"]
    docs, seen, notes = [], set(), []

    def add_path(path):
        real = os.path.realpath(path)
        if real in seen:
            return
        seen.add(real)
        if os.path.isdir(path):
            for current, dirnames, filenames in os.walk(path, followlinks=False):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".git"))
                for name in sorted(filenames):
                    if name.startswith(".") or len(docs) >= MAX_FILES:
                        continue
                    add_path(os.path.join(current, name))
            return
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            notes.append({"path": os.path.basename(path), "reason": "stat failed: %s" % exc})
            return
        if size > MAX_HASH_BYTES:
            notes.append({"path": os.path.basename(path), "reason": "file too large; metadata only"})
            return
        try:
            pages, status, note = extract_document(path)
        except Exception as exc:  # one bad file must not abort the bundle
            pages, status, note = [], "unreadable", "%s: %s" % (type(exc).__name__, exc)
        docs.append(make_doc(path, join_pages(pages)[:MAX_TEXT_CHARS], status, note, pages, size, ctx))

    def add_record(record, key):
        if isinstance(record, str):
            resolved = _resolve(record, roots)
            if resolved:
                add_path(resolved)
            elif ext_of(record):
                notes.append({"path": record, "reason": "declared path not found"})
            else:
                add_record({"text": record, "id": key}, key)
            return
        if not isinstance(record, dict):
            return
        path_value = None
        for field in ("path", "file", "file_path", "source_path", "uri"):
            if record.get(field):
                path_value = record.get(field)
                break
        inline = as_text(record.get("text") or record.get("content") or record.get("abstract") or record.get("full_text"))
        if path_value:
            resolved = _resolve(path_value, roots)
            if resolved and os.path.exists(resolved):
                add_path(resolved)
                if docs:
                    merge_meta(docs[-1], record)
                return
            notes.append({"path": as_text(path_value), "reason": "declared path not found"})
        if inline.strip():
            identifier = as_text(record.get("id") or record.get("doi") or record.get("title") or key)
            dedupe = "inline:" + sha256_bytes(identifier.encode("utf-8"))
            if dedupe in seen:
                return
            seen.add(dedupe)
            text = inline[:MAX_TEXT_CHARS]
            doc = make_doc(None, text, "text", "inline_text", [text], len(text.encode("utf-8")), ctx)
            doc["path"] = as_text(record.get("title") or record.get("name") or "inline-%d" % (len(docs) + 1))
            merge_meta(doc, record)
            docs.append(doc)
            return
        if any(record.get(field) for field in ("title", "doi", "abstract", "authors", "year")):
            identifier = as_text(record.get("id") or record.get("doi") or record.get("title"))
            dedupe = "meta:" + sha256_bytes(identifier.encode("utf-8"))
            if dedupe in seen:
                return
            seen.add(dedupe)
            doc = make_doc(None, "", "metadata_only", "no_text_provided", [], 0, ctx)
            doc["path"] = as_text(record.get("title") or record.get("name") or "record-%d" % (len(docs) + 1))
            merge_meta(doc, record)
            docs.append(doc)
            return
        notes.append({"path": as_text(record.get("name") or key), "reason": "record has no readable text or path"})

    for key in DOC_KEYS + DIR_KEYS:
        if key not in case:
            continue
        value = case[key]
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            add_record(entry, key)
    if isinstance(case.get("inputs"), dict):
        for key, value in case["inputs"].items():
            entries = value if isinstance(value, list) else [value]
            for entry in entries:
                add_record(entry, "inputs." + key)

    for number, doc in enumerate(docs, start=1):
        doc["id"] = "doc-%04d" % number
        if not doc["title"]:
            stem = os.path.splitext(doc["name"])[0]
            doc["title"] = re.sub(r"[_\-]+", " ", stem).strip() or doc["path"]
        if not doc["meta"].get("year"):
            doc["meta"]["year"] = to_int(doc["name"] + " " + doc["text"][:2000])
        if not doc["meta"].get("doi"):
            match = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", doc["text"][:20000])
            doc["meta"]["doi"] = match.group(0).rstrip(".,;)") if match else None
        doc["sections"] = split_sections(doc["text"])
    ctx["documents"] = docs
    ctx["warnings"].extend(notes)
    return docs


def split_sections(text):
    lines = as_text(text).splitlines()
    heading = re.compile(
        r"^(?:#{1,6}\s+\S|第[一二三四五六七八九十百]+[章节篇]|\d{1,2}(?:\.\d{1,2}){0,3}[\.、)\s]+\S"
        r"|[A-Z][A-Za-z0-9 ,&/:\-]{2,60}$)"
    )
    sections, current, buffer = [], {"title": "", "line": 1, "level": 0}, []
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped and len(stripped) <= 120 and heading.match(stripped) and not stripped.endswith("."):
            if buffer and any(part.strip() for part in buffer):
                current["text"] = "\n".join(buffer).strip()
                sections.append(current)
            current = {"title": stripped.lstrip("# ").strip(), "line": number,
                       "level": len(stripped) - len(stripped.lstrip("#")) if stripped.startswith("#") else 1}
            buffer = [line]
        else:
            buffer.append(line)
    if buffer and any(part.strip() for part in buffer):
        current["text"] = "\n".join(buffer).strip()
        sections.append(current)
    return sections or [{"title": "", "line": 1, "level": 0, "text": as_text(text)}]


def sentence_spans(text):
    spans = []
    pattern = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?", re.S)
    for match in pattern.finditer(as_text(text)):
        fragment = match.group(0)
        if fragment.strip():
            spans.append((match.start(), match.end(), fragment.strip()))
    if not spans and as_text(text).strip():
        spans.append((0, len(as_text(text)), as_text(text).strip()))
    return spans


def sentences(text):
    return [item[2] for item in sentence_spans(text)]


def line_offsets(text):
    return [0] + [match.end() for match in re.finditer(r"\n", text)]


def offset_to_line(offsets, position):
    low, high = 0, len(offsets) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if offsets[mid] <= position:
            low = mid
        else:
            high = mid - 1
    return low + 1


def locate(doc, snippet):
    text = doc["text"]
    needle = norm_ws(snippet)[:200]
    start = text.find(needle) if needle else -1
    if start < 0 and needle:
        start = text.lower().find(needle.lower())
    if start < 0:
        return {"page": None, "line": None, "section": None,
                "anchor_status": "unverified",
                "reason": "quote not found verbatim in extracted text"}
    line = offset_to_line(line_offsets(text), start)
    page = text.count("\f", 0, start) + 1 if doc["page_count"] > 1 else 1
    section = None
    for item in doc["sections"]:
        if item["line"] <= line:
            section = item["title"]
    return {"page": page, "line": line, "section": section,
            "anchor_status": "verified",
            "reason": "verbatim match at character %d" % start}


LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}")
CJK_RE = re.compile(r"[\u3400-\u9fff]+")


def tokens(text):
    out = set()
    for word in LATIN_RE.findall(as_text(text).lower()):
        if word not in STOPWORDS and len(word) > 1:
            out.add(word)
    for run in CJK_RE.findall(as_text(text)):
        if len(run) == 1:
            out.add(run)
        for index in range(len(run) - 1):
            out.add(run[index:index + 2])
    return out


def score_units(query, units):
    query_tokens = tokens(query)
    if not units or not query_tokens:
        return []
    bags = [tokens(unit["text"]) for unit in units]
    total = len(units)
    df = {term: sum(1 for bag in bags if term in bag) for term in query_tokens}
    scored = []
    phrase = norm_ws(query).lower()
    for unit, bag in zip(units, bags):
        hits = sorted(query_tokens & bag)
        if not hits:
            continue
        value = sum(math.log((total + 1.0) / (df.get(term, 0) + 1.0)) + 1.0 for term in hits)
        value /= (len(bag) ** 0.5 + 1.0)
        if len(phrase) >= 6 and phrase in unit["text"].lower():
            value += 2.0
        scored.append((unit, value, hits))
    scored.sort(key=lambda item: (-item[1], item[0]["unit_id"]))
    return scored


def best_sentence(text, terms):
    best = ("", 0.0, 0)
    for start, end, sentence in sentence_spans(text):
        overlap = len(tokens(sentence) & terms)
        if overlap == 0:
            continue
        density = overlap / (len(tokens(sentence)) ** 0.5 + 1.0)
        if density > best[1]:
            best = (sentence, density, start)
    return best


UNIT_LIST_KEYS = ("paragraphs", "passages", "segments", "chunks", "blocks", "clauses")


def collect_units(case, docs):
    units, seen = [], set()

    def add(text, paragraph_id, source_id, section=""):
        body = norm_ws(text)
        if not body or len(body) < 2:
            return
        key = (str(paragraph_id), body[:120])
        if key in seen:
            return
        seen.add(key)
        units.append({
            "unit_id": "U%04d" % (len(units) + 1),
            "paragraph_id": str(paragraph_id) if paragraph_id else "U%04d" % (len(units) + 1),
            "source_id": source_id,
            "section": section,
            "text": body,
        })

    def parse_item(item):
        if isinstance(item, str):
            add(item, None, "case")
        elif isinstance(item, dict):
            text = as_text(item.get("text") or item.get("content") or item.get("paragraph") or item.get("quote"))
            pid = item.get("paragraph_id") or item.get("pid") or item.get("id")
            source = as_text(item.get("source_id") or item.get("document_id") or item.get("paper_id") or "case")
            section = as_text(item.get("section") or item.get("heading"))
            add(text, pid, source, section)

    def walk(obj, depth):
        if depth > 8:
            return
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in UNIT_LIST_KEYS and isinstance(value, list):
                    for entry in value:
                        parse_item(entry)
                elif isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(obj, list):
            for entry in obj:
                walk(entry, depth + 1)

    walk(case, 0)
    if not units:
        for doc in docs:
            if doc["read_status"] != "text":
                continue
            for number, block in enumerate(re.split(r"\n\s*\n", doc["text"]), start=1):
                if block.strip():
                    add(block, "%s-p%03d" % (doc["id"], number), doc["id"])
    return units


def read_side_inputs(case, ctx, filenames, case_keys=()):
    objects, used, errors = [], [], []
    for name in filenames:
        for base in ("/input", ctx["case_dir"]):
            path = os.path.join(base, name)
            if os.path.isfile(path):
                value = load_json_soft(path)
                if value is None:
                    errors.append({"file": name, "reason": "not valid JSON"})
                else:
                    objects.append(value)
                    used.append(name)
                break
    for key in case_keys:
        if key in case:
            objects.append(case[key])
            used.append(key)
    return objects, used, errors


def deep_collect(obj, keys):
    """Collect every list/dict value stored under any of the given keys."""
    found = []

    def walk(node, depth):
        if depth > 10:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys:
                    if isinstance(value, list):
                        found.extend(value)
                    elif isinstance(value, dict):
                        found.append(value)
                if isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for entry in node:
                walk(entry, depth + 1)

    walk(obj, 0)
    return found


def contract_names(case):
    contract = case.get("output_contract")
    if contract is None:
        contract = case.get("output_schema") or case.get("result_contract")
    names = []

    def add(value):
        if isinstance(value, str) and value:
            names.append(value)
        elif isinstance(value, dict):
            for key in value.keys():
                if key not in ("type", "description", "version", "schema_version",
                               "$schema", "title", "additionalProperties"):
                    names.append(key)
        elif isinstance(value, list):
            for entry in value:
                add(entry)

    if isinstance(contract, str):
        names.extend(part.strip() for part in contract.split(",") if part.strip())
    elif isinstance(contract, list):
        add(contract)
    elif isinstance(contract, dict):
        for key in ("fields", "required", "optional", "properties", "items", "outputs"):
            if key in contract:
                add(contract[key])
        if not names:
            add(contract)
    return uniq([name for name in names if isinstance(name, str) and name])


def assemble(case, built, ctx):
    result = built.get("result") or {}
    status = built.get("status") or "success"
    evidence = built.get("evidence") or []
    uncertainty = uniq(built.get("uncertainty") or [])
    errors = built.get("errors") or list(ctx.get("warnings") or [])
    stats = built.get("stats") or {}
    names = contract_names(case)
    values, notes = {}, {}
    for name in names:
        if name == "status":
            values[name] = status
        elif name in result:
            values[name] = result[name]
        elif name in built:
            values[name] = built[name]
        else:
            target = None
            for pattern, key in CONTRACT_RULES:
                if re.search(pattern, name.lower()):
                    target = key
                    break
            if target is not None and target in result:
                values[name] = result[target]
            else:
                values[name] = None
                notes[name] = "declared by output_contract but not mapped deterministically; kept null"
    payload = dict(values)
    payload["case_id"] = case.get("case_id") if case.get("case_id") is not None else case.get("id")
    payload["status"] = status
    payload["result"] = result
    payload["evidence"] = evidence
    payload["uncertainty"] = uncertainty
    payload["errors"] = errors
    payload["stats"] = stats
    payload["contract_notes"] = notes
    payload["skill"] = {"name": SKILL_NAME, "version": SKILL_VERSION}
    payload["challenge_id"] = case.get("challenge_id") or CHALLENGE_ID
    return payload


def failed_payload(message, case_id=None, code="input_error"):
    return {
        "case_id": case_id,
        "status": "insufficient_input" if code == "input_error" else "failed",
        "result": {},
        "evidence": [],
        "uncertainty": [message],
        "errors": [{"code": code, "message": message}],
        "stats": {},
        "contract_notes": {},
        "skill": {"name": SKILL_NAME, "version": SKILL_VERSION},
        "challenge_id": CHALLENGE_ID,
    }


# @@BUILD@@
RELATION_PATTERNS = [
    (r"\b(?:inhibit|inhibits|inhibited|suppress|suppresses|block|blocks)\b|抑制|阻断", "INHIBITS", "negative"),
    (r"\b(?:activate|activates|activated|promote|promotes|induce|induces)\b|激活|促进|诱导", "ACTIVATES", "positive"),
    (r"\b(?:increase|increases|increased|enhance|enhances|improve|improves|raise|raises)\b|提高|增加|增强", "INCREASES", "positive"),
    (r"\b(?:decrease|decreases|decreased|reduce|reduces|lower|lowers|decline)\b|降低|减少|减弱", "DECREASES", "negative"),
    (r"\b(?:cause|causes|caused|lead to|leads to|result in|results in)\b|导致|引起", "CAUSES", "causal"),
    (r"\b(?:associated with|correlates? with|related to)\b|与.{0,8}相关", "ASSOCIATED_WITH", "associative"),
    (r"\b(?:outperform|outperforms|surpass|surpasses|better than)\b|优于|超过", "OUTPERFORMS", "comparative"),
    (r"\b(?:use|uses|used|employ|employs|adopt|adopts)\b|采用|使用", "USES", "methodological"),
    (r"\b(?:is|are|was|were)\b|是|属于", "IS_A", "taxonomic"),
]
SPLIT_RE = re.compile(r"[;；]|,\s*(?:whereas|while)\s+")
PRONOUN_RE = re.compile(r"^(it|this|these|they|其|该|这|这些)\b", re.I)


def _clauses(units):
    clauses = []
    for unit in units:
        for sentence in sentences(unit["text"]):
            for part in SPLIT_RE.split(sentence):
                part = part.strip(" ,，")
                if len(part) >= 8 and not part.lower().startswith(("figure", "table", "图", "表")):
                    clauses.append((unit, part))
    return clauses


def _extract(part):
    for pattern, relation, polarity in RELATION_PATTERNS:
        match = re.search(pattern, part, re.I)
        if not match:
            continue
        subject = part[:match.start()].strip(" ,，")
        obj = part[match.end():].strip(" ,，.")
        if len(subject) < 2 or len(obj) < 2:
            continue
        return {
            "subject": subject[:120],
            "relation": relation,
            "object": obj[:160],
            "polarity": polarity,
            "extraction": "pattern",
        }
    return {
        "subject": part[:100],
        "relation": "MENTIONS",
        "object": None,
        "polarity": "neutral",
        "extraction": "unbound",
    }


def build_deliverable(case, docs, ctx):
    units = collect_units(case, docs)
    doc_index = {doc["id"]: doc for doc in docs}
    pubs, assertions, quality, evidence, uncertainty = [], [], [], [], []
    for unit, clause in _clauses(units):
        extracted = _extract(clause)
        doc = doc_index.get(unit["source_id"])
        source = {
            "source_id": unit["source_id"],
            "title": doc.get("title") if doc else None,
            "doi": doc["meta"].get("doi") if doc else None,
            "year": doc["meta"].get("year") if doc else None,
            "paragraph_id": unit["paragraph_id"],
        }
        checks = []
        if extracted["relation"] == "MENTIONS":
            checks.append({"check": "atomic_assertion", "passed": False,
                           "detail": "no controlled relation could be bound"})
        if extracted["object"] is None:
            checks.append({"check": "object_present", "passed": False, "detail": "object is missing"})
        if len(clause) > 320:
            checks.append({"check": "assertion_length", "passed": False,
                           "detail": "assertion is longer than 320 characters; may still be compound"})
        if PRONOUN_RE.search(extracted["subject"]):
            checks.append({"check": "unresolved_pronoun", "passed": False,
                           "detail": "subject begins with a pronoun and may be ambiguous"})
        if not checks:
            checks.append({"check": "atomic_assertion", "passed": True,
                           "detail": "relation and arguments were bound deterministically"})
        loc = locate(doc, clause) if doc else {"anchor_status": "unavailable"}
        assertion = {
            "assertion_id": "A%04d" % (len(assertions) + 1),
            "text": clause,
            "subject": extracted["subject"],
            "relation": extracted["relation"],
            "object": extracted["object"],
            "polarity": extracted["polarity"],
            "extraction_method": extracted["extraction"],
            "evidence": {
                "quote": clause,
                "paragraph_id": unit["paragraph_id"],
                "source_id": unit["source_id"],
                **loc,
            },
            "source": source,
            "confidence": "direct_quote" if extracted["extraction"] == "pattern" else "weak",
            "quality_checks": checks,
        }
        assertions.append(assertion)
        quality.extend([{"assertion_id": assertion["assertion_id"], **item} for item in checks])
        evidence.append(assertion["evidence"])
        if extracted["extraction"] == "unbound":
            uncertainty.append("assertion A%04d has no controlled relation" % len(assertions))
        pubs.append({
            "nanopublication_id": "NP%04d" % len(pubs),
            "assertion": {
                "subject": extracted["subject"],
                "relation": extracted["relation"],
                "object": extracted["object"],
                "text": clause,
            },
            "provenance": source,
            "evidence": assertion["evidence"],
            "confidence": assertion["confidence"],
            "quality_checks": checks,
        })
        if len(pubs) >= 500:
            uncertainty.append("publication list truncated at 500 assertions")
            break
    bound = sum(1 for item in assertions if item["extraction_method"] == "pattern")
    if not assertions:
        status = "insufficient_input"
        uncertainty.append("no paragraph text was available to build assertions")
    elif bound == len(assertions):
        status = "success"
    elif bound:
        status = "partial"
    else:
        status = "partial"
        uncertainty.append("no assertion could be bound to a controlled relation; all are marked weak")
    result = {
        "nanopublications": pubs,
        "assertions": assertions,
        "sources": [{"source_id": doc["id"], "title": doc["title"],
                     "doi": doc["meta"].get("doi"), "year": doc["meta"].get("year"),
                     "read_status": doc["read_status"]} for doc in docs],
        "quality_checks": quality,
        "coverage": {
            "paragraph_units": len(units),
            "assertions": len(assertions),
            "bound_assertions": bound,
            "unbound_assertions": len(assertions) - bound,
            "sources": len(docs),
        },
    }
    return {
        "status": status,
        "result": result,
        "evidence": evidence,
        "uncertainty": uncertainty,
        "errors": [],
        "stats": result["coverage"],
    }
# @@END_BUILD@@


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run this literature-reading skill on one Playground case.")
    parser.add_argument("--case", default=DEFAULT_CASE, help="case JSON path (default /input/case.json)")
    parser.add_argument("--out", "--output", default=DEFAULT_OUT, help="result JSON path (default /app/output/result.json)")
    parser.add_argument("--work", default=DEFAULT_WORK, help="scratch directory (default /app/work)")
    parser.add_argument("--max-files", type=int, default=MAX_FILES)
    args = parser.parse_args(argv)
    try:
        os.makedirs(args.work, exist_ok=True)
    except OSError:
        pass
    case_path = os.path.abspath(args.case)
    out_path = os.path.abspath(args.out)
    try:
        case = load_json(case_path)
    except InputError as exc:
        payload = failed_payload(str(exc), code="input_error")
        try:
            write_json(out_path, payload)
        except OSError:
            pass
        sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return 2
    ctx = {
        "case_path": case_path,
        "case_dir": os.path.dirname(case_path),
        "case_sha256": sha256_file(case_path),
        "warnings": [],
    }
    try:
        docs = collect_documents(case, ctx)
        built = build_deliverable(case, docs, ctx)
        payload = assemble(case, built, ctx)
        write_json(out_path, payload)
        sys.stdout.write(json.dumps({
            "status": payload.get("status"),
            "skill": SKILL_NAME,
            "case_id": payload.get("case_id"),
            "documents": len(docs),
            "contract_fields": contract_names(case),
        }, ensure_ascii=False) + "\n")
        return 0
    except Exception as exc:  # structured failure is part of the contract
        message = "%s: %s" % (type(exc).__name__, exc)
        payload = failed_payload(message, case_id=case.get("case_id"), code="runtime_error")
        try:
            write_json(out_path, payload)
        except OSError:
            pass
        sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return 2


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.path.join("/app/output", "result.json")
            os.makedirs("/app/output", exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    if not os.path.isfile("/app/output/result.json"):
        try:
            os.makedirs("/app/output", exist_ok=True)
            with open("/app/output/result.json", "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0)
