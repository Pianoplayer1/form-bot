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
        self.has_started = False
        super().__init__(intents=discord.Intents.default())
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        query_ids = "SELECT DISTINCT message_id FROM form_views ORDER BY id;"
        query_views = "SELECT * FROM form_views WHERE message_id = $1;"

        self.pool = await asyncpg.create_pool(os.getenv("FORMS_DB_URL"))
        for record in await self.pool.fetch(query_ids):
            view = StarterView(
                self.pool,
                record["message_id"],
                [
                    (
                        v["label"],
                        v["emoji"],
                        discord.ButtonStyle(v["style"]),
                        v["form_id"],
                    )
                    for v in await self.pool.fetch(query_views, record["message_id"])
                ],
            )
            self.add_view(view, message_id=record["message_id"])

        test_guild_id = os.getenv("FORMS_TEST_GUILD")
        if test_guild_id is not None:
            test_guild = discord.Object(int(test_guild_id))
            self.tree.add_command(AdminCommands(name="admin"), guild=test_guild)
            await self.tree.sync(guild=test_guild)
        self.tree.add_command(FormCommands(self.pool, name="forms"))
        self.tree.add_command(FormModalCommands(self.pool, name="modals"))
        self.tree.add_command(FormQuestionCommands(self.pool, name="questions"))
        await self.tree.sync()

    async def on_ready(self) -> None:
        await self.change_presence(status=discord.Status.offline)
        if not self.has_started:
            self.has_started = True
        log_channel = self.get_channel(int(os.getenv("FORMS_LOG_CHANNEL", "0")))
        if isinstance(log_channel, discord.TextChannel):
            logging.getLogger().addHandler(DiscordLogHandler(self, log_channel))
        else:
            logging.getLogger("client").warning("Discord logging channel not found")
        logging.getLogger("client").info("Booted up")


Client().run(os.getenv("FORMS_TOKEN", "MISSING"), root_logger=True)
