import socket
import select
import struct
import time
import signal
import re
import sqlite3
import time
import os


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


def init_sqlite(db):
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            timestamp INTEGER PRIMARY KEY,
            player_count INTEGER NOT NULL,
            mspt_60s_min REAL NOT NULL,
            mspt_60s_avg REAL NOT NULL,
            mspt_60s_max REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            timestamp INTEGER NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (timestamp, name)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS players_timestamp_idx
        ON players (timestamp)
    """)
    db.commit()


def insert_stats(db, timestamp, players, mspt):
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO stats (timestamp, player_count, mspt_60s_avg, mspt_60s_min, mspt_60s_max)
        VALUES (?, ?, ?, ?, ?)
    """, (timestamp, len(players), *mspt))
    cursor.executemany(
        "INSERT INTO players (timestamp, name) VALUES (?, ?)",
        [(timestamp, player) for player in players])

    db.commit()


def strip_color_codes(text):
    return re.sub("\xa7[0-9a-f]", "", text, flags=re.IGNORECASE)


def mspt(rcon):
    response = strip_color_codes(rcon.command("mspt"))

    lines = response.split("\n")
    if lines[0] != "Server tick times (avg/min/max) from last 5s, 10s, 1m:":
        print("Unexpected response from server:", response)
        return

    # Remove the leading "◴ "
    stats_line = lines[1][len("◴ "):]
    return {
        label: tuple(float(x) for x in section.split("/"))
        for label, section in zip(("5s", "10s", "1m"), stats_line.split(", "))
    }


def players_online(rcon):
    response = rcon.command("list")

    match = re.match(
        r"There are (\d+) of a max of (\d+) players online: (.*)", response)
    if match is None:
        print("Unexpected response from server:", response)
        return

    return [name for name in match.group(3).split(", ") if len(name) > 0]


RCON_HOST = "localhost"
RCON_PASSWORD = "password"
RCON_PORT = 25575


def main():
    base_path = os.path.dirname(os.path.realpath(__file__))
    database = os.path.join(base_path, "stats.db")

    with MCRcon(RCON_HOST, RCON_PASSWORD, RCON_PORT) as rcon, sqlite3.connect(database) as db:
        init_sqlite(db)

        stats = mspt(rcon)
        if stats is None:
            return

        players = players_online(rcon)
        if players is None:
            return

        utc_timestamp = int(time.mktime(time.gmtime()))
        insert_stats(db, utc_timestamp, players, stats["1m"])


if __name__ == "__main__":
    main()
