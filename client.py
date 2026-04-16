import logging
import os

import asyncpg
import discord

from commands.forms import FormCommands
from commands.pages import FormPageCommands
from commands.questions import FormQuestionCommands
from views.starter import StarterView

log = logging.getLogger(__name__)


class Client(discord.Client):
    pool: asyncpg.Pool

    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        query_ids = "SELECT DISTINCT message_id FROM form_views;"
        query_views = "SELECT * FROM form_views WHERE message_id = $1 ORDER BY id;"

        # DB for persistent storage, dict below for local mapping of discord id to forms
        self.pool = await asyncpg.create_pool(os.getenv("FORMS_DB_URL"))
        selected_forms: dict[int, int] = {}

        # Add persistent views to client
        for record in await self.pool.fetch(query_ids):
            setup_data = [
                (r["label"], r["emoji"], discord.ButtonStyle(r["style"]), r["form_id"])
                for r in await self.pool.fetch(query_views, record["message_id"])
            ]
            view = StarterView(self.pool, record["message_id"], setup_data)
            self.add_view(view, message_id=record["message_id"])

        # Setup commands
        self.tree.add_command(FormCommands(self.pool, selected_forms))
        self.tree.add_command(FormPageCommands(self.pool, selected_forms))
        self.tree.add_command(FormQuestionCommands(self.pool, selected_forms))
        await self.tree.sync()

    async def on_ready(self) -> None:
        await self.change_presence(status=discord.Status.offline)
        log.info("Booted up")


if __name__ == "__main__":
    Client().run(os.getenv("FORMS_TOKEN", "MISSING"), root_logger=True)
