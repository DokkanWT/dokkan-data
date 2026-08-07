import os
import typing
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from render import render

from cogs.utils import *


class PlayerSelect(discord.ui.Select):
    def __init__(self, players, ctx, borders, update):
        self.ctx = ctx
        self.players = players
        self.borders = borders
        self.update = update

        options = [
            discord.SelectOption(
                label=f"#{player["ranks"][-1]:{player["name"]}}", value=str(index)
            )
            for index, player in enumerate(players)
        ]
        super().__init__(placeholder="Select a player...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.user.id:
            await interaction.response.send_message(
                "You cannot select a player for this command.", ephemeral=True
            )
            return

        selected_index = int(self.values[0])
        player = self.players[selected_index]
        await process_wins(self.ctx, player, self.borders, self.update, interaction)


class PlayerSelectView(discord.ui.View):
    def __init__(self, players, ctx, borders, update):
        super().__init__()
        self.add_item(PlayerSelect(players, ctx, borders, update))


class WinsCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        globals()["bot"] = bot

    async def autocomplete_borders(
        self, interaction: discord.Interaction, current: str
    ) -> typing.List[app_commands.Choice[str]]:
        choices = [
            app_commands.Choice(name="Yes", value="1"),
            app_commands.Choice(name="No", value="0"),
        ]
        return choices

    async def autocompletion_region(
        self, interaction: discord.Interaction, current: str
    ) -> typing.List[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name="GLB", value="GLB"),
            app_commands.Choice(name="JP", value="JP"),
        ]

    @app_commands.command(name="wins", description="Show the wins of a player.")
    @app_commands.describe(
        identifier="The identifier of the player you want to see the wins of.",
        rank="If you wish to provide a rank instead of an identifier",
        borders="Whether or not you want to see the borders on your graphs",
        region="Region to query (GLB or JP).",
    )
    @app_commands.autocomplete(borders=autocomplete_borders, region=autocompletion_region)
    async def wins(
        self, ctx, identifier: str = None, rank: str = None, borders: str = None, region: str = "GLB"
    ):
        try:
            await ctx.response.defer()
            region = (region or "GLB").upper()
            conn = load_db_data(region)
            discord_users = load_discord_users()
            update, _, _, _, _, _ = time_data(region=region)

            borders = find_borders(conn, 100) if borders == "1" else None

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

            if not players:
                await ctx.followup.send(
                    f'Player with name or ID "{identifier}" not found. (Not in the top 10,000?)'
                )
                return

            if isinstance(players, list) and len(players) > 1:
                if len(players) >= 25:
                    await ctx.followup.send(
                        "Too many users found with a matching name. Please be more precise."
                    )
                    return
                await ctx.followup.send(
                    "Multiple players found. Please select one:",
                    view=PlayerSelectView(players, ctx, borders, update),
                )
                return

            player = players if isinstance(players, dict) else players[0]
            await process_wins(ctx, player, borders, update)

        except Exception as e:
            self.bot.log_message(f"An error occurred: {e}")
            await ctx.followup.send("Me no worki lol ask Polo (@polowiper) 2 fix plz")


async def process_wins(ctx, player, borders, update, interaction=None):
    wins_data = player.get("wins")
    if not wins_data:
        response = "No data available for wins. Either fetch failed or you're not in the top 10,000."
        if interaction:
            await interaction.response.edit_message(content=response, view=None)
        else:
            await ctx.followup.send(response)
        return

    render([player], output_dir, "wins", border=borders)
    current_wins = wins_data[-1]
    image_path = os.path.join(
        output_dir, player["name"].replace("$", "\\$"), "wins.png"
    )

    embed = discord.Embed(
        title=f"{player['name']}'s Current Wins",
        description=f"The current wins are **{current_wins:,}**.",
        color=discord.Color.brand_red(),
    )
    embed.add_field(
        name="Updated at",
        value=f"<t:{int(update.timestamp())}:f> (<t:{int(update.timestamp())}:R>)",
        inline=False,
    )

    if os.path.exists(image_path):
        file = discord.File(image_path, filename="wins.png")
        embed.set_image(url="attachment://wins.png")
        if interaction:
            await interaction.response.edit_message(
                embed=embed, attachments=[file], view=None
            )
        else:
            await ctx.followup.send(file=file, embed=embed)
    else:
        if interaction:
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            await ctx.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(WinsCommand(bot))
