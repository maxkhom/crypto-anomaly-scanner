"""Print five public trade messages, then close the diagnostic connection."""
import asyncio
import json
import time

from websockets.asyncio.client import connect

URL = 'wss://fapi.bitunix.com/public/'


async def check():
    async with asyncio.timeout(45):
        async with connect(URL, open_timeout=10, close_timeout=3, ping_interval=None) as socket:
            print('Соединение установлено.', flush=True)
            await socket.send(json.dumps({'op':'subscribe','args':[{'symbol':'BTCUSDT','ch':'trade'}]}))
            print('Подписка BTCUSDT отправлена. Ожидаем 5 сообщений со сделками…', flush=True)
            next_ping = time.monotonic()
            count = 0
            while count < 5:
                if time.monotonic() >= next_ping:
                    await socket.send(json.dumps({'op':'ping','ping':int(time.time())}))
                    next_ping = time.monotonic() + 15
                try:
                    message = await asyncio.wait_for(socket.recv(), timeout=max(0.1, next_ping-time.monotonic()))
                except TimeoutError:
                    continue
                payload = json.loads(message)
                print(json.dumps(payload, ensure_ascii=False), flush=True)
                if isinstance(payload, dict) and payload.get('ch') == 'trade' and payload.get('symbol') == 'BTCUSDT' and payload.get('data'):
                    count += 1
            print('Проверка завершена: получено 5 сообщений со сделками.', flush=True)


if __name__ == '__main__':
    try:
        asyncio.run(check())
    except TimeoutError:
        print('Время проверки истекло: не удалось получить 5 сообщений за 45 секунд.', flush=True)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print('Проверка остановлена.')
