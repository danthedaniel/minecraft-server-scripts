import argparse
import subprocess
import os
from datetime import datetime, timedelta

# Formats for the sqlite3 CLI
OUTPUT_MODES = [
    "ascii",
    "box",
    "column",
    "csv",
    "html",
    "insert",
    "json",
    "line",
    "list",
    "markdown",
    "quote",
    "table",
    "tabs",
    "tcl",
]


def format_timestamp_col(table_name):
    return f"strftime('%Y-%m-%d %H:00', datetime({table_name}.timestamp, 'unixepoch', 'localtime'))"


def percentile_sql(percentile):
    return f"""
        (
            SELECT printf("%5s", mspt_60s_avg)
            FROM stats AS percentile_stats
            WHERE {format_timestamp_col("percentile_stats")} = HourlyGroups.hour_timestamp
            ORDER BY mspt_60s_avg ASC
            LIMIT 1
            OFFSET (
                SELECT CAST(num_records * {percentile / 100} AS INTEGER)
                FROM HourlyGroups
                WHERE hour_timestamp = HourlyGroups.hour_timestamp
            )
        ) AS p{percentile}"""


def main(args):
    today = datetime.utcnow()

    percentiles = [50, 75, 90, 95, 99]
    sql = f""".mode {args.mode}

    CREATE TEMP TABLE HourlyGroups AS
    SELECT
        {format_timestamp_col("stats")} AS hour_timestamp,
        AVG(player_count) AS avg_player_count,
        COUNT(*) AS num_records
    FROM stats
    GROUP BY hour_timestamp
    HAVING timestamp >= {(today - timedelta(days=args.days)).timestamp()};

    SELECT
        HourlyGroups.hour_timestamp,
        printf("%7s", ROUND(HourlyGroups.avg_player_count, 1)) AS players,
        (
            SELECT printf("%5s", mspt_60s_min)
            FROM stats AS min_stats
            WHERE {format_timestamp_col("min_stats")} = HourlyGroups.hour_timestamp
            ORDER BY mspt_60s_min ASC
            LIMIT 1
        ) AS min,
        {",".join(percentile_sql(percentile) for percentile in percentiles)},
        (
            SELECT printf("%5s", mspt_60s_max)
            FROM stats AS max_stats
            WHERE {format_timestamp_col("max_stats")} = HourlyGroups.hour_timestamp
            ORDER BY mspt_60s_max DESC
            LIMIT 1
        ) AS max
    FROM HourlyGroups
    ORDER BY hour_timestamp ASC;
    """

    base_dir = os.path.dirname(os.path.abspath(__file__))
    subprocess.run(["sqlite3", os.path.join(base_dir, "stats.db")],
                   input=sql, text=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--mode", choices=OUTPUT_MODES, default="box")
    args = parser.parse_args()

    main(args)
