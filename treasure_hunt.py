import socket
import select
import struct
import time
import signal
import random
import re
import http.client
import json
import os
import textwrap
import traceback


class MCRconException(Exception):
    pass


def timeout_handler(signum, frame):
    raise MCRconException("Connection timeout error")


class MCRcon(object):
    socket = None

    def __init__(self, host, password, port=25575, timeout=5):
        self.host = host
        self.password = password
        self.port = port
        self.timeout = timeout
        signal.signal(signal.SIGALRM, timeout_handler)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, type, value, tb):
        self.disconnect()

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
        self._send(3, self.password)

    def disconnect(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def _read(self, length):
        signal.alarm(self.timeout)
        data = b""
        while len(data) < length:
            data += self.socket.recv(length - len(data))
        signal.alarm(0)
        return data

    def _send(self, out_type, out_data):
        if self.socket is None:
            raise MCRconException("Must connect before sending data")

        # Send a request packet
        out_payload = (
            struct.pack("<ii", 0, out_type) +
            out_data.encode("utf8") + b"\x00\x00"
        )
        out_length = struct.pack("<i", len(out_payload))
        self.socket.send(out_length + out_payload)

        # Read response packets
        in_data = ""
        while True:
            # Read a packet
            (in_length,) = struct.unpack("<i", self._read(4))
            in_payload = self._read(in_length)
            in_id, in_type = struct.unpack("<ii", in_payload[:8])
            in_data_partial, in_padding = in_payload[8:-2], in_payload[-2:]

            # Sanity checks
            if in_padding != b"\x00\x00":
                raise MCRconException("Incorrect padding")
            if in_id == -1:
                raise MCRconException("Login failed")

            # Record the response
            in_data += in_data_partial.decode("utf8")

            # If there's nothing more to receive, return the response
            if len(select.select([self.socket], [], [], 0)[0]) == 0:
                return in_data

    def command(self, command):
        result = self._send(2, command)
        time.sleep(0.003)  # MC-72390 workaround
        return result


MINECRAFT_BIOMES = [
    # Ocean biomes first
    "cold_ocean",
    "deep_cold_ocean",
    "deep_frozen_ocean",
    "deep_lukewarm_ocean",
    "deep_ocean",
    "frozen_ocean",
    "lukewarm_ocean",
    "ocean",
    "warm_ocean",
    # Common biomes next
    "plains",
    "forest",
    "desert",
    "savanna",
    "taiga",
    "swamp",
    "river",
    "jungle",
    # Others
    "badlands",
    "bamboo_jungle",
    "beach",
    "birch_forest",
    "cherry_grove",
    "dark_forest",
    "deep_dark",
    "dripstone_caves",
    "eroded_badlands",
    "flower_forest",
    "frozen_peaks",
    "frozen_river",
    "grove",
    "ice_spikes",
    "jagged_peaks",
    "lush_caves",
    "mangrove_swamp",
    "meadow",
    "mushroom_fields",
    "old_growth_birch_forest",
    "old_growth_pine_taiga",
    "old_growth_spruce_taiga",
    "savanna_plateau",
    "snowy_beach",
    "snowy_plains",
    "snowy_slopes",
    "snowy_taiga",
    "sparse_jungle",
    "stony_peaks",
    "stony_shore",
    "sunflower_plains",
    "windswept_forest",
    "windswept_gravelly_hills",
    "windswept_hills",
    "windswept_savanna",
    "wooded_badlands"
]


# 50% chance of elytra, 50% chance of netherite gear
MINECRAFT_TREASURES = [
    "elytra",
    "elytra",
    "elytra",
    "elytra",
    "elytra",
    "elytra",
    "elytra",
    "elytra",
    "elytra",
    "elytra",
    "netherite_ingot",
    "netherite_sword",
    "netherite_pickaxe",
    "netherite_axe",
    "netherite_shovel",
    "netherite_hoe",
    "netherite_helmet",
    "netherite_chestplate",
    "netherite_leggings",
    "netherite_boots",
]


class PositionNotLoaded(Exception):
    pass


def test_for_block(rcon, x, y, z, block):
    output = rcon.command(f"execute if block {x} {y} {z} {block}")

    if output == "Test passed":
        return True
    elif output == "Test failed":
        return False
    elif output == "That position is not loaded":
        raise PositionNotLoaded()
    else:
        raise Exception("Unexpected output from execute command: " + output)


def detect_biome(rcon, x, y, z):
    for biome in MINECRAFT_BIOMES:
        time.sleep(1)  # Delay to keep from hammering the Minecraft main thread
        output = rcon.command(
            f"execute positioned {x} {y} {z} run locate biome minecraft:{biome}")

        match = re.search(r"\((\d+) blocks away\)", output)
        if not match:
            print(f"Error: Could not parse output - {output}")
            continue

        if match.group(1) == "0":
            return biome


TREASURE_MAX_DIST = 5000
TREASURE_DEAD_ZONE = 1000
TREASURE_MAX_HEIGHT = 70
TREASURE_MIN_HEIGHT = -50


# Finds a spot less than TREASURE_MAX_DIST away from 0, 0, 0 on the x and z axes
# and between TREASURE_MIN_HEIGHT and TREASURE_MAX_HEIGHT on the y axis
# that is not in the dead zone (TREASURE_DEAD_ZONE) around 0, 0, 0.
def find_treasure_spot(rcon):
    distance_range = TREASURE_MAX_DIST - TREASURE_DEAD_ZONE
    x = random.randint(-distance_range, distance_range)
    x += TREASURE_DEAD_ZONE * (1 if x > 0 else -1)

    y = random.randint(-TREASURE_MIN_HEIGHT, TREASURE_MAX_HEIGHT)

    z = random.randint(-distance_range, distance_range)
    z += TREASURE_DEAD_ZONE * (1 if z > 0 else -1)

    try:
        if test_for_block(rcon, x, y, z, "minecraft:air"):
            # Scan down
            while test_for_block(rcon, x, y, z, "minecraft:air"):
                y -= 1
                if y < -TREASURE_MIN_HEIGHT:
                    return None

            y += 1
        else:
            # Scan up
            while not test_for_block(rcon, x, y, z, "minecraft:air"):
                y += 1
                if y > TREASURE_MAX_HEIGHT:
                    return None

        return x, y, z

    except PositionNotLoaded:
        return None


def place_treasure(rcon, x, y, z, item):
    rcon.command(
        f"setblock {x} {y} {z} minecraft:chest{{Items:[{{id:'minecraft:{item}',Count:1b}}]}}")


def treasure_gone(rcon, x, y, z):
    if test_for_block(rcon, x, y, z, "minecraft:chest{Items:[]}"):
        return True

    if not test_for_block(rcon, x, y, z, "minecraft:chest"):
        return True

    return False


OPENAI_KEY = "sk-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"


def gpt_completion(prompt):
    conn = http.client.HTTPSConnection("api.openai.com")
    conn.request("POST", "/v1/chat/completions",
                 headers={
                     "Content-Type": "application/json",
                     "Authorization": f"Bearer {OPENAI_KEY}",
                 },
                 body=json.dumps({
                     "model": "gpt-3.5-turbo",
                     "messages": [
                         {
                             "role": "system",
                             "content": "You are a dungeon master narrator",
                         },
                         {
                             "role": "user",
                             "content": prompt,
                         },
                     ],
                 }),
                 )
    response = json.loads(conn.getresponse().read().decode("utf-8"))
    return response["choices"][0]["message"]["content"]


def list_players(rcon):
    response = rcon.command("list")
    match = re.search(r"\d+ players online: (.*)", response)
    if not match:
        return []

    return match.group(1).split(", ")


def announce(rcon, tellraw_data):
    rcon.command(f"tellraw @a {json.dumps(tellraw_data)}")


def log(message, file, level="INFO"):
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%S%z')

    for line in message.split("\n"):
        log_line = f"[{level}] {line}"
        print(log_line)
        print(f"[{timestamp}] {log_line}", file=file)


RCON_HOST = "localhost"
RCON_PASSWORD = "password"
RCON_PORT = 25575

SKIP_ODDS = 48  # Higher number means less frequent treasure hunts
WATER_LEVEL = 62


def main(log_file):
    if random.randint(0, SKIP_ODDS) != 0:
        log("Skipping treasure hunt", log_file)
        return

    with MCRcon(RCON_HOST, RCON_PASSWORD, RCON_PORT) as rcon:
        online_players = list_players(rcon)
        if len(online_players) == 0:
            log("No online players, exiting", log_file)
            return

        for _ in range(1000):
            location = find_treasure_spot(rcon)
            if location is None:
                continue

            x, y, z = location
            log(f"Found treasure spot at {x}, {y}, {z}", log_file)

            biome = detect_biome(rcon, x, y, z)
            if biome is None:
                log("Could not detect biome, skipping", log_file)
                continue
            if "ocean" in biome and y > WATER_LEVEL:
                log("Treasure was on the ocean, skipping", log_file)
                continue

            height = ""
            if y < -40:
                height = "Close to bedrock"
            elif y < 0:
                height = "Deepslate level"
            elif y < WATER_LEVEL:
                height = "Below ground"
            else:
                height = "Above ground"

            round_to = 16
            x_approx = round(x / round_to) * round_to
            z_approx = round(z / round_to) * round_to

            item = random.choice(MINECRAFT_TREASURES)
            flavor_text = gpt_completion(textwrap.dedent(f"""
                Please give me flavor text for a treasure hunt describing a
                location where a chest is hidden in a Minecraft world.

                Details:
                Biome: {biome.replace('_', ' ')}
                X: ~{x_approx}
                Z: ~{z_approx}
                Height: {height}
                Contents: {item.replace('_', ' ')}

                Be concise. This should be no more than 3 sentences.
                Make sure to include the biome, coordinates (and that they are
                approximate), height, and contents. This message is broadcast to
                all online players, so tailor it accordingly.
            """))

            place_treasure(rcon, x, y, z, item)
            log(f"{item} placed at {x}, {y}, {z} in biome {biome}", log_file)
            announce(rcon, {
                "text": "TREASURE HUNT!",
                "color": "green",
                "bold": True,
            })
            announce(rcon, {
                "text": flavor_text,
                "color": "green",
            })

            flavor_text_oneline = flavor_text.replace('\n', ' ')
            log(f"Flavor text: {flavor_text_oneline}", log_file)

            time.sleep(10)

            announce(rcon, {
                "text": "Move quickly! The treasure chest (and all of its contents) will disappear in 10 minutes!",
                "color": "red",
            })

            minute_tape = [None, None, None, None, None, 5, None, 3, 2, 1]
            for remaining_time_alert in minute_tape:
                time.sleep(60)

                if treasure_gone(rcon, x, y, z):
                    log("Treasure was acquired!", log_file)
                    announce(rcon, {
                        "text": "The treasure chest has been emptied!",
                        "color": "green",
                    })
                    break

                if remaining_time_alert is None:
                    continue

                duration = "minutes" if remaining_time_alert > 1 else "minute"
                announce(rcon, {
                    "text": f"The treasure chest will disappear in {remaining_time_alert} {duration}!",
                    "color": "red",
                })
            else:
                time.sleep(60)

            if test_for_block(rcon, x, y, z, "minecraft:chest"):
                rcon.command(f"setblock {x} {y} {z} minecraft:air")

                if not treasure_gone(rcon, x, y, z):
                    # Only bother announcing the chest vanished if the treasure is still there
                    announce(rcon, {
                        "text": "The treasure chest vanishes back to the realm it came from!",
                        "color": "green",
                    })

                log("Treasure chest disappeared", log_file)
            else:
                log("Treasure chest was already gone", log_file)

            log("Treasure hunt complete", log_file)
            break

        else:
            log("Could not find a treasure spot", log_file)


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(base_dir, "treasure_hunt.log"), "a") as log_file:
        try:
            main(log_file)
        except Exception as e:
            log(traceback.format_exception(e, limit=2), log_file, level="ERROR")
            raise e
