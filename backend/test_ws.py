import asyncio
import websockets

async def test():
    async with websockets.connect('ws://localhost:9000/api/v1/chat/ws') as websocket:
        await websocket.send('hello')
        print(await websocket.recv())

asyncio.run(test())
