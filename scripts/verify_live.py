"""One-shot live verification of a running Sentinel server (port 8100)."""
import asyncio
import json
import urllib.request

import websockets

BASE = "http://127.0.0.1:8100"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


async def main():
    # 1) wait for health
    for _ in range(40):
        try:
            status, body = get("/api/health")
            if status == 200:
                print(f"[health] {body}")
                break
        except Exception:
            await asyncio.sleep(0.25)
    else:
        print("server never came up"); return

    # 2) static assets
    for path in ("/", "/static/app.js", "/static/styles.css"):
        with urllib.request.urlopen(BASE + path, timeout=5) as r:
            print(f"[static] {path} -> {r.status} ({r.headers.get('content-type')})")

    # 3) stream over the websocket for a few seconds
    updates = 0
    anomalies = []
    methods = set()
    last = None
    async with websockets.connect("ws://127.0.0.1:8100/ws", max_size=None) as ws:
        first = json.loads(await ws.recv())
        print(f"[ws] first frame type={first['type']} "
              f"history={len(first.get('history', []))} alerts={len(first.get('alerts', []))}")
        try:
            while updates < 400:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
                if msg.get("type") != "update":
                    continue
                updates += 1
                last = msg["result"]
                for a in last["anomalies"]:
                    anomalies.append(a)
                    methods.add(a["method"])
        except asyncio.TimeoutError:
            pass

    print(f"[ws] received {updates} updates")
    print(f"[ws] anomalies seen: {len(anomalies)} | detection methods exercised: {sorted(methods)}")
    if last:
        ev = last["event"]
        print(f"[sample event] lat={ev['latency_ms']}ms err={ev['error_rate']} "
              f"rps={ev['traffic_rps']} endpoint={ev['endpoint']}")
        print(f"[sample stats] " + ", ".join(
            f"{s['name']}: p99={s['p99']} z={s['zscore']}" for s in last["stats"]))
        print(f"[sample] isolation_score={last['isolation_score']} "
              f"unique_total={last['cardinality']['unique_total']} "
              f"top_endpoint={last['top_endpoints'][0]['key'] if last['top_endpoints'] else None}")
    for a in anomalies[:6]:
        print(f"   ! [{a['severity']}/{a['method']}] {a['message']}")

    status, snap = get("/api/state")
    print(f"[state] events={snap['snapshot']['events_processed']} "
          f"anomalies={snap['snapshot']['anomalies_total']} bus={snap['config']['bus']}")
    status, hist = get("/api/history?limit=10")
    print(f"[history] {len(hist)} points (last latency={hist[-1]['latency_ms'] if hist else 'NA'})")


asyncio.run(main())
