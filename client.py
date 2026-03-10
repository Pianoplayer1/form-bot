import logging
import os

import asyncpg
import discord

from commands.admin import AdminCommands
from commands.forms import FormCommands
from commands.modals import FormModalCommands
from commands.questions import FormQuestionCommands
from utils.logger import DiscordLogHandler
from views.starter import StarterView


class Client(discord.Client):
    pool: asyncpg.Pool

    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        query_ids = "SELECT DISTINCT message_id FROM form_views;"
        query_views = "SELECT * FROM form_views WHERE message_id = $1 ORDER BY id;"

        self.pool = await asyncpg.create_pool(os.getenv("FORMS_DB_URL"))
        selected_forms: dict[int, int] = {}
        selected_modals: dict[int, int] = {}

        # Add persistent views to client
        for record in await self.pool.fetch(query_ids):
            setup_data = [
                (r["label"], r["emoji"], discord.ButtonStyle(r["style"]), r["form_id"])
                for r in await self.pool.fetch(query_views, record["message_id"])
            ]
            view = StarterView(self.pool, record["message_id"], setup_data)
            self.add_view(view, message_id=record["message_id"])

        # Setup admin commands in test guild
        test_guild_id = os.getenv("FORMS_TEST_GUILD")
        if test_guild_id is not None:
            test_guild = discord.Object(int(test_guild_id))
            self.tree.add_command(
                AdminCommands(self.pool, name="admin"), guild=test_guild
            )
            await self.tree.sync(guild=test_guild)

        # Setup other commands globally
        self.tree.add_command(FormCommands(self.pool, selected_forms, name="forms"))
        self.tree.add_command(
            FormModalCommands(self.pool, selected_forms, selected_modals, name="modals")
        )
        self.tree.add_command(
            FormQuestionCommands(self.pool, selected_modals, name="questions")
        )
        await self.tree.sync()

    async def on_ready(self) -> None:
        await self.change_presence(status=discord.Status.offline)

        # Attach Discord log handler
        log_channel = self.get_channel(int(os.getenv("FORMS_LOG_CHANNEL", "0")))
        if isinstance(log_channel, discord.TextChannel):
            logging.getLogger().addHandler(DiscordLogHandler(self, log_channel))
        else:
            logging.getLogger("client").warning("Discord logging channel not found")
        logging.getLogger("client").info("Booted up")


if __name__ == "__main__":
    Client().run(os.getenv("FORMS_TOKEN", "MISSING"), root_logger=True)
