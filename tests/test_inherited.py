import hashlib
import json
from pathlib import Path


def test_inherited_code_is_unchanged():
    root = Path(__file__).resolve().parents[1]
    for name, expected in json.loads((Path(__file__).with_name("inherited.json")).read_text()).items():
        content = (root / name).read_bytes()
        if b"\0" not in content:
            content = content.replace(b"\r\n", b"\n")
        assert hashlib.sha256(content).hexdigest() == expected, name
