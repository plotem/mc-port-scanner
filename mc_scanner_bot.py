import asyncio
import json
import os
import struct
import time

import discord
from discord.ext import commands


BOT_TOKEN = os.environ.get("DISCORD_TOKEN", "")

# tcp values for port scanning
TCP_WORKERS = 200        # concurrent connection attempts (lower if ports get missed)
TCP_TIMEOUT = 1.5        # must be well above real round-trip time to avoid false timeout
TCP_RETRIES = 2          # retries only happen on timeouts, not on refused ports

# minecraft values for determining if open ports are mc servers or not
MC_WORKERS = 50          #at most 50 ports should be checked for minecraft at once
MC_TIMEOUT = 3.0         # total time allowed for handshake + status reply
MC_RETRIES = 2
MC_PROTOCOL = 777        # protocol number sent in the handshake

# limits so we don't break stuff
MAX_PORTS = 50000
PROGRESS_INTERVAL = 5.0


#standard discord bot setup
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=("!", "/"), intents=intents)

scan_running = False
stop_requested = False


async def send_message(ctx, message):
    message = str(message)
    #simple message splitter to bypass 2000 character limit
    #stops messages not being sent or being cut off
    while len(message) > 2000:
        split_at = message.rfind("\n", 0, 2000)
        if split_at <= 0:
            split_at = 2000
        await ctx.send(message[:split_at])
        message = message[split_at:].lstrip("\n")

    if message:
        await ctx.send(message)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    #just confirm that the bot is working
    #not seen on discord

@bot.event
async def on_command_error(ctx, error):
    #error handling for misusage with arguments
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await send_message(ctx, f"Missing argument: `{error.param.name}`")
        return

    if isinstance(error, commands.BadArgument):
        await send_message(
            ctx,
            "Invalid arguments.\n\n"
            "`!test <host> <port>`\n"
            "`!work <start> <end> <host>`",
        )
        return

    print(f"Command error: {error!r}")
    await send_message(ctx, f"Error: `{error}`")


#just a helper command to help users get started
@bot.command()
async def start(ctx):
    await send_message(
        ctx,
        "Scanner online.\n\n"
        "`!test <host> <port>`\n"
        "`!work <start> <end> <host>`\n"
        "`!stop`",
    )

#check if an individual por + ip combo is an mc server
@bot.command()
async def test(ctx, host: str = None, port: int = None):
    #more error handling
    if host is None or port is None:
        await send_message(ctx, "Usage: `!test <host> <port>`")
        return

    if not 1 <= port <= 65535:
        await send_message(ctx, "Port must be between 1 and 65535.")
        return

    await send_message(ctx, f"Testing `{host}:{port}`...")

    started = time.monotonic()
    result = await check_minecraft_with_retries(host, port)
    elapsed = time.monotonic() - started

    if result is None:
        await send_message(
            ctx,
            f"No Minecraft server detected at `{host}:{port}`.\n"
            f"Time: `{elapsed:.2f}s`",
        )
        return
    #message thats sent to discord channel to alert of found mc servers
    await send_message(
        ctx,
        "Minecraft server detected!\n\n"
        f"Address: `{host}:{port}`\n"
        f"Players: `{result['players_online']}/{result['players_max']}`\n"
        f"Version: `{result['version']}`\n"
        f"Protocol: `{result['protocol']}`\n"
        f"Time: `{elapsed:.2f}s`",
    )

#work is similar to test but over a larger range of ports
@bot.command()
async def work(ctx, start_port: int = None, end_port: int = None, host: str = None):
    global scan_running, stop_requested #yucky global but im lazy and its more readable

    if start_port is None or end_port is None or host is None:
        await send_message(ctx, "Usage: `!work <start> <end> <host>`")
        return

    if not 1 <= start_port <= 65535:
        await send_message(ctx, "Invalid start port.")
        return

    if not 1 <= end_port <= 65535:
        await send_message(ctx, "Invalid end port.")
        return

    if end_port < start_port:
        await send_message(ctx, "End port must be greater than or equal to start port.")
        return
    #check user isn't trying to scan too many ports which could be flagged as a DOS
    total_ports = end_port - start_port + 1
    if total_ports > MAX_PORTS:
        await send_message(
            ctx,
            f"Too many ports.\nRequested: `{total_ports:,}`\nMaximum: `{MAX_PORTS:,}`",
        )
        return

    if scan_running:
        await send_message(ctx, "A scan is already running.")
        return

    scan_running = True
    stop_requested = False

    try:
        await run_scan(ctx, host, start_port, end_port)
    except Exception as e:
        print(f"Scan error: {e!r}")
        await send_message(ctx, f"Scan error: `{e}`")
    finally:
        scan_running = False
        stop_requested = False

#allow for premature terminationi of scan
@bot.command()
async def stop(ctx):
    global stop_requested

    if not scan_running:
        await send_message(ctx, "No scan is currently running.")
        return

    stop_requested = True
    await send_message(ctx, "Stopping scan...")


