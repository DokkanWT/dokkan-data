import typing
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from render import render

from cogs.utils import *


class PlayerSelect(discord.ui.Select):

    def __init__(self, players, ctx, pace_type, borders, update):
        self.ctx = ctx
        self.players = players
        self.pace_type = pace_type
        self.borders = borders
        self.update = update

        options = [
            discord.SelectOption(
                label=f"#{player["ranks"][-1]}:{player["name"]}", value=str(index)
            )
            for index, player in enumerate(players)
        ]

        super().__init__(placeholder="Select a player...", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_index = int(self.values[0])
        player = self.players[selected_index]

        # Proceed with the selected player
        pace_data = player.get(self.pace_type)
        if pace_data:
            render([player], output_dir, self.pace_type, border=self.borders)
            latest_pace = pace_data[-1]
            image_path = os.path.join(
                output_dir, player["name"], f"{self.pace_type}.png"
            )

            embed = discord.Embed(
                title=f"{player['name']}'s current {self.pace_type.replace('_', ' ')}",
                description=f"Your current {self.pace_type.replace('_', ' ')} is **{latest_pace}**.",
                color=discord.Color.blue(),
            )
            if os.path.exists(image_path):
                file = discord.File(image_path, filename=f"{self.pace_type}.png")
                embed.set_image(url=f"attachment://{self.pace_type}.png")
                embed.add_field(
                    name="Updated at",
                    value=f"<t:{int(self.update.timestamp())}:f>    (<t:{int(self.update.timestamp())}:R>)",
                    inline=False,
                )
                await interaction.response.edit_message(
                    content=None, embed=embed, attachments=[file], view=None
                )
            else:
                embed.add_field(
                    name="Updated at",
                    value=f"<t:{int(self.update.timestamp())}:f>    (<t:{int(self.update.timestamp())}:R>)",
                    inline=False,
                )
                await interaction.response.edit_message(
                    content=None, embed=embed, view=None
                )
        else:
            await interaction.response.edit_message(
                content=f"No data available for {self.pace_type}.", view=None
            )


class PlayerSelectView(discord.ui.View):

    def __init__(self, players, ctx, pace_type, borders, update):
        super().__init__()
        self.add_item(PlayerSelect(players, ctx, pace_type, borders, update))


class PaceCommand(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        globals()["bot"] = bot

    async def autocompletion_type_pace(
        self, interaction: discord.Interaction, current: str
    ) -> typing.List[app_commands.Choice[str]]:
        choices = [app_commands.Choice(name=a, value=a) for a in ["wins", "points"]]
        return choices

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

    @app_commands.command(name="pace", description="Show your current pace.")
    @app_commands.describe(
        pace_type="The pace type you want to see. Either 'wins' or 'points'.",
        identifier="The identifier of the player you want to see the pace of.",
        rank="If you wish to search the pace of a player with its rank instead of its name",
        edition="Specify the edition you want (0 = current edition)",
        borders="Whether or not you wish to see the border on your graph",
        region="Region to query (GLB or JP).",
    )
    @app_commands.autocomplete(
        pace_type=autocompletion_type_pace, borders=autocomplete_borders, region=autocompletion_region
    )
    async def pace(
        self,
        ctx,
        pace_type: str = "wins",
        identifier: str = None,
        rank: str = None,
        edition: int = 0,
        borders: str = None,
        region: str = "GLB",
    ):
        try:
            await ctx.response.defer()

            if pace_type not in ["wins", "points"]:
                await ctx.followup.send(
                    "Please provide a valid type. Either 'wins' or 'points'."
                )
                return

            region = (region or "GLB").upper()
            try:
                conn = load_db_data(region, edition)
            except FileNotFoundError:
                await ctx.followup.send(
                    f"No data found for edition {edition} in {region}."
                )
                return
            discord_users = load_discord_users()
            update, start, end, total, left, elapsed = time_data(
                edition_dir=edition or None, region=region
            )
            if update is None:
                update = datetime.fromisoformat("2005-03-30")
                update = datetime.combine(update, datetime.min.time())

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
                    identifier = find_rank(conn, rank, region, edition)
            print(f"Identifier: {identifier}")
            players = find_player(conn, identifier)
            if borders == "1":
                borders = find_borders(conn, 100)
            else:
                borders = None

            if not players:
                await ctx.followup.send(
                    f'Player with name or ID "{identifier}" not found. (Not in the top 10,000???)'
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
                    view=PlayerSelectView(
                        players, ctx, pace_type + "_pace", borders, update
                    ),
                )
                return

            # If a single player was found, proceed as usual
            player = players if isinstance(players, dict) else players[0]
            pace_type = pace_type + "_pace"

            if pace_type not in ["wins_pace", "points_pace"]:
                await ctx.followup.send(
                    f'Invalid pace type "{pace_type}". Use "wins" or "points".'
                )
                return

            pace_data = player.get(pace_type)
            if pace_data:
                render([player], output_dir, pace_type, border=borders)
                latest_pace = pace_data[-1]
                image_path = os.path.join(
                    output_dir, player["name"].replace("$", "\\$"), f"{pace_type}.png"
                )

                embed = discord.Embed(
                    title=f"{player['name']}'s current {pace_type.replace('_', ' ')}",
                    description=f"Your current {pace_type.replace('_', ' ')} is **{latest_pace}**.",
                    color=discord.Color.blue(),
                )
                if os.path.exists(image_path):
                    file = discord.File(image_path, filename=f"{pace_type}.png")
                    embed.set_image(url=f"attachment://{pace_type}.png")
                    embed.add_field(
                        name="Updated at",
                        value=f"<t:{int(update.timestamp())}:f>    (<t:{int(update.timestamp())}:R>)",
                        inline=False,
                    )
                    await ctx.followup.send(file=file, embed=embed)
                else:
                    embed.add_field(
                        name="Updated at",
                        value=f"<t:{int(update.timestamp())}:f>    (<t:{int(update.timestamp())}:R>)",
                        inline=False,
                    )
                    await ctx.followup.send(embed=embed)
            else:
                await ctx.followup.send(f"No data available for {pace_type}.")
        except Exception as e:
            self.bot.log_message(f"An error occurred: {e}")
            await ctx.followup.send("Me no worki lol ask Polo (@polowiper) 2 fix plz")


async def setup(bot):
    await bot.add_cog(PaceCommand(bot))
