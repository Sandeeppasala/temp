"""One paced MP3 encoder per language, broadcasting encoded bytes to listeners.

Live policy: preserve FIFO while queued PCM <= MAX_PCM_SECONDS. On overflow,
drop the oldest *not-yet-played* speech and log the loss explicitly.
"""
import asyncio
import logging
import os
import time
from collections import deque

log = logging.getLogger("shared-mp3")
RATE = 16000
SLICE_MS = 100
SLICE_BYTES = RATE * 2 * SLICE_MS // 1000
MAX_PCM_SECONDS = float(os.getenv("STREAM_MAX_PCM_BACKLOG_S", "20"))
MAX_PCM_BYTES = int(MAX_PCM_SECONDS * RATE * 2)
STREAM_MODE = os.getenv("STREAM_DELIVERY_MODE", "burst").strip().lower()
if STREAM_MODE not in ("burst", "paced"):
    raise ValueError("STREAM_DELIVERY_MODE must be burst or paced")
MAX_CLIENT_CHUNKS = 256 if STREAM_MODE == "burst" else 32

class SharedMP3:
    def __init__(self, language):
        self.language = language
        self.clients = set()
        self.pcm = deque()
        self.pcm_bytes = 0
        self.dropped_seconds = 0.0
        self.proc = None
        self.tasks = []
        self.lock = asyncio.Lock()
        self.running = False
        self.last_encoded_at = 0.0
        self.wakeup = asyncio.Event()
        self.silence_seconds = 0.0

    async def start(self):
        async with self.lock:
            if self.running:
                return
            self.proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", "pipe:0",
                "-codec:a", "libmp3lame", "-b:a", "48k",
                "-write_xing", "0", "-f", "mp3", "-flush_packets", "1", "pipe:1",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            self.running = True
            self.tasks = [asyncio.create_task((self._feed_burst() if STREAM_MODE == "burst" else self._feed()), name="mp3-feed-"+self.language),
                          asyncio.create_task(self._broadcast(), name="mp3-read-"+self.language)]

    def enqueue(self, pcm):
        if not self.clients or not pcm:
            return
        self.pcm.append(memoryview(pcm))
        self.pcm_bytes += len(pcm)
        self.wakeup.set()
        # Explicit live catch-up policy; never silently discard speech.
        while self.pcm_bytes > MAX_PCM_BYTES and self.pcm:
            old = self.pcm.popleft()
            self.pcm_bytes -= len(old)
            self.dropped_seconds += len(old) / (RATE * 2)
            log.warning("%s live audio backlog exceeded %.1fs; discarded %.2fs of old audio (total %.1fs)",
                        self.language, MAX_PCM_SECONDS, len(old)/(RATE*2), self.dropped_seconds)

    async def subscribe(self):
        await self.start()
        q = asyncio.Queue(maxsize=MAX_CLIENT_CHUNKS)
        self.clients.add(q)
        return q

    def unsubscribe(self, q):
        self.clients.discard(q)

    async def _feed_burst(self):
        """Deliver queued speech immediately; send quiet keepalive on idle."""
        silence = bytes(RATE * 2 // 4)
        try:
            while self.running:
                if not self.pcm:
                    self.wakeup.clear()
                    try:
                        await asyncio.wait_for(self.wakeup.wait(), timeout=0.25)
                    except asyncio.TimeoutError:
                        if not self.pcm:
                            self.proc.stdin.write(silence)
                            await self.proc.stdin.drain()
                            self.silence_seconds += 0.25
                    continue
                head = self.pcm.popleft()
                self.pcm_bytes -= len(head)
                self.proc.stdin.write(head)
                await self.proc.stdin.drain()
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s burst MP3 feeder failed", self.language)
            self.running = False

    async def _feed(self):
        deadline = time.monotonic()
        silence = bytes(SLICE_BYTES)
        try:
            while self.running:
                now = time.monotonic()
                if now < deadline:
                    await asyncio.sleep(deadline - now)
                else:
                    # Do not attempt to catch up by bursting old PCM.
                    deadline = now
                remaining = SLICE_BYTES
                chunks = []
                while remaining and self.pcm:
                    head = self.pcm[0]
                    n = min(len(head), remaining)
                    chunks.append(head[:n])
                    self.pcm_bytes -= n
                    remaining -= n
                    if n == len(head):
                        self.pcm.popleft()
                    else:
                        self.pcm[0] = head[n:]
                if remaining:
                    chunks.append(memoryview(silence)[:remaining])
                self.proc.stdin.write(b"".join(chunks))
                await self.proc.stdin.drain()
                deadline += SLICE_MS / 1000
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s shared MP3 feeder failed", self.language)
            self.running = False

    async def _broadcast(self):
        try:
            while self.running:
                chunk = await self.proc.stdout.read(2048)
                if not chunk:
                    break
                self.last_encoded_at = time.monotonic()
                for q in tuple(self.clients):
                    try:
                        q.put_nowait(chunk)
                    except asyncio.QueueFull:
                        self.clients.discard(q)
                        log.warning("%s slow listener disconnected: encoded MP3 queue full", self.language)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s shared MP3 broadcaster failed", self.language)
        finally:
            self.running = False

    def stats(self):
        return {"listeners":len(self.clients), "pcm_backlog_s":round(self.pcm_bytes/(RATE*2),2),
                "dropped_audio_s":round(self.dropped_seconds,2),
                "encoder_running":self.running, "delivery_mode":STREAM_MODE,
                "burst_silence_s":round(self.silence_seconds,2),
                "last_encoded_age_s":round(time.monotonic()-self.last_encoded_at,2) if self.last_encoded_at else None}

    async def close(self):
        self.running = False
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        if self.proc:
            if self.proc.returncode is None:
                self.proc.kill()
            await self.proc.wait()
            self.proc = None
        self.clients.clear()
        self.pcm.clear()
        self.pcm_bytes = 0