async def run_pool(items, worker_fn, concurrency, state, on_result=None):

    #running through queue updating state to done when finsihed
    #with concurrent workers but stop if stop flag is raised
    #when a worker has finished it is assigned to anotoher port
    queue = asyncio.Queue()
    for item in items:
        queue.put_nowait(item)

    results = []

    async def worker():
        while not stop_requested:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            try:
                result = await worker_fn(item)
            except Exception as e:
                print(f"Worker error on {item}: {e!r}")
                result = None

            state["done"] += 1
            results.append((item, result))

            if on_result is not None:
                await on_result(item, result)
    #assigning "workers" to each job
    n = max(1, min(concurrency, len(items)))
    workers = [asyncio.create_task(worker()) for _ in range(n)]
    await asyncio.gather(*workers)
    return results


async def progress_reporter(ctx, label, state, total, found_label, unit):
    #sends progress update to the channel w frequency depending on
    #PROGRESS_INTERVAL
    started = time.monotonic()
    try:
        while True:
            await asyncio.sleep(PROGRESS_INTERVAL)
            elapsed = time.monotonic() - started
            speed = state["done"] / elapsed if elapsed > 0 else 0
            pct = state["done"] / total * 100 if total else 100
            await send_message(
                ctx,
                f"{label}\n"
                f"Progress: `{pct:.1f}%`\n"
                f"Checked: `{state['done']:,}/{total:,}`\n"
                f"Speed: `{speed:,.0f} {unit}`\n"
                f"{found_label}: `{state['found']}`",
            )
    except asyncio.CancelledError:
        pass


async def run_scan(ctx, host, start_port, end_port):
    total_ports = end_port - start_port + 1
    overall_started = time.monotonic()

    await send_message(
        ctx,
        f"Starting scan:\n"
        f"`{host}:{start_port}-{end_port}`\n\n"
        f"Ports: `{total_ports:,}`\n"
        f"TCP workers: `{TCP_WORKERS}` (timeout `{TCP_TIMEOUT}s`, retries `{TCP_RETRIES}`)\n"
        f"Minecraft workers: `{MC_WORKERS}`\n\n"
        f"Phase 1: TCP port scan",
    )

    # tcp phase / port scanning

    tcp_started = time.monotonic()
    tcp_state = {"done": 0, "found": 0}
    open_ports = []

    async def tcp_worker(port):
        return await check_port(host, port)

    async def tcp_on_result(port, is_open):
        if is_open:
            open_ports.append(port)
            tcp_state["found"] += 1
            print(f"OPEN {host}:{port}")

    reporter = asyncio.create_task(
        progress_reporter(
            ctx, "Phase 1: TCP scan", tcp_state, total_ports,
            "Open ports", "ports/sec",
        )
    )
    try:
        await run_pool(
            range(start_port, end_port + 1),
            tcp_worker,
            TCP_WORKERS,
            tcp_state,
            tcp_on_result,
        )
    finally:
        reporter.cancel()

    if stop_requested:
        await send_message(ctx, "Scan stopped during TCP phase.")
        return

    open_ports.sort()
    tcp_elapsed = time.monotonic() - tcp_started
    tcp_speed = tcp_state["done"] / tcp_elapsed if tcp_elapsed > 0 else 0

    await send_message(
        ctx,
        f"TCP scan complete!\n\n"
        f"Checked: `{tcp_state['done']:,}`\n"
        f"Open ports: `{len(open_ports)}`"
        + (f" (`{', '.join(map(str, open_ports[:30]))}"
           f"{'...' if len(open_ports) > 30 else ''}`)" if open_ports else "")
        + f"\nTime: `{tcp_elapsed:.2f}s`\n"
        f"Speed: `{tcp_speed:,.0f} ports/sec`",
    )

    if not open_ports:
        await send_message(ctx, "No open TCP ports found.")
        return

    # checking open ports to see if they are running minecraft servers

    await send_message(ctx, "Starting Minecraft detection...")

    mc_started = time.monotonic()
    mc_state = {"done": 0, "found": 0}
    servers = []

    async def mc_worker(port):
        return await check_minecraft_with_retries(host, port)

    async def mc_on_result(port, result):
        if result is None:
            return
        servers.append(result)
        mc_state["found"] += 1
        print(f"MINECRAFT SERVER FOUND YAY {host}:{port}")
        await send_message(
            ctx,
            f"Minecraft server found!\n"
            f"`{host}:{port}` | {result['players_online']}/{result['players_max']} | "
            f"{result['version']} | Protocol {result['protocol']}",
        )

    reporter = asyncio.create_task(
        progress_reporter(
            ctx, "Phase 2: Minecraft detection", mc_state, len(open_ports),
            "Servers found", "checks/sec",
        )
    )
    try:
        await run_pool(open_ports, mc_worker, MC_WORKERS, mc_state, mc_on_result)
    finally:
        reporter.cancel()

    if stop_requested:
        await send_message(ctx, "Scan stopped during Minecraft detection.")
        return

    # final report

    mc_elapsed = time.monotonic() - mc_started
    overall_elapsed = time.monotonic() - overall_started

    servers.sort(key=lambda s: s["players_online"], reverse=True)

    report = (
        "Scan complete!\n\n"
        f"Host: `{host}`\n"
        f"Ports checked: `{tcp_state['done']:,}`\n"
        f"Open ports: `{len(open_ports)}`\n"
        f"Minecraft checks: `{mc_state['done']}`\n"
        f"Minecraft servers: `{len(servers)}`\n\n"
        f"TCP time: `{tcp_elapsed:.2f}s`\n"
        f"Minecraft time: `{mc_elapsed:.2f}s`\n"
        f"Total time: `{overall_elapsed:.2f}s`"
    )

    if servers:
        report += "\n\nMinecraft servers:\n\n"
        for i, s in enumerate(servers, 1):
            report += (
                f"{i}. `{host}:{s['port']}` | "
                f"{s['players_online']}/{s['players_max']} | "
                f"{s['version']} | Protocol {s['protocol']}\n"
            )
    else:
        report += "\n\nNo Minecraft servers were identified."

    await send_message(ctx, report)


