import os
import typing
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from render import render

from cogs.utils import *


class MaxCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        globals()["bot"] = bot

    async def autocompletion_type_max(
        self, interaction: discord.Interaction, current: str
    ) -> typing.List[app_commands.Choice[str]]:
        return [app_commands.Choice(name=a, value=a) for a in ["wins", "points"]]

    async def autocomplete_borders(
        self, interaction: discord.Interaction, current: str
    ) -> typing.List[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name="Yes", value="1"),
            app_commands.Choice(name="No", value="0"),
        ]

    async def autocompletion_region(
        self, interaction: discord.Interaction, current: str
    ) -> typing.List[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name="GLB", value="GLB"),
            app_commands.Choice(name="JP", value="JP"),
        ]

    @app_commands.command(
        name="max", description="Show the maximum points or wins of a player."
    )
    @app_commands.describe(
        type="The type of maximum you want to see. Either 'points' or 'wins'.",
        identifier="The identifier of the player you want to see the maximum of.",
        rank="If you wish to use a rank instead of providing/using an identifier",
        borders="Whether or not you wish to see the borders displayed on the graph.",
        region="Region to query (GLB or JP).",
    )
    @app_commands.autocomplete(
        type=autocompletion_type_max, borders=autocomplete_borders, region=autocompletion_region
    )
    async def max_(
        self,
        ctx,
        type: str = "points",
        identifier: str = None,
        rank: str = None,
        borders: str = None,
        region: str = "GLB",
    ):
        try:
            await ctx.response.defer()
            if type not in ["wins", "points"]:
                await ctx.followup.send(
                    "Please provide a valid type. Either 'points' or 'wins'."
                )
                return
            region = (region or "GLB").upper()
            conn = load_db_data(region)
            discord_users = load_discord_users()
            update, *_ = time_data(region=region)
            update = update or datetime.fromisoformat("2005-03-30")

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

                select = discord.ui.Select(
                    placeholder="Select the correct player",
                    options=[
                        discord.SelectOption(
                            label=f"#{p['ranks'][-1]}:{p['name']}", value=str(index)
                        )
                        for index, p in enumerate(players)
                    ],
                )

                async def select_callback(interaction: discord.Interaction):
                    selected_player = players[int(select.values[0])]
                    view.clear_items()
                    await interaction.response.edit_message(view=view)
                    await self.process_player(
                        ctx, selected_player, update, type, borders, region
                    )

                select.callback = select_callback
                view = discord.ui.View()
                view.add_item(select)
                await ctx.followup.send(
                    "Multiple players found, please select one:", view=view
                )
                return

            await self.process_player(
                ctx,
                players[0] if isinstance(players, list) else players,
                update,
                type,
                borders,
                region,
            )

        except Exception as e:
            self.bot.log_message(f"An error occurred: {e}")
            await ctx.followup.send("Me no worki lol ask Polo (@polowiper) 2 fix plz")

    async def process_player(self, ctx, player, update, type, borders=None, region: str = "GLB"):
        conn = load_db_data(region)
        borders = find_borders(conn, 100) if borders == "1" else None
        maximum = player.get(f"max_{type}")

        if maximum:
            render([player], output_dir, f"max_{type}", border=borders)
            current_max = maximum[-1]  # No shit :explode:
            image_path = os.path.join(
                output_dir, player["name"].replace("$", "\\$"), f"max_{type}.png"
            )

            embed = discord.Embed(
                title=f"{player['name']}'s maximum {type} achievable",
                description=f"Your current max is **{round(current_max, 0):,} {type}**.",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="Updated at",
                value=f"<t:{int(update.timestamp())}:f> (<t:{int(update.timestamp())}:R>)",
                inline=False,
            )

            if os.path.exists(image_path):
                file = discord.File(image_path, filename=f"max_{type}.png")
                embed.set_image(url=f"attachment://max_{type}.png")
                await ctx.followup.send(file=file, embed=embed)
            else:
                await ctx.followup.send(embed=embed)
        else:
            await ctx.followup.send(
                f"No data available for {type}. Either fetch failed or you're not in the top 10,000."
            )


async def setup(bot):
    await bot.add_cog(MaxCommand(bot))
