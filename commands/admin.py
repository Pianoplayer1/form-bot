import subprocess

import discord
from discord import app_commands

from utils.responses import respond_success


@app_commands.default_permissions(administrator=True)
class AdminCommands(app_commands.Group):
    @app_commands.command()
    async def reboot(self, interaction: discord.Interaction) -> None:
        subprocess.run(["sudo", "reboot"], check=True)
        await respond_success(interaction, "Rebooting now.")
