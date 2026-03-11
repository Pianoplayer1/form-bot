import logging

import asyncpg
import discord
from discord import app_commands, ui

from database.models import Modal
from utils.responses import respond_error, respond_success

log = logging.getLogger(__name__)


class PageEditModal(ui.Modal):
    def __init__(self, pool: asyncpg.Pool, modal: Modal) -> None:
        super().__init__(title=f"Editing {modal.label:.37}")
        self.pool = pool
        self.form_id = modal.form_id
        self.original_label = modal.label

        self.label_input: ui.TextInput[PageEditModal] = ui.TextInput(
            default=modal.label,
            max_length=80,
        )
        self.title_input: ui.TextInput[PageEditModal] = ui.TextInput(
            default=modal.title,
            required=False,
            max_length=45,
        )

        self.add_item(ui.Label(
            text="Label",
            description="The label of the button for this page.",
            component=self.label_input,
        ))
        self.add_item(ui.Label(
            text="Title",
            description="Defaults to the form name.",
            component=self.title_input,
        ))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query_exists = "SELECT TRUE FROM modals WHERE form_id = $1 AND label = $2;"
        query_update = (
            "UPDATE modals SET label = $3, title = $4"
            " WHERE form_id = $1 AND label = $2;"
        )

        label = self.label_input.value
        if label != self.original_label and await self.pool.fetchval(
            query_exists, self.form_id, label
        ):
            await respond_error(
                interaction,
                f"A page with label `{label}`"
                " already exists in the selected form.",
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
    def __init__(
        self,
        pool: asyncpg.Pool,
        selected_forms: dict[int, int],
        name: str,
    ) -> None:
        super().__init__(name=name)
        self.pool = pool
        self.selected_forms = selected_forms

    async def page_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            return []
        query = "SELECT label FROM modals WHERE form_id = $1 AND label ILIKE $2;"

        return [
            app_commands.Choice(name=record["label"], value=record["label"])
            for record in await self.pool.fetch(query, form_id, current + "%")
        ]

    @app_commands.command()
    @app_commands.describe(label="The label of the button for this page.")
    async def add(
        self,
        interaction: discord.Interaction,
        label: app_commands.Range[str, 1, 80],
    ) -> None:
        """Add a new page to the selected form and open the editor."""
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        query = (
            "INSERT INTO modals (form_id, label) VALUES ($1, $2)"
            " ON CONFLICT (form_id, label) DO NOTHING RETURNING id;"
        )

        modal_id = await self.pool.fetchval(query, form_id, label)
        if modal_id is None:
            await respond_error(
                interaction,
                f"A page with label `{label}`"
                " already exists in the selected form.",
            )
            return

        log.info("%s added page %r", interaction.user, label)
        query_get = "SELECT * FROM modals WHERE id = $1;"
        row = await self.pool.fetchrow(query_get, modal_id)
        if row is None:
            await respond_error(interaction, "Failed to create page.")
            return
        await interaction.response.send_modal(
            PageEditModal(self.pool, Modal(**dict(row)))
        )

    @app_commands.command()
    @app_commands.autocomplete(page=page_autocomplete)
    @app_commands.describe(page="The page to edit.")
    async def edit(
        self, interaction: discord.Interaction, page: app_commands.Range[str, 1, 80]
    ) -> None:
        """Edit a page of the selected form."""
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        query = "SELECT * FROM modals WHERE form_id = $1 AND label = $2;"

        row = await self.pool.fetchrow(query, form_id, page)
        if row is None:
            await respond_error(
                interaction,
                f"Page `{page}` not found in the selected form.",
            )
        else:
            await interaction.response.send_modal(
                PageEditModal(self.pool, Modal(**dict(row)))
            )

    @app_commands.command()
    @app_commands.autocomplete(page=page_autocomplete)
    @app_commands.describe(page="The page to remove.")
    async def remove(
        self, interaction: discord.Interaction, page: app_commands.Range[str, 1, 80]
    ) -> None:
        """Remove a page from the selected form. This is permanent."""
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        query = "DELETE FROM modals WHERE form_id = $1 AND label = $2 RETURNING id;"

        if await self.pool.fetchval(query, form_id, page) is None:
            await respond_error(
                interaction,
                f"Page `{page}` not found in the selected form.",
            )
        else:
            log.info("%s removed page %r", interaction.user, page)
            await respond_success(interaction, f"Page `{page}` removed.")
