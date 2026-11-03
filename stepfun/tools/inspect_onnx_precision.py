"""Read serialized ONNX initializer types; never execute or modify a model.

Uses the standard protobuf wire format and the pinned ONNX schema fields:
https://github.com/onnx/onnx/blob/v1.18.0/onnx/onnx.proto3
This small inspector is not a complete ONNX semantic validator.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "751bff37182d3f1213fa05d7196b954e230abad9"
MODEL_ROOT = ROOT / "public" / "models" / REVISION / "Xenova/all-MiniLM-L6-v2/onnx"
TYPES = {1: "FLOAT32", 2: "UINT8", 3: "INT8", 6: "INT32", 7: "INT64", 9: "BOOL", 10: "FLOAT16", 11: "FLOAT64", 16: "BFLOAT16"}


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("Truncated varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError("Invalid oversized varint")


def fields(data):
    offset = 0
    while offset < len(data):
        tag, offset = varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError("Invalid protobuf field zero")
        if wire == 0:
            value, offset = varint(data, offset)
        else:
            if wire == 2:
                size, offset = varint(data, offset)
            elif wire in (1, 5):
                size = 8 if wire == 1 else 4
            else:
                raise ValueError(f"Unsupported protobuf wire type {wire}")
            end = offset + size
            if end > len(data):
                raise ValueError("Truncated protobuf payload")
            value = data[offset:end]
            offset = end
        yield number, wire, value


def inspect(path):
    raw = path.read_bytes()
    graphs = [value for number, wire, value in fields(memoryview(raw)) if number == 7 and wire == 2]
    if len(graphs) != 1:
        raise ValueError("Expected one top-level ModelProto graph")
    counts, elements, raw_bytes, operators = Counter(), Counter(), Counter(), Counter()
    external = 0
    for number, wire, payload in fields(graphs[0]):
        if wire != 2:
            continue
        if number == 1:
            names = [bytes(value).decode("utf8") for field, kind, value in fields(payload) if field == 4 and kind == 2]
            if len(names) != 1:
                raise ValueError("Expected one NodeProto op_type")
            operators[names[0]] += 1
        elif number == 5:
            dtype, dims, size = None, [], 0
            for field, kind, value in fields(payload):
                if field == 2 and kind == 0:
                    dtype = value
                elif field == 1:
                    if kind == 0:
                        dims.append(value)
                    elif kind == 2:
                        at = 0
                        while at < len(value):
                            dim, at = varint(value, at)
                            dims.append(dim)
                elif field == 9 and kind == 2:
                    size += len(value)
                elif field == 14 and kind == 0 and value == 1:
                    external += 1
            if dtype is None or any(dim >= 2**63 for dim in dims):
                raise ValueError("Invalid initializer type or negative dimension")
            name = TYPES.get(dtype, f"TYPE_{dtype}")
            counts[name] += 1
            elements[name] += math.prod(dims)
            raw_bytes[name] += size
    return {"file": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "initializerCounts": dict(counts), "initializerElementCounts": dict(elements),
            "initializerRawDataBytes": dict(raw_bytes), "externalInitializers": external,
            "topLevelOperators": dict(operators)}


if __name__ == "__main__":
    report = {"recordedAt": datetime.now(timezone.utc).isoformat(),
              "schema": "https://github.com/onnx/onnx/blob/v1.18.0/onnx/onnx.proto3",
              "scope": "Serialized top-level initializer types/operators only; not runtime kernel precision, model inference, or retrieval quality",
              "modelRevision": REVISION,
              "models": [inspect(MODEL_ROOT / name) for name in ("model.onnx", "model_fp16.onnx", "model_quantized.onnx")]}
    output = ROOT / "evidence/model-precision/GRAPH_TYPES.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"output": str(output), "types": [{"file": item["file"], "counts": item["initializerCounts"]} for item in report["models"]]}))
