from datetime import datetime, timedelta
import typing

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
                    label=f"#{player["ranks"][-1]}:{player["name"]}", value=str(index)
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


class TargetCommand(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
    async def autocompletion_goal_type(
        self, interaction: discord.Interaction, current: str
    ) -> typing.List[app_commands.Choice[str]]:
        choices = [
            app_commands.Choice(name="Points", value="points"),
            app_commands.Choice(name="Wins", value="wins"),
        ]
        return choices
    @app_commands.command(
        name="target", description="Show the pace needed to reach a goal."
    )
    @app_commands.describe(
        goal="The goal you want to reach.",
        identifier="The identifier of the player you want to see the pace of.",
        goal_type="Whether you want to reach a number of wins or points.",
        rank="If you wish to provide a rank instead of an identifier",
        region="Region to query (GLB or JP).",
    )
    @app_commands.autocomplete(goal_type=autocompletion_goal_type)
    async def target(self, ctx, goal: str, identifier: str = None, goal_type: str = "points", rank: str = None, region: str = "GLB"):
        try:
            await ctx.response.defer()
            region = (region or "GLB").upper()

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

            if left is None:
                await ctx.followup.send("No time left to do the calculations.")
                return

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

            player = find_player(conn, identifier)

            if not player:  # No player found
                await ctx.followup.send(
                    f'Player with name or ID "{identifier}" not found.'
                )
                return

            if isinstance(
                player, list
            ):  # Multiple players found, ask the user to pick one
                view = PlayerSelectView(
                    ctx.user,
                    player,
                    lambda i, idx: self.send_target_pace(ctx, goal, player[idx], region, goal_type=goal_type),
                )
                await ctx.followup.send(
                    "Multiple players found. Please select the correct one:", view=view
                )
                return

            # If it's a dict (single player), process it directly
            await self.send_target_pace(ctx, goal, player, region, goal_type=goal_type)

        except Exception as e:
            self.bot.log_message(f"An error occurred: {e}")
            await ctx.followup.send("Me no worki lol, ask Polo to fix plz.")

    async def send_target_pace(self, ctx, goal, player, region: str, goal_type: str):
        """Send the calculated pace to reach the target."""

        update, start, end, total, left, elapsed = time_data(update_only=False, region=region)
        if goal_type == "points":
            wins_points_ratio = player["points_wins"][-1]

            req_pace = (goal - player["points"][-1]) / (
                left.days * 24 + left.seconds / 3600
            )
            req_wins_pace = req_pace / wins_points_ratio

            if player["points"][-1] >= goal:
                warning_text = "**:warning: You already have more points than your goal, so the required pace is 0.**\n\n"
            else:
                warning_text = ""
        else:
            req_pace = (goal - player["wins"][-1]) / (
                left.days * 24 + left.seconds / 3600
            )
            req_wins_pace = req_pace
            if player["wins"][-1] >= goal:
                warning_text = "**:warning: You already have more wins than your goal, so the required pace is 0.**\n\n"
            else:
                warning_text = ""

        embed = discord.Embed(
            title=f"{player['name']}'s target pace",
            color=discord.Color.green(),
            description=f"{warning_text}• You would need to have a pace of **{round(req_wins_pace, 2)}** wins/hour to reach **{goal:,}** {goal_type}.\n\n_Note: This is based on your current points, goal, remaining time, and average points/wins ratio._",
        )
        await ctx.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(TargetCommand(bot))
