from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from cogs.utils import *


class GapCommand(commands.Cog):

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

    @app_commands.command(
        name="gap",
        description="Show the gap between the player and the player above and below (if any).",
    )
    @app_commands.describe(
        identifier="The identifier of the player you want to see the gap of.",
        rank="If you wish to search the gap of a player with its rank instead of its name",
        region="Region to query (GLB or JP).",
    )
    @app_commands.autocomplete(region=autocompletion_region)
    async def gap(
        self, ctx, identifier: str = None, rank: str = None, region: str = "GLB"
    ):
        try:
            await ctx.response.defer()
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

            if isinstance(players, list) and len(players) > 1:
                if len(players) >= 25:
                    await ctx.followup.send(
                        "Too many users found with a matching name. Please be more precise."
                    )
                    return

                await ctx.followup.send(
                    "Multiple players found. Please select one:",
                    view=PlayerSelectView(players, ctx, update, conn),
                )
                return

            player = players if isinstance(players, dict) else players[0]
            await process_gap(ctx, player, update, conn)

        except Exception as e:
            self.bot.log_message(f"An error occurred: {e}")
            await ctx.followup.send("Me no worki lol ask Polo (@polowiper) 2 fix plz")


class PlayerSelect(discord.ui.Select):

    def __init__(self, players, ctx, update, conn):
        self.ctx = ctx
        self.players = players
        self.update = update
        self.conn = conn
        options = [
            discord.SelectOption(label=player["name"], value=str(index))
            for index, player in enumerate(players)
        ]
        super().__init__(placeholder="Select a player...", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_index = int(self.values[0])
        player = self.players[selected_index]
        await process_gap(self.ctx, player, self.update, self.conn)


class PlayerSelectView(discord.ui.View):

    def __init__(self, players, ctx, update, conn):
        super().__init__()
        self.add_item(PlayerSelect(players, ctx, update, conn))


async def process_gap(ctx, player, update, conn):
    pro, noob = find_gap(player, conn)
    embed = discord.Embed(
        title=f"{player['name']} - Points Gap",
        description=f"Points gap comparison for {player['name']}",
        color=0x00B0F4,
    )
    pro_gap = abs(pro["points"][-1] - player["points"][-1]) if pro else 1e99
    noob_gap = abs(noob["points"][-1] - player["points"][-1]) if noob else 1e99

    if pro:
        delta_pro = (
            pro_gap - abs(pro["points"][-2] - player["points"][-2])
            if len(player["points"]) >= 2 and len(pro["points"]) >= 2
            else 0
        )
        estimated_time_pro = (
            int((pro_gap) / (abs(delta_pro) * 4 / 60)) if delta_pro != 0 else 0
        )
        enplus = (
            f"\n|--> `around {estimated_time_pro} minutes needed` --> (<t:{int(update.timestamp() + estimated_time_pro * 60)}:R>)"
            if delta_pro <= 0
            else f"\n:warning: {pro['name']} is farming faster than you! Skill issue, take this L "
        )
        embed.add_field(
            name=f" ⬆️ - {pro['ranks'][-1]} - {pro['name']}",
            value=f"• Points: **{pro['points'][-1]:,}**\n•   Gap:  **{pro_gap:,} ({'+' if delta_pro > 0 else ''}{delta_pro:,})**{enplus}",
            inline=False,
        )

    embed.add_field(
        name=f" ▶️ - {player['ranks'][-1]} - {player['name']}",
        value=f"Points: **{player['points'][-1]:,}**",
        inline=False,
    )

    if noob:
        delta_noob = (
            noob_gap - abs(noob["points"][-2] - player["points"][-2])
            if len(player["points"]) >= 2 and len(noob["points"]) >= 2
            else 0
        )
        embed.add_field(
            name=f" ⬇️ - {noob['ranks'][-1]} - {noob['name']}",
            value=f"Points: **{noob['points'][-1]:,}**\nGap: **{noob_gap:,} ({'+' if delta_noob > 0 else ''}{delta_noob:,})**",
            inline=False,
        )

    embed.add_field(
        name="Updated at",
        value=f"<t:{int(update.timestamp())}:f>    (<t:{int(update.timestamp())}:R>)",
        inline=False,
    )
    await ctx.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(GapCommand(bot))
