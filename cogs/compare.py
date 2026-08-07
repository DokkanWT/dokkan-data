import os
import typing
from datetime import date

import discord
from discord import app_commands
from discord.ext import commands
from render import render

from cogs.utils import *


class CompareCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        globals()["bot"] = bot

    async def autocompletion_type_cmp(
        self, interaction: discord.Interaction, current: str
    ):
        choices = [
            app_commands.Choice(name=a, value=b)
            for (a, b) in [
                ("points pace", "points_pace"),
                ("wins pace", "wins_pace"),
                ("ranking", "ranks"),
                ("wins", "wins"),
                ("points", "points"),
                ("seed", "points_wins"),
                ("max wins", "max_wins"),
                ("max points", "max_points"),
            ]
        ]
        return choices

    async def autocompletion_editions(
        self, interaction: discord.Interaction, current: str
    ) -> typing.List[app_commands.Choice[str]]:
        choices = [app_commands.Choice(name="BEST", value="BEST")]

        # Get available editions from older_editions/GLB
        older_editions_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "../older_editions/GLB"
        )
        if os.path.exists(older_editions_path):
            editions = [
                d
                for d in os.listdir(older_editions_path)
                if os.path.isdir(os.path.join(older_editions_path, d))
            ]
            editions.sort()
            for edition in editions:
                choices.append(
                    app_commands.Choice(name=f"Edition {edition}", value=edition)
                )

        return choices

    @app_commands.command(name="compare", description="Compare multiple users.")
    @app_commands.describe(
        type="The type of comparison you want to see. Either 'wins', 'points', or 'ranks'.",
        users="The users you want to compare (ex. /compare type:points users:User1 User2).",
        ranks="If you wish to use the ranks to compare so that you don't have to type the names of the players (this will stack on top of the user list so you can use both at the same time)",
        region="Region to query (GLB or JP).",
        editions="Space-separated list of edition numbers to include your performance from those editions (optional). Use 'BEST' to include your best edition automatically.",
    )
    @app_commands.autocomplete(
        type=autocompletion_type_cmp, editions=autocompletion_editions
    )
    async def compare(
        self,
        ctx,
        type: typing.Optional[str] = None,
        users: typing.Optional[str] = None,
        ranks: typing.Optional[str] = None,
        region: str = "GLB",
        editions: typing.Optional[str] = None,
    ):
        try:
            await ctx.response.defer()
            region = (region or "GLB").upper()
            if type not in [
                "points_pace",
                "wins_pace",
                "ranks",
                "wins",
                "points",
                "points_wins",
                "max_wins",
                "max_points",
            ]:
                await ctx.followup.send(
                    "Please provide a valid type: 'wins', 'points', 'max_points', 'max_wins', 'wins_pace', 'points_pace', or 'ranks'."
                )
                return

            user_list = users.split(" ") if users is not None else []
            ranks_list = ranks.split(" ") if ranks is not None else []
            editions_list = editions.split(" ") if editions is not None else []
            if len(user_list) + len(ranks_list) + len(editions_list) < 2:
                await ctx.followup.send("Please provide at least 2 users to compare.")
                return

            update, start, end, total, left, elapsed = time_data(region=region)
            update = update or datetime.combine(
                date.fromisoformat("2005-03-30"), datetime.min.time()
            )

            conn = load_db_data(region)
            self.unresolved_users = []
            self.resolved_users = {}

            # Identify users needing resolution
            for user in user_list:
                players = find_player(conn, user)
                if players is None:
                    await ctx.followup.send(f"Player '{user}' not found.")
                    return
                elif isinstance(players, list):
                    self.unresolved_users.append((user, players))
                else:
                    self.resolved_users[user] = players
            for ranker in ranks_list:
                identifier = find_rank(conn, int(ranker))
                player = find_player(conn, identifier)
                if player is not None and isinstance(player, dict):
                    self.resolved_users[player["name"]] = player

            # Handle editions parameter to add user's data from older editions
            if editions:
                discord_users = load_discord_users()
                user_id = str(ctx.user.id)
                game_id = discord_users.get(user_id)

                if game_id is None:
                    await ctx.followup.send(
                        "Your Discord account isn't linked to any Dokkan account. Please link your account (/link) to use the editions feature."
                    )
                    return

                for edition in editions_list:
                    if edition == "BEST":
                        # Use find_best function to get best performance
                        best_player = find_best(game_id, region)
                        if best_player and isinstance(best_player, dict):
                            # Add suffix to name to differentiate from current data
                            best_player["name"] = (
                                f"{best_player['name']} (WT{best_player['edition']})"
                            )
                            self.resolved_users[best_player["name"]] = best_player
                    else:
                        # Load data from specific edition
                        older_editions_path = os.path.join(
                            os.path.dirname(os.path.abspath(__file__)),
                            "../older_editions",
                            region,
                        )
                        db_path = os.path.join(
                            older_editions_path, edition, f"{edition}.db"
                        )

                        if os.path.exists(db_path):
                            try:
                                edition_conn = sqlite3.connect(
                                    f"file:{db_path}?mode=ro", uri=True
                                )
                                edition_player = find_player(edition_conn, game_id)
                                edition_conn.close()

                                if edition_player and isinstance(edition_player, dict):
                                    # Add suffix to name to differentiate from current data
                                    edition_player["name"] = (
                                        f"{edition_player['name']} (WT{edition})"
                                    )
                                    self.resolved_users[edition_player["name"]] = (
                                        edition_player
                                    )
                            except sqlite3.Error as e:
                                print(f"Error loading edition {edition}: {e}")

            # Start resolving conflicts one by one
            await self.resolve_next_user(ctx, type, update)

        except Exception as e:
            self.bot.log_message(f"An error occurred: {e}")
            await ctx.followup.send(f"Me no worki lol ask Polo (@polowiper) 2 fix plz")

    async def resolve_next_user(self, ctx, type, update):
        """Resolve multiple matches one by one."""
        if not self.unresolved_users:
            # All users are resolved, proceed with comparison
            await self.process_comparison(ctx, type, update)
            return

        user, players = self.unresolved_users.pop(0)  # Get the next unresolved user

        # Create select menu
        options = [
            discord.SelectOption(label=f"#{p["ranks"][-1]}:{p["name"]}", value=str(i))
            for i, p in enumerate(players)
        ]

        class PlayerSelect(discord.ui.Select):
            def __init__(self, parent, user, players):
                self.parent = parent
                self.user = user
                self.players = players
                super().__init__(
                    placeholder=f"Select the correct player for {user}:",
                    options=options,
                )

            async def callback(self, interaction: discord.Interaction):
                selected_index = int(self.values[0])
                self.parent.resolved_users[self.user] = self.players[selected_index]
                await interaction.response.edit_message(
                    content=f"✅ Selected **{self.players[selected_index]['name']}** for `{self.user}`.",
                    view=None,
                )

                # Move to next unresolved user
                await self.parent.resolve_next_user(ctx, type, update)

        view = discord.ui.View()
        view.add_item(PlayerSelect(self, user, players))
        await ctx.followup.send(
            f"Multiple players found for `{user}`. Please select the correct one:",
            view=view,
        )

    async def process_comparison(self, ctx, type, update):
        """Process the comparison once all users are resolved."""
        player_list = list(self.resolved_users.values())

        render(player_list, "top100_data", type, multiple=True, step=(type == "ranks"))
        image_path = os.path.join("top100_data", f"multiple{type}.png")

        embed = discord.Embed(
            title="Comparison",
            description=f"Here's the {type} comparison between {', '.join(self.resolved_users.keys())}.",
            color=discord.Color.blurple(),
        )
        if os.path.exists(image_path):
            file = discord.File(image_path, filename="comparison.png")
            embed.set_image(url="attachment://comparison.png")
            embed.add_field(
                name="Updated at",
                value=f"<t:{int(update.timestamp())}:f> (<t:{int(update.timestamp())}:R>)",
                inline=False,
            )
            await ctx.followup.send(file=file, embed=embed)
        else:
            await ctx.followup.send("No comparison image was generated.")


async def setup(bot):
    await bot.add_cog(CompareCommand(bot))
