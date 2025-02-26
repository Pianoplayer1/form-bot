from typing import Any

import asyncpg
import discord
from discord import app_commands, ui

from utils.responses import respond_error, respond_success


class ModalEditModal(ui.Modal):
    def __init__(self, pool: asyncpg.Pool, record: asyncpg.Record):  # type: ignore
        super().__init__(title=f"Editing {record['label']:.37}")
        self.pool = pool
        self.form_id = record["form_id"]
        self.items: list[ui.TextInput[ModalEditModal]] = [
            ui.TextInput(
                label="Label",
                placeholder="The label of the button that opens this modal.",
                default=record["label"],
                max_length=80,
            ),
            ui.TextInput(
                label="Title",
                placeholder=(
                    "The title of the modal. Defaults to the title of the form this"
                    " modal belongs to."
                ),
                default=record["title"],
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
                f"A modal with label `{self.items[0].value}`"
                " already exists in the currently selected form.",
            )
            return

        await self.pool.execute(
            query_update,
            self.form_id,
            self.items[0].default,
            self.items[0].value,
            self.items[1].value or None,
        )
        await respond_success(interaction, f"Modal `{self.items[0].value}` updated.")


@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
class FormModalCommands(app_commands.Group):
    def __init__(self, pool: asyncpg.Pool, **kwargs: Any):  # type: ignore
        super().__init__(**kwargs)
        self.pool = pool

    async def modal_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        query = (
            "SELECT modals.* FROM modals"
            " JOIN selected_forms ON modals.form_id = selected_forms.form_id"
            " WHERE user_id = $1 AND label ILIKE $2;"
        )

        records = await self.pool.fetch(query, interaction.user.id, current + "%")
        return [
            app_commands.Choice(name=record["label"], value=record["label"])
            for record in records
        ]

    @app_commands.command()
    @app_commands.describe(
        label="The label of the button that opens this modal.",
        title=(
            "The title of the modal. Defaults to the title of the form this modal"
            " belongs to."
        ),
    )
    async def add(
        self,
        interaction: discord.Interaction,
        label: app_commands.Range[str, 1, 80],
        title: app_commands.Range[str, 1, 45] | None = None,
    ) -> None:
        """Add a new modal to the currently selected form."""
        query = (
            "INSERT INTO modals (form_id, label, title)"
            " SELECT form_id, $2, $3 FROM selected_forms WHERE user_id = $1"
            " ON CONFLICT (form_id, label) DO NOTHING;"
        )

        result = await self.pool.execute(query, interaction.user.id, label, title)
        if result.endswith("0"):
            await respond_error(
                interaction,
                f"No form selected or a modal with label `{label}`"
                " already exists in the currently selected form.",
            )
        else:
            await respond_success(
                interaction,
                f"Modal `{label}` added\nSelect it with"
                f" `/{interaction.command().root_parent.qualified_name} select`"
                " to add questions.",
            )

    @app_commands.command()
    @app_commands.autocomplete(modal=modal_autocomplete)
    @app_commands.describe(modal="The label of the modal you want to edit.")
    async def edit(
        self, interaction: discord.Interaction, modal: app_commands.Range[str, 1, 80]
    ) -> None:
        """Edit a modal of the currently selected form."""
        query = (
            "SELECT modals.* FROM modals"
            " JOIN selected_forms ON modals.form_id = selected_forms.form_id"
            " WHERE user_id = $1 AND label = $2;"
        )

        record = await self.pool.fetchrow(query, interaction.user.id, modal)
        if record is None:
            await respond_error(
                interaction,
                f"No form selected or modal `{modal}` not found in the"
                " currently selected form.",
            )
        else:
            await interaction.response.send_modal(ModalEditModal(self.pool, record))

    @app_commands.command()
    @app_commands.autocomplete(modal=modal_autocomplete)
    @app_commands.describe(modal="The label of the modal you want to select.")
    async def select(
        self, interaction: discord.Interaction, modal: app_commands.Range[str, 1, 80]
    ) -> None:
        """Select a modal of the currently selected form to manage its questions."""
        query = (
            "INSERT INTO selected_modals (user_id, modal_id)"
            " SELECT user_id, id FROM modals"
            " JOIN selected_forms ON modals.form_id = selected_forms.form_id"
            " WHERE user_id = $1 AND label = $2"
            " ON CONFLICT (user_id) DO UPDATE SET modal_id = EXCLUDED.modal_id;"
        )

        result = await self.pool.execute(query, interaction.user.id, modal)
        if result.endswith("0"):
            await respond_error(
                interaction,
                f"No form selected or modal `{modal}` not found in the"
                " currently selected form.",
            )
        else:
            await respond_success(
                interaction,
                f"Modal `{modal}` selected.\nYou can now use modal commands to edit its"
                " questions.",
            )

    @app_commands.command()
    @app_commands.autocomplete(modal=modal_autocomplete)
    @app_commands.describe(modal="The label of the modal you want to remove.")
    async def remove(
        self, interaction: discord.Interaction, modal: app_commands.Range[str, 1, 80]
    ) -> None:
        """Remove a modal of the currently selected form. WARNING: This action is permanent."""
        query = (
            "DELETE FROM modals"
            " WHERE form_id = (SELECT form_id FROM selected_forms WHERE user_id = $1)"
            " AND label = $2;"
        )

        result = await self.pool.execute(query, interaction.user.id, modal)
        if result.endswith("0"):
            await respond_error(
                interaction,
                f"No form selected or modal `{modal}` not found in the"
                " currently selected form.",
            )
        else:
            await respond_success(interaction, f"Modal `{modal}` removed.")
