import typing
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


import sqlite3
from datetime import datetime

import discord
import json
from discord import app_commands
from discord.ext import commands
from render import render

from cogs.utils import *

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
class PredictCommand(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        globals()["bot"] = bot

    async def autocompletion_region(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name="GLB", value="GLB"),
            app_commands.Choice(name="JP", value="JP"),
        ]

    @app_commands.command(name="predict", description="Predict final points based on current performance vs historical averages.")
    @app_commands.describe(
        identifier="The identifier of the player you want to predict for.",
        rank="If you wish to search by rank instead of name",
        region="Region to query (GLB or JP).",
    )
    @app_commands.autocomplete(
        region=autocompletion_region,
    )
    async def predict(
        self,
        ctx,
        identifier: typing.Optional[str] = None,
        rank: typing.Optional[str] = None,
        region: str = "GLB"
    ):
        try:
            await ctx.response.defer()
            old_db_path = os.path.join(ROOT_DIR, "older_editions", f"{region.upper()}")
            dbs = os.listdir(old_db_path)

            region = (region or "GLB").upper()
            conn = load_db_data(region)
            discord_users = load_discord_users()
            update, *_ = time_data(region=region)
            if update is None:
                update = datetime.fromisoformat("2005-03-30")
                update = datetime.combine(update, datetime.min.time())
            if identifier is None:
                if rank is None:
                    user_id = str(ctx.user.id)
                    identifier = discord_users.get(user_id)
                    if identifier is None:
                        await ctx.followup.send(
                            "You did not provide a Dokkan name/ID and your Discord account isn't linked to any. Please provide an identifier or link your Discord account (/link)"
                        )
                        return
                else:
                    identifier = find_rank(conn, rank, region=region)
            
            players = find_player(conn, identifier)
            if not players:
                await ctx.followup.send(
                    f'Player with name or ID "{identifier}" not found. (Not in the top 10,000???)'
                )
                return
            
            # Handle both single player dict and list of players
            if isinstance(players, list):
                if len(players) > 1:
                    await ctx.followup.send(
                        f'Multiple players found with the identifier "{identifier}". Please be more specific.'
                    )
                    return
                player = players[0]
            else:
                # Single player dict returned (ID match)
                player = players
            player_rank = player["ranks"][-1]
            player_current_points = player["points"][-1]
            player_current_hour = player["hour"][-1]
            
            # Get current tournament elapsed time
            _, start, _, _, _, elapsed = time_data(region=region)
            if elapsed is None:
                await ctx.followup.send("Unable to calculate elapsed time for current tournament.")
                return
            current_elapsed_hours = round(elapsed.total_seconds() / 3600, 2)
            
            # Collect historical data: points at similar elapsed time for this rank
            historical_points_at_current_time = []
            historical_final_points = []
            
            print(f"\n=== DEBUG: Searching historical data for rank {player_rank} at {current_elapsed_hours}h ===")
            print(f"Scanning directory: {old_db_path}")
            print(f"Found editions: {dbs}")
            
            for db in dbs:
                try:
                    db_path = os.path.join(old_db_path, db, f"{db}.db")
                    print(f"\n[Edition {db}] Checking: {db_path}")
                    
                    if not os.path.exists(db_path):
                        print(f"  -> DB file not found, skipping")
                        continue
                    
                    print(f"  -> DB exists, connecting...")
                    old_conn = sqlite3.connect(db_path)
                    cursor = old_conn.cursor()
                    
                    # For historical editions, we need to find players at the FINAL rank
                    # not at a specific elapsed hour like find_rank does for current tournaments
                    # Query: find player whose last rank (final rank) matches our target rank
                    # AND has the longest hour array (stayed until the end)
                    old_conn.create_function("strrev", 1, lambda s: s[::-1])
                    cursor.execute(
                        """
                        SELECT id FROM players WHERE
                        CAST(SUBSTR(ranks, LENGTH(ranks) - INSTR(strrev(ranks), ',') + 2, LENGTH(ranks)) AS INTEGER) = ?
                        ORDER BY LENGTH(hour) - LENGTH(REPLACE(hour, ',', '')) DESC
                        LIMIT 1
                        """,
                        (player_rank,)
                    )
                    row = cursor.fetchone()
                    old_player_id = row[0] if row else None
                    
                    print(f"  -> Query for final rank {player_rank} (longest data) returned: {old_player_id}")
                    
                    if old_player_id:
                        # Get the full player data
                        old_player = find_player(old_conn, old_player_id)
                        print(f"  -> find_player returned type: {type(old_player)}")
                        
                        # Handle both dict and list returns from find_player
                        if isinstance(old_player, list):
                            old_player = old_player[0] if old_player else None
                        
                        if old_player:
                            # Find the points at approximately the same elapsed hour
                            hours = old_player["hour"]
                            points = old_player["points"]
                            print(f"  -> Player has {len(hours)} data points")
                            
                            # Find the closest hour to current_elapsed_hours
                            closest_idx = None
                            min_diff = float('inf')
                            for idx, hour in enumerate(hours):
                                diff = abs(hour - current_elapsed_hours)
                                if diff < min_diff:
                                    min_diff = diff
                                    closest_idx = idx
                            
                            print(f"  -> Closest hour: {hours[closest_idx] if closest_idx is not None else 'N/A'} (diff: {min_diff:.2f}h)")
                            
                            if closest_idx is not None and min_diff <= 2.0:  # Within 2 hours tolerance
                                historical_points_at_current_time.append(points[closest_idx])
                                historical_final_points.append(points[-1])
                                print(f"  -> ✓ Added: {points[closest_idx]:,} points at {hours[closest_idx]:.2f}h, final: {points[-1]:,}")
                            else:
                                print(f"  -> ✗ Skipped: difference too large ({min_diff:.2f}h > 2.0h)")
                        else:
                            print(f"  -> find_player returned None")
                    else:
                        print(f"  -> Rank {player_rank} not found in this edition")
                    
                    old_conn.close()
                except Exception as e:
                    print(f"  -> ERROR: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            print(f"\n=== Found {len(historical_points_at_current_time)} historical data points ===\n")
            
            if not historical_points_at_current_time:
                await ctx.followup.send(
                    f"Not enough historical data to predict for rank {player_rank}."
                )
                return
            
            # Calculate averages
            avg_points_at_current_time = sum(historical_points_at_current_time) / len(historical_points_at_current_time)
            avg_final_points = sum(historical_final_points) / len(historical_final_points)
            
            # Calculate percentage difference from average
            if avg_points_at_current_time > 0:
                percentage_diff = ((player_current_points - avg_points_at_current_time) / avg_points_at_current_time) * 100
            else:
                percentage_diff = 0
            
            # Apply the percentage difference to the average final points to get prediction
            predicted_final_points = avg_final_points * (1 + (percentage_diff / 100))
            
            # Format the response
            embed = discord.Embed(title=f"Prediction for {player['name']} (Rank {player_rank})", color=0x00ff00)
            embed.add_field(name="Current Points", value=f"**{player_current_points:,}**", inline=False)
            embed.add_field(name="Elapsed Time", value=f"**{current_elapsed_hours:.2f}h**", inline=False)
            embed.add_field(name="Historical Average (at current time)", value=f"**{int(avg_points_at_current_time):,}**", inline=False)
            embed.add_field(name="Your Difference", value=f"**{percentage_diff:+.2f}%**", inline=False)
            embed.add_field(name="Historical Average (final)", value=f"**{int(avg_final_points):,}**", inline=False)
            embed.add_field(name="Predicted Final Points", value=f"**{int(predicted_final_points):,}**", inline=False)
            embed.set_footer(text=f"Based on {len(historical_points_at_current_time)} past tournament(s)")
            await ctx.followup.send(embed=embed)
            conn.close()

        except Exception as e:
            print(f"An error occurred in predict command: {e}")
            import traceback
            traceback.print_exc()
            await ctx.followup.send("Me no worki lol ask Polo (@polowiper) 2 fix plz")


async def setup(bot):
    await bot.add_cog(PredictCommand(bot))
