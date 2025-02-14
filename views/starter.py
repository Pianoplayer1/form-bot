from typing import Any

import asyncpg
import discord
from discord import ui

from utils.responses import respond_error
from views.application import ApplicationView


class StarterView(ui.View):
    def __init__(
        self,
        pool: asyncpg.Pool,  # type: ignore
        message_id: int,
        setup_data: list[tuple[str, str | None, discord.ButtonStyle, int]],
    ) -> None:
        super().__init__(timeout=None)
        for i, datum in enumerate(setup_data):
            self.add_item(
                ApplicationButton(pool, *datum, custom_id=f"{message_id}-{i}")
            )


class ApplicationButton(ui.Button[StarterView]):
    def __init__(
        self,
        pool: asyncpg.Pool,  # type: ignore
        label: str,
        emoji: str | None,
        style: discord.ButtonStyle,
        form_id: int,
        **kwargs: Any,
    ) -> None:
        super().__init__(style=style, label=label, emoji=emoji, **kwargs)
        self.pool = pool
        self.form_id = form_id

    async def callback(self, interaction: discord.Interaction) -> None:
        query_form = "SELECT * FROM forms WHERE id = $1;"
        query_modals = "SELECT * FROM modals WHERE form_id = $1 ORDER BY id;"
        query_questions = "SELECT * FROM questions WHERE modal_id = $1 ORDER BY id;"

        form_record = await self.pool.fetchrow(query_form, self.form_id)
        if form_record is None:
            await respond_error(interaction, "This form does not exist anymore.")
            return

        data = [
            (modal_record, await self.pool.fetch(query_questions, modal_record["id"]))
            for modal_record in await self.pool.fetch(query_modals, self.form_id)
        ]
        await interaction.response.send_message(
            form_record["message"],
            view=ApplicationView(self.pool, form_record, data),
            ephemeral=True,
        )
