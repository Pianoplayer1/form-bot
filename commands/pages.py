import logging

import asyncpg
import discord
from discord import app_commands, ui

from database.models import Page
from utils.responses import respond_error, respond_success

log = logging.getLogger(__name__)


class PageEditModal(ui.Modal):
    def __init__(self, pool: asyncpg.Pool, page: Page) -> None:
        super().__init__(title=f"Editing {page.label:.37}")
        self.pool = pool
        self.form_id = page.form_id
        self.original_label = page.label

        self.label_input: ui.TextInput[PageEditModal] = ui.TextInput(
            default=page.label,
            max_length=80,
        )
        self.title_input: ui.TextInput[PageEditModal] = ui.TextInput(
            default=page.title,
            required=False,
            max_length=45,
        )

        self.add_item(
            ui.Label(
                text="Label",
                description="The label of the button for this page.",
                component=self.label_input,
            )
        )
        self.add_item(
            ui.Label(
                text="Title",
                description="Defaults to the form name.",
                component=self.title_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query_exists = "SELECT TRUE FROM pages WHERE form_id = $1 AND label = $2;"
        query_update = (
            "UPDATE pages SET label = $3, title = $4 WHERE form_id = $1 AND label = $2;"
        )

        label = self.label_input.value
        if label != self.original_label and await self.pool.fetchval(
            query_exists, self.form_id, label
        ):
            await respond_error(
                interaction,
                f"A page with label `{label}` already exists in this form.",
            )
            return

        await self.pool.execute(
            query_update,
            self.form_id,
            self.original_label,
            label,
            self.title_input.value or None,
        )
        log.info("%s edited page %r", interaction.user, label)
        await respond_success(interaction, f"Page `{label}` updated.")


@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
class FormPageCommands(app_commands.Group):
    def __init__(self, pool: asyncpg.Pool, selected_forms: dict[int, int]) -> None:
        super().__init__(name="pages")
        self.pool = pool
        self.selected_forms = selected_forms

    async def page_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        query = "SELECT label FROM pages WHERE form_id = $1 AND label ILIKE $2;"

        form_id = self.selected_forms.get(interaction.user.id)
        return [
            app_commands.Choice(name=record["label"], value=record["label"])
            for record in await self.pool.fetch(query, form_id, current + "%")
        ]

    @app_commands.command()
    @app_commands.describe(label="The label of the button for this page.")
    async def add(
        self, interaction: discord.Interaction, label: app_commands.Range[str, 1, 80]
    ) -> None:
        """Add a new page to the selected form and open the editor."""
        query_insert = (
            "INSERT INTO pages (form_id, label) VALUES ($1, $2)"
            " ON CONFLICT (form_id, label) DO NOTHING RETURNING id;"
        )
        query_get = "SELECT * FROM pages WHERE id = $1;"

        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        page_id = await self.pool.fetchval(query_insert, form_id, label)
        if page_id is None:
            await respond_error(
                interaction, f"A page with label `{label}` already exists in this form."
            )
            return

        if row := await self.pool.fetchrow(query_get, page_id):
            db_page = Page(**dict(row))
            log.info("%s added page %r", interaction.user, label)
            await interaction.response.send_modal(PageEditModal(self.pool, db_page))
        else:
            await respond_error(interaction, "Failed to create page.")

    @app_commands.command()
    @app_commands.autocomplete(page=page_autocomplete)
    @app_commands.describe(page="The page to edit.")
    async def edit(
        self, interaction: discord.Interaction, page: app_commands.Range[str, 1, 80]
    ) -> None:
        """Edit a page of the selected form."""
        query = "SELECT * FROM pages WHERE form_id = $1 AND label = $2;"

        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        if row := await self.pool.fetchrow(query, form_id, page):
            db_page = Page(**dict(row))
            await interaction.response.send_modal(PageEditModal(self.pool, db_page))
        else:
            await respond_error(interaction, f"Page `{page}` not found in this form.")

    @app_commands.command()
    @app_commands.autocomplete(page=page_autocomplete)
    @app_commands.describe(page="The page to remove.")
    async def remove(
        self, interaction: discord.Interaction, page: app_commands.Range[str, 1, 80]
    ) -> None:
        """Remove a page from the selected form. This is permanent."""
        query = "DELETE FROM pages WHERE form_id = $1 AND label = $2 RETURNING id;"

        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        if await self.pool.fetchval(query, form_id, page):
            log.info("%s removed page %r", interaction.user, page)
            await respond_success(interaction, f"Page `{page}` removed.")
        else:
            await respond_error(interaction, f"Page `{page}` not found in this form.")
