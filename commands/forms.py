import logging

import asyncpg
import discord
from discord import app_commands, ui

from database.models import Form
from utils.responses import respond_error, respond_success
from views.send import SendView

log = logging.getLogger(__name__)


class FormEditModal(ui.Modal):
    def __init__(self, pool: asyncpg.Pool, form: Form) -> None:
        super().__init__(title=f"Editing {form.name:.37}")
        self.pool = pool
        self.original_name = form.name

        self.name_input: ui.TextInput[FormEditModal] = ui.TextInput(
            default=form.name,
            max_length=45,
        )
        self.message_input: ui.TextInput[FormEditModal] = ui.TextInput(
            style=discord.TextStyle.long,
            default=form.message,
            required=False,
            max_length=2000,
        )
        self.confirmation_input: ui.TextInput[FormEditModal] = ui.TextInput(
            style=discord.TextStyle.long,
            default=form.confirmation,
            required=False,
            max_length=2000,
        )
        self.channel_input: ui.TextInput[FormEditModal] = ui.TextInput(
            default=str(form.channel) if form.channel is not None else None,
            required=False,
            max_length=18,
        )
        self.checkboxes: ui.CheckboxGroup[FormEditModal] = ui.CheckboxGroup(
            options=[
                discord.CheckboxGroupOption(
                    label="Ping @everyone on new response",
                    value="ping",
                    default=form.ping,
                ),
            ],
        )

        self.add_item(ui.Label(text="Name", component=self.name_input))
        self.add_item(
            ui.Label(
                text="Message",
                description="Displayed to users filling out this form.",
                component=self.message_input,
            )
        )
        self.add_item(
            ui.Label(
                text="Confirmation",
                description="Shown after submitting. Defaults to 'Response Recorded!'",
                component=self.confirmation_input,
            )
        )
        self.add_item(
            ui.Label(
                text="Channel",
                description="The ID of the text channel where responses are sent.",
                component=self.channel_input,
            )
        )
        self.add_item(self.checkboxes)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query_exists = "SELECT TRUE FROM forms WHERE name = $1;"
        query_update = (
            "UPDATE forms SET name = $1, message = $2, confirmation = $3"
            " , channel = $4, ping = $5 WHERE name = $6;"
        )

        name = self.name_input.value
        if name != self.original_name and await self.pool.fetchval(query_exists, name):
            await respond_error(
                interaction, f"A form with name `{name}` already exists."
            )
            return

        channel = None
        if self.channel_input.value:
            try:
                channel = abs(int(self.channel_input.value))
            except ValueError:
                await respond_error(interaction, "Not a valid channel ID.")
                return

        ping = "ping" in self.checkboxes.values

        await self.pool.execute(
            query_update,
            name,
            self.message_input.value or None,
            self.confirmation_input.value or None,
            channel,
            ping,
            self.original_name,
        )
        log.info("%s edited form %r", interaction.user, name)
        await respond_success(interaction, f"Form `{name}` updated.")


@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
class FormCommands(app_commands.Group):
    def __init__(
        self,
        pool: asyncpg.Pool,
        selected_forms: dict[int, int],
        name: str,
    ) -> None:
        super().__init__(name=name)
        self.pool = pool
        self.selected_forms = selected_forms

    async def form_autocomplete(
        self, _: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        query = "SELECT name FROM forms WHERE name ILIKE $1;"

        return [
            app_commands.Choice(name=record["name"], value=record["name"])
            for record in await self.pool.fetch(query, current + "%")
        ]

    @app_commands.command()
    @app_commands.describe(name="The name of the form.")
    async def create(
        self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 45]
    ) -> None:
        """Create a new form and open the editor."""
        query = (
            "INSERT INTO forms (name) VALUES ($1)"
            " ON CONFLICT (name) DO NOTHING"
            " RETURNING id;"
        )

        form_id = await self.pool.fetchval(query, name)
        if form_id is None:
            await respond_error(
                interaction, f"A form with name `{name}` already exists."
            )
            return

        self.selected_forms[interaction.user.id] = form_id
        log.info("%s created form %r", interaction.user, name)

        query_get = "SELECT * FROM forms WHERE id = $1;"
        row = await self.pool.fetchrow(query_get, form_id)
        if row is None:
            await respond_error(interaction, "Failed to create form.")
            return
        await interaction.response.send_modal(
            FormEditModal(self.pool, Form(**dict(row)))
        )

    @app_commands.command()
    @app_commands.autocomplete(form=form_autocomplete)
    @app_commands.describe(form="The form to edit.")
    async def edit(
        self, interaction: discord.Interaction, form: app_commands.Range[str, 1, 45]
    ) -> None:
        """Edit a form."""
        query = "SELECT * FROM forms WHERE name = $1;"

        row = await self.pool.fetchrow(query, form)
        if row is None:
            await respond_error(interaction, f"Form `{form}` not found.")
        else:
            f = Form(**dict(row))
            self.selected_forms[interaction.user.id] = f.id
            await interaction.response.send_modal(FormEditModal(self.pool, f))

    @app_commands.command()
    @app_commands.autocomplete(form=form_autocomplete)
    @app_commands.describe(form="The form to select.")
    async def select(
        self, interaction: discord.Interaction, form: app_commands.Range[str, 1, 45]
    ) -> None:
        """Select a form to manage its pages and questions."""
        query = "SELECT id FROM forms WHERE name = $1;"

        form_id = await self.pool.fetchval(query, form)
        if form_id is None:
            await respond_error(interaction, f"Form `{form}` not found.")
        else:
            self.selected_forms[interaction.user.id] = form_id
            await respond_success(interaction, f"Form `{form}` selected.")

    @app_commands.command()
    @app_commands.autocomplete(form=form_autocomplete)
    @app_commands.describe(form="The form to remove.")
    async def remove(
        self, interaction: discord.Interaction, form: app_commands.Range[str, 1, 45]
    ) -> None:
        """Remove a form. This is permanent."""
        query = "DELETE FROM forms WHERE name = $1 RETURNING id;"

        deleted_id = await self.pool.fetchval(query, form)
        if deleted_id is None:
            await respond_error(interaction, f"Form `{form}` not found.")
        else:
            if self.selected_forms.get(interaction.user.id) == deleted_id:
                del self.selected_forms[interaction.user.id]
            log.info("%s removed form %r", interaction.user, form)
            await respond_success(interaction, f"Form `{form}` removed.")

    @app_commands.command()
    @app_commands.describe(
        channel="The text channel to send the message to.",
        content="The text above the form button(s).",
    )
    async def send(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | discord.Thread,
        content: str,
    ) -> None:
        """Send a message with form buttons to a channel."""
        query = "SELECT * FROM forms;"

        embed = discord.Embed(
            title="New form message", description=f"Will be sent in {channel.mention}"
        )
        embed.add_field(
            name="Button 1/1", value="Current Label: [None]\nCurrent Emoji: [None]"
        )
        forms = [Form(**dict(r)) for r in await self.pool.fetch(query)]
        await interaction.response.send_message(
            embed=embed, view=SendView(self.pool, channel, content, embed, forms)
        )
