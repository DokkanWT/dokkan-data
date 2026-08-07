import typing
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View

from cogs.utils import *


class PlayerSelectView(View):
    def __init__(self, user, players, callback):
        super().__init__(timeout=60)
        self.user = user
        self.callback = callback  # Function to call when a selection is made

        select = Select(
            placeholder="Select the correct player...",
            options=[
                discord.SelectOption(
                    label=f"{player["ranks"][-1]}:{player["name"]}", value=str(index)
                )
                for index, player in enumerate(players)
            ],
            min_values=1,
            max_values=1,
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "You're not allowed to select this.", ephemeral=True
            )
            return

        selected_index = int(interaction.data["values"][0])
        await interaction.message.delete()  # Delete the select menu after selection
        await self.callback(interaction, selected_index)


class WhenCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def autocompletion_type_goal(
        self, interaction: discord.Interaction, current: str
    ) -> typing.List[app_commands.Choice[str]]:
        return [app_commands.Choice(name=a, value=a) for a in ["wins", "points"]]

    @app_commands.command(
        name="when",
        description="Show the estimated time of when a player will reach a goal.",
    )
    @app_commands.describe(
        goal="The goal you want to reach.",
        identifier="The identifier of the player you want to see the estimated time of.",
        pace="Your pace per hour.",
        rank="If you wish to provide a rank instead of an identifier",
        region="Region to query (GLB or JP).",
    )
    @app_commands.autocomplete(goal_type=autocompletion_type_goal)
    async def when(
        self,
        ctx,
        goal: str,
        goal_type: str = "points",
        pace: int = 0,
        identifier: str = None,
        rank: str = None,
        region: str = "GLB",
    ):
        try:
            await ctx.response.defer()
            region = (region or "GLB").upper()

            if pace <= 0:
                await ctx.followup.send(
                    "Please provide a valid pace (greater than 0).", ephemeral=True
                )
                return

            # Convert goal (e.g., 850M -> 850000000)
            num = {"m": 1000000, "b": 1000000000, "k": 1000}
            if goal[-1].lower() in num:
                goal = int(goal[:-1]) * num[goal[-1].lower()]
            try:
                goal = int(goal)
            except ValueError:
                await ctx.followup.send(
                    "Please provide a valid number as a goal.", ephemeral=True
                )
                return

            # Load database and user data
            conn = load_db_data(region)
            discord_users = load_discord_users()
            update, start, end, total, left, elapsed = time_data(update_only=False, region=region)

            if update is None:
                self.bot.log_message("No update time found, setting to default")
                update = datetime.fromisoformat("2005-03-30")
                update = datetime.combine(update, datetime.min.time())
                end = update
                start = update

            if identifier is None:
                if rank is None:
                    user_id = str(ctx.user.id)
                    identifier = discord_users.get(user_id)
                    if identifier is None:
                        await ctx.followup.send(
                            "You did not provide a Dokkan name/ID and your Discord account isn't linked to any. Please provide an identifier or link your Discord account (/link)."
                        )
                        return
                else:
                    identifier = find_rank(conn, rank)

            players = find_player(conn, identifier)

            if not players:  # No player found
                await ctx.followup.send(
                    f'Player with name or ID "{identifier}" not found.'
                )
                return

            if (
                isinstance(players, list) and len(players) > 1
            ):  # Multiple players found, ask the user to pick one
                view = PlayerSelectView(
                    ctx.user,
                    players,
                    lambda i, idx: self.calculate_when(
                        ctx, goal, goal_type, pace, players[idx], region
                    ),
                )
                await ctx.followup.send(
                    "Multiple players found. Please select the correct one:", view=view
                )
                return

            # If it's a dict (single player), process it directly
            await self.calculate_when(ctx, goal, goal_type, pace, players, region)

        except Exception as e:
            self.bot.log_message(f"An error occurred: {e}")
            await ctx.followup.send("Me no worki lol, ask Polo to fix plz.")

    async def calculate_when(self, ctx, goal, goal_type, pace, player, region: str):
        """Calculate and send the estimated time to reach the goal."""
        update, start, end, total, left, elapsed = time_data(update_only=False, region=region)

        if goal_type == "points":
            player_points = player["points"][-1]
            if goal <= player_points:
                await ctx.followup.send(
                    "Please provide a goal higher than your current points."
                )
                return
            req_points = goal - player_points
            req_hours = req_points / pace
            final_timestamp = (update + timedelta(hours=req_hours)).timestamp()
            req = req_points

        elif goal_type == "wins":
            player_wins = player["wins"][-1]
            if goal <= player_wins:
                await ctx.followup.send(
                    "Please provide a goal higher than your current wins."
                )
                return
            req_wins = goal - player_wins
            req_hours = req_wins / pace
            final_timestamp = (update + timedelta(hours=req_hours)).timestamp()
            req = req_wins

        if final_timestamp > end.timestamp():
            await ctx.followup.send("You can't reach this goal in the future.... L")
            return

        embed = discord.Embed(
            title=f"{player['name']}'s estimated time to reach {goal:,} {goal_type}",
            description=f"You need to reach **{req:,}** {goal_type} in **{round(req_hours, 2):,}** hours to reach your goal.",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Updated at",
            value=f"<t:{int(update.timestamp())}:f> (<t:{int(update.timestamp())}:R>)",
            inline=False,
        )

        await ctx.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(WhenCommand(bot))
