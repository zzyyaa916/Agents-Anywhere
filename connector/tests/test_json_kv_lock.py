import json
import threading

from connector.core.json_kv import JsonKeyValueStore


def test_concurrent_writers_keep_both_keys(tmp_path):
    path = tmp_path / "kv.json"
    first, second = JsonKeyValueStore(path), JsonKeyValueStore(path)
    barrier = threading.Barrier(2)

    def write(store, key, value):
        for index in range(50):
            barrier.wait()
            store.set(key, {"value": f"{value}-{index}"})

    threads = [
        threading.Thread(target=write, args=(first, "first", "a")),
        threading.Thread(target=write, args=(second, "second", "b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    document = json.loads(path.read_text())
    assert document["values"]["first"]["value"] == "a-49"
    assert document["values"]["second"]["value"] == "b-49"
    assert (tmp_path / "kv.json.lock").exists()
