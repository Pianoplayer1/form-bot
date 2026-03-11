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
        self.items: list[ui.TextInput[PageEditModal]] = [
            ui.TextInput(
                label="Label",
                placeholder="The label of the button for this page.",
                default=modal.label,
                max_length=80,
            ),
            ui.TextInput(
                label="Title",
                placeholder=(
                    "The title of the page pop-up. Defaults to the form name."
                ),
                default=modal.title,
                required=False,
                max_length=45,
            ),
        ]
        for item in self.items:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query_exists = "SELECT TRUE FROM modals WHERE form_id = $1 AND label = $2;"
        query_update = (
            "UPDATE modals SET label = $3, title = $4"
            " WHERE form_id = $1 AND label = $2;"
        )

        if self.items[0].value != self.items[0].default and await self.pool.fetchval(
            query_exists, self.form_id, self.items[0].value
        ):
            await respond_error(
                interaction,
                f"A page with label `{self.items[0].value}`"
                " already exists in the selected form.",
            )
            return

        await self.pool.execute(
            query_update,
            self.form_id,
            self.items[0].default,
            self.items[0].value,
            self.items[1].value or None,
        )
        log.info("%s edited page %r", interaction.user, self.items[0].value)
        await respond_success(interaction, f"Page `{self.items[0].value}` updated.")


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
    @app_commands.describe(
        label="The label of the button for this page.",
        title="The title of the page pop-up. Defaults to the form name.",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        label: app_commands.Range[str, 1, 80],
        title: app_commands.Range[str, 1, 45] | None = None,
    ) -> None:
        """Add a new page to the selected form."""
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        query = (
            "INSERT INTO modals (form_id, label, title) VALUES ($1, $2, $3)"
            " ON CONFLICT (form_id, label) DO NOTHING RETURNING label;"
        )

        if await self.pool.fetchval(query, form_id, label, title) is None:
            await respond_error(
                interaction,
                f"A page with label `{label}` already exists in the selected form.",
            )
        else:
            log.info("%s added page %r", interaction.user, label)
            await respond_success(interaction, f"Page `{label}` added.")

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