#async tcp check

async def check_port(host, port):
    for _ in range(TCP_RETRIES):
        writer = None
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), TCP_TIMEOUT
            ) # try to establish connection for time determined in
            #TCP_TIMEOUT
            return True
        except asyncio.TimeoutError:
            # Could be a dropped packet or a filtered port: retry.
            continue
        except ConnectionRefusedError:
            # Definitely closed. No point retrying.
            return False
        except OSError:
            # Unreachable, reset, etc. Retry once more in case it's transient.
            continue
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
    return False


#async mc checker

async def check_minecraft_with_retries(host, port):
    for attempt in range(MC_RETRIES):
        if attempt > 0:
            await asyncio.sleep(0.15)
        result = await check_minecraft_server(host, port)
        if result is not None:
            return result
    return None


async def check_minecraft_server(host, port):
    try:
        return await asyncio.wait_for(_mc_status(host, port), MC_TIMEOUT)
    except asyncio.TimeoutError:
        return None
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError,
            asyncio.IncompleteReadError):
        return None
    except Exception as e:
        print(f"Unexpected MC error {host}:{port}: {e!r}")
        return None


async def _mc_status(host, port):
    reader, writer = await asyncio.open_connection(host, port)
    try:
        host_bytes = host.encode("utf-8")

        # handshake (packet id 0, next state = 1 / status)
        #packet id, protocol version, serverhostname, port, nextstate
        handshake = (
            encode_varint(0) #because mc doesn't use 4 byte ints but VarInt
            + encode_varint(MC_PROTOCOL)
            + encode_varint(len(host_bytes))
            + host_bytes
            + struct.pack(">H", port) # > big endian H unsigned 16 bit
            + encode_varint(1)
        )
        writer.write(encode_varint(len(handshake)) + handshake)

        # status request (packet id 0, empty)
        status_request = encode_varint(0) #minecraft status request packet
        writer.write(encode_varint(len(status_request)) + status_request)
        await writer.drain()

        # response
        packet_length = await read_varint(reader)
        if packet_length <= 0 or packet_length > 2_000_000:
            return None

        packet = await reader.readexactly(packet_length)

        packet_id, offset = decode_varint_bytes(packet, 0)
        if packet_id != 0:
            return None

        json_length, offset = decode_varint_bytes(packet, offset)
        if json_length < 0 or offset + json_length > len(packet):
            return None

        data = json.loads(packet[offset:offset + json_length].decode("utf-8")) # convert json block to text
        if not isinstance(data, dict):
            return None

        if "version" not in data and "players" not in data:
            return None

        players = data.get("players", {})
        if not isinstance(players, dict):
            players = {}

        version = data.get("version", {})
        if isinstance(version, dict):
            version_name = version.get("name", "Unknown")
            protocol = version.get("protocol", "Unknown")
        else:
            version_name = str(version)
            protocol = "Unknown"

        return {
            "port": port,
            "players_online": players.get("online", 0),
            "players_max": players.get("max", 0),
            "version": version_name,
            "protocol": protocol,
        }
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


#encode / decode helpers

def encode_varint(value):
    value &= 0xFFFFFFFF
    out = bytearray()
    while True:
        byte = value & 0x7F #take 7 lowest bits
        value >>= 7
        if value:
            byte |= 0x80
        out.append(byte)
        if not value:
            break
    return bytes(out)


async def read_varint(reader):
    result = 0
    shift = 0
    while True:
        byte = (await reader.readexactly(1))[0]
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result
        shift += 7
        if shift > 35:
            raise ValueError("Invalid VarInt")


def decode_varint_bytes(data, offset=0):
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("Incomplete VarInt")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, offset
        shift += 7
        if shift > 35:
            raise ValueError("Invalid VarInt")

#start bot checking bot token is environment var
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: Set the DISCORD_TOKEN environment variable to your bot token.")
    else:
        bot.run(BOT_TOKEN)
