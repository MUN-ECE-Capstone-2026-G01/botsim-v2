import asyncio, json, websockets

async def handler(ws):
    print(f"[broker] Client connected")
    async for msg in ws:
        data = json.loads(msg)
        print(f"[broker] Received: {data}")
        # Echo a state message back
        if data.get("type") == "hello":
            await ws.send(json.dumps({"type": "state", "positions": {}}))
            await asyncio.sleep(5)
            await ws.send(json.dumps({"type": "algorithm", "name": "pentagon"}))

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("Minimal broker listening on :8765")
        await asyncio.Future()

asyncio.run(main())