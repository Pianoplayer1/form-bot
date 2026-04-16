import logging

import asyncpg
import discord
from discord import ui

from database.models import Form, Page, Question
from utils.responses import respond_error
from views.fill_out import FillOutView

log = logging.getLogger(__name__)


class StarterView(ui.View):
    def __init__(
        self,
        pool: asyncpg.Pool,
        message_id: int,
        setup_data: list[tuple[str, str | None, discord.ButtonStyle, int]],
    ) -> None:
        super().__init__(timeout=None)
        for i, datum in enumerate(setup_data):
            button = ApplicationButton(pool, *datum, custom_id=f"{message_id}-{i}")
            self.add_item(button)


class ApplicationButton(ui.Button[StarterView]):
    def __init__(
        self,
        pool: asyncpg.Pool,
        label: str,
        emoji: str | None,
        style: discord.ButtonStyle,
        form_id: int,
        custom_id: str,
    ) -> None:
        super().__init__(style=style, label=label, emoji=emoji, custom_id=custom_id)
        self.pool = pool
        self.form_id = form_id

    async def callback(self, interaction: discord.Interaction) -> None:
        query_form = "SELECT * FROM forms WHERE id = $1;"
        query_pages = "SELECT * FROM pages WHERE form_id = $1 ORDER BY id;"
        query_questions = "SELECT * FROM questions WHERE page_id = $1 ORDER BY id;"

        row = await self.pool.fetchrow(query_form, self.form_id)
        if row is None:
            log.warning("Form %d not found in database", self.form_id)
            await respond_error(interaction, "This form does not exist anymore.")
            return

        form = Form(**dict(row))
        data = []
        for page_row in await self.pool.fetch(query_pages, self.form_id):
            page = Page(**dict(page_row))
            question_rows = await self.pool.fetch(query_questions, page.id)
            data.append((page, [Question(**dict(q)) for q in question_rows]))
        log.info("%s started form %r", interaction.user, form.name)
        await interaction.response.send_message(
            f"## {form.name}\n\n{form.message}\n** **",
            view=FillOutView(self.pool, form, data),
            ephemeral=True,
        )
