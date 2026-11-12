from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from myzing.factory.network import Network


def test_parallel_requests_keep_every_ledger_row(tmp_path):
    (tmp_path / "factory.json").write_text('{"offline": false}', encoding="utf-8")
    net = Network(tmp_path)

    def one(i):
        with net.request(f"https://host{i % 7}.example/x", "parallel scoring") as row:
            row["size"] = 1000 + i

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(one, range(400)))
    rows = [json.loads(line) for line in (tmp_path / "network.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 400                         # concurrent appends must not overwrite each other
    assert sorted(r["bytes"] for r in rows) == [1000 + i for i in range(400)]
