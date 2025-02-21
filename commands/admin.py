import enum
import logging
import subprocess

import discord
from discord import app_commands

from utils.responses import respond_success


class LogLevel(enum.Enum):
    critical = logging.CRITICAL
    error = logging.ERROR
    warning = logging.WARNING
    info = logging.INFO
    debug = logging.DEBUG


@app_commands.default_permissions(administrator=True)
class AdminCommands(app_commands.Group):
    @app_commands.command()
    async def reboot(self, interaction: discord.Interaction) -> None:
        subprocess.run(["sudo", "reboot"], check=True)
        await respond_success(interaction, "Rebooting now.")

    @app_commands.command()
    async def logging(
        self,
        interaction: discord.Interaction,
        level: LogLevel,
        logger: str | None = None,
    ) -> None:
        logging.getLogger(logger).setLevel(level.value)
        await respond_success(
            interaction, f"Set logging level of {logger} to {level.name}."
        )
