import asyncpg
import discord
from discord import app_commands, ui

from models import Modal
from utils.responses import respond_error, respond_success


class ModalEditModal(ui.Modal):
    def __init__(self, pool: asyncpg.Pool, modal: Modal) -> None:
        super().__init__(title=f"Editing {modal.label:.37}")
        self.pool = pool
        self.form_id = modal.form_id
        self.items: list[ui.TextInput[ModalEditModal]] = [
            ui.TextInput(
                label="Label",
                placeholder="The label of the button that opens this modal.",
                default=modal.label,
                max_length=80,
            ),
            ui.TextInput(
                label="Title",
                placeholder=(
                    "The title of the modal. Defaults to the title of the form this"
                    " modal belongs to."
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
    def __init__(
        self,
        pool: asyncpg.Pool,
        selected_forms: dict[int, int],
        selected_modals: dict[int, int],
        name: str,
    ) -> None:
        super().__init__(name=name)
        self.pool = pool
        self.selected_forms = selected_forms
        self.selected_modals = selected_modals

    async def modal_autocomplete(
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
                f"A modal with label `{label}`"
                " already exists in the currently selected form.",
            )
        else:
            msg = f"Modal `{label}` added."
            if (
                isinstance(interaction.command, app_commands.Command)
                and (parent := interaction.command.root_parent) is not None
            ):
                msg += f"\nUse /`{parent.qualified_name}` select to add questions."
            await respond_success(interaction, msg)

    @app_commands.command()
    @app_commands.autocomplete(modal=modal_autocomplete)
    @app_commands.describe(modal="The label of the modal you want to edit.")
    async def edit(
        self, interaction: discord.Interaction, modal: app_commands.Range[str, 1, 80]
    ) -> None:
        """Edit a modal of the currently selected form."""
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        query = "SELECT * FROM modals WHERE form_id = $1 AND label = $2;"

        row = await self.pool.fetchrow(query, form_id, modal)
        if row is None:
            await respond_error(
                interaction,
                f"Modal `{modal}` not found in the currently selected form.",
            )
        else:
            await interaction.response.send_modal(
                ModalEditModal(self.pool, Modal(**dict(row)))
            )

    @app_commands.command()
    @app_commands.autocomplete(modal=modal_autocomplete)
    @app_commands.describe(modal="The label of the modal you want to select.")
    async def select(
        self, interaction: discord.Interaction, modal: app_commands.Range[str, 1, 80]
    ) -> None:
        """Select a modal of the currently selected form to manage its questions."""
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        query = "SELECT id FROM modals WHERE form_id = $1 AND label = $2;"

        modal_id = await self.pool.fetchval(query, form_id, modal)
        if modal_id is None:
            await respond_error(
                interaction,
                f"Modal `{modal}` not found in the currently selected form.",
            )
        else:
            self.selected_modals[interaction.user.id] = modal_id
            await respond_success(
                interaction,
                f"Modal `{modal}` selected.\nYou can now use modal commands to edit"
                " its questions.",
            )

    @app_commands.command()
    @app_commands.autocomplete(modal=modal_autocomplete)
    @app_commands.describe(modal="The label of the modal you want to remove.")
    async def remove(
        self, interaction: discord.Interaction, modal: app_commands.Range[str, 1, 80]
    ) -> None:
        """Remove a modal of the selected form. WARNING: This action is permanent."""
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        query = "DELETE FROM modals WHERE form_id = $1 AND label = $2 RETURNING id;"

        if await self.pool.fetchval(query, form_id, modal) is None:
            await respond_error(
                interaction,
                f"Modal `{modal}` not found in the currently selected form.",
            )
        else:
            await respond_success(interaction, f"Modal `{modal}` removed.")
