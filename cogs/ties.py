import os
import typing
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from render import render

from cogs.utils import *


class TiesCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        globals()["bot"] = bot

    @app_commands.command(name="ties", description="Show the wins of a player.")
    async def wins(self, ctx):
        try:
            await ctx.response.defer()
            conn = load_db_data()
            update, _, _, _, _, elapsed = time_data()
            current_hour = round(elapsed.total_seconds() / 3600, 2)
            self.bot.log_message(f"{current_hour}")

            conn.create_function("strrev", 1, lambda s: s[::-1])
            caca = conn.execute(
                """
                SELECT p.id, latest_points, latest_hour
                FROM (
                    SELECT 
                        id,
                        CAST(SUBSTR(hour, LENGTH(hour) - INSTR(strrev(hour), ',') + 2, LENGTH(hour)) AS FLOAT) AS latest_hour,
                        CAST(SUBSTR(points, LENGTH(points) - INSTR(strrev(points), ',') + 2, LENGTH(points)) AS INTEGER) AS latest_points
                    FROM players
                ) p
                WHERE p.latest_hour = ?
                AND p.latest_points IN (
                    SELECT latest_points
                    FROM (
                        SELECT 
                            CAST(SUBSTR(hour, LENGTH(hour) - INSTR(strrev(hour), ',') + 2, LENGTH(hour)) AS FLOAT) AS latest_hour,
                            CAST(SUBSTR(points, LENGTH(points) - INSTR(strrev(points), ',') + 2, LENGTH(points)) AS INTEGER) AS latest_points
                        FROM players
                    )
                    WHERE latest_hour = ?
                    GROUP BY latest_points
                    HAVING COUNT(*) > 1
                );
                """,
                (current_hour, current_hour),
            )
            result = caca.fetchall()

            # Group IDs by points
            ties_by_points = {}
            for player_id, points, _ in result:
                ties_by_points.setdefault(points, []).append(player_id)

            # Prepare a message with multiple groups
            message = "Here's the list of players tied right now:\n"
            for points, ids in sorted(
                ties_by_points.items(), reverse=True
            ):  # highest points first
                message += f"**{points:,} points:** {', '.join(map(str, ids))}\n"

            await ctx.followup.send(message)

        except Exception as e:
            self.bot.log_message(f"An error occurred: {e}")
            await ctx.followup.send("Me no worki lol ask Polo (@polowiper) 2 fix plz")


async def setup(bot):
    await bot.add_cog(TiesCommand(bot))
