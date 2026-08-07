import sqlite3

import discord
from discord import Interaction, app_commands
from discord.ext import commands
from cogs.utils import load_db_data


class FindUser(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        globals()["bot"] = bot

    async def autocompletion_region(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name="GLB", value="GLB"),
            app_commands.Choice(name="JP", value="JP"),
        ]

    @app_commands.command(name="finduser", description="Find a user by name or ID.")
    @app_commands.autocomplete(region=autocompletion_region)
    @app_commands.describe(region="Region to query (GLB or JP).")
    async def finduser(self, interaction: Interaction, identifier: str, region: str = "GLB"):
        await interaction.response.defer()
        region = (region or "GLB").upper()
        conn = load_db_data(region)
        cursor = conn.cursor()
        identifier = "%" + "%".join(identifier) + "%"
        # Polo -> %P%o%l%o%          Fuzzy seaching supremacy
        cursor.execute("SELECT name, id FROM players WHERE name LIKE ?", (identifier,))
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            await interaction.followup.send(
                "No users found with the given identifier.", ephemeral=True
            )
            return

        class UserSelectMenu(discord.ui.Select):
            def __init__(self):
                options = [
                    discord.SelectOption(label=row[0], description=f"name: {row[0]}")
                    for row in rows
                ]
                super().__init__(
                    placeholder="Select a user",
                    min_values=1,
                    max_values=1,
                    options=options,
                )

            async def callback(self, interaction: Interaction):
                selected_user = self.values[0]
                await interaction.response.send_message(
                    f"You selected: {selected_user}", ephemeral=True
                )

        class UserSelectView(discord.ui.View):
            def __init__(self):
                super().__init__()
                self.add_item(UserSelectMenu())

        if len(rows) < 25:
            await interaction.followup.send(
                "Please select a user from the list of users found",
                view=UserSelectView(),
                ephemeral=True,
            )
        else:
            await interaction.followup.send("Too many options lol rip")


async def setup(bot):
    await bot.add_cog(FindUser(bot))
