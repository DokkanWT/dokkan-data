from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from cogs.utils import *


class PlayerSelect(discord.ui.Select):
    def __init__(self, players, ctx, resets_amount, update):
        self.ctx = ctx
        self.players = players
        self.resets_amount = resets_amount
        self.update = update

        options = [
            discord.SelectOption(
                label=f"#{player['ranks'][-1]}:{player['name']}", value=str(index)
            )
            for index, player in enumerate(players)
        ]

        super().__init__(placeholder="Select the correct player", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.user.id:
            await interaction.response.send_message(
                "You cannot select a player for this command.", ephemeral=True
            )
            return

        selected_index = int(self.values[0])
        player = self.players[selected_index]
        await process_rseed(
            self.ctx, player, self.resets_amount, self.update, interaction
        )


class PlayerSelectView(discord.ui.View):
    def __init__(self, players, ctx, resets_amount, update):
        super().__init__()
        self.add_item(PlayerSelect(players, ctx, resets_amount, update))


class RandomSeedCommand(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        globals()["bot"] = bot
    async def autocompletion_type(
        self, interaction: discord.Interaction, current: str
    ) -> typing.List[app_commands.Choice[str]]:
        choices = [
            app_commands.Choice(name="Points", value="points"),
            app_commands.Choice(name="Wins", value="wins"),
        ]
        return choices
    @app_commands.command(
        name="rseed",
        description="Show the seed performance of a player relative to a certain amount of resets.",
    )
    @app_commands.describe(
        identifier="Player identifier (name/ID).",
        rank="If you wish to use a rank instead of providing/using an identifier",
        resets_amount="Number of resets for calculation.",
        region="Region to query (GLB or JP).",
    )
    async def rseed(
        self,
        ctx,
        identifier: str = None,
        rank: int = None,
        resets_amount: int = None,
        region: str = "GLB",
    ):
        try:
            await ctx.response.defer()
            region = (region or "GLB").upper()

            if resets_amount is None:
                await ctx.followup.send(
                    "You didn't provide a resets amount, please provide one."
                )
                return

            conn = load_db_data(region)
            discord_users = load_discord_users()
            update, start, end, total, left, elapsed = time_data(region=region)

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
                    identifier = find_rank(conn, rank, region)

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
                    view=PlayerSelectView(players, ctx, resets_amount, update),
                )
                return

            player = players if isinstance(players, dict) else players[0]
            await process_rseed(ctx, player, resets_amount, update)
        except Exception as e:
            self.bot.log_message(f"An error occurred: {e}")
            await ctx.followup.send("Me no worki lol ask Polo (@polowiper) 2 fix plz")


async def process_rseed(ctx, player, resets_amount, update, interaction=None):
    if len(player["hour"]) < resets_amount + 1:
        response = f"Player {player['name']} has not played enough resets."
        if interaction:
            await interaction.response.edit_message(content=response, view=None)
        else:
            await ctx.followup.send(response)
        return

    player_points = player.get("points")
    player_wins = player.get("wins")
    if not player_points or not player_wins:
        response = (
            "No points/wins data available for this player. "
            "Either fetch failed or the player is not in the top 10,000."
        )
        if interaction:
            await interaction.response.edit_message(content=response, view=None)
        else:
            await ctx.followup.send(response)
        return

    wins_delta = player_wins[-1] - player_wins[-resets_amount - 1]
    if wins_delta == 0:
        response = (
            f"Cannot compute relative seed for {player['name']} because wins "
            "did not change over the selected resets."
        )
        if interaction:
            await interaction.response.edit_message(content=response, view=None)
        else:
            await ctx.followup.send(response)
        return

    player_rseed = (
        player_points[-1] - player_points[-resets_amount - 1]
    ) / wins_delta
    embed = discord.Embed(
        title=f"Relative seed performance of {player['name']} over the last {resets_amount} resets",
        description=f"{player['name']} has had a seed of {int(player_rseed):_} over the last {resets_amount} resets.",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Updated at",
        value=f"<t:{int(update.timestamp())}:f> (<t:{int(update.timestamp())}:R>)",
        inline=False,
    )

    if interaction:
        await interaction.response.edit_message(content=None, embed=embed, view=None)
    else:
        await ctx.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(RandomSeedCommand(bot))
