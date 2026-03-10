import asyncpg
import discord
from discord import app_commands, ui

from models import Form
from utils.responses import respond_error, respond_success
from views.send import SendView


class FormEditModal(ui.Modal):
    def __init__(self, pool: asyncpg.Pool, form: Form) -> None:
        super().__init__(title=f"Editing {form.name:.37}")
        self.pool = pool
        self.items: list[ui.TextInput[FormEditModal]] = [
            ui.TextInput(label="Name", default=form.name, max_length=45),
            ui.TextInput(
                label="Message",
                style=discord.TextStyle.long,
                placeholder=(
                    "The initial message that is displayed to users filling out this"
                    " form."
                ),
                default=form.message,
                required=False,
                max_length=2000,
            ),
            ui.TextInput(
                label="Confirmation",
                style=discord.TextStyle.long,
                placeholder=(
                    "The confirmation message users get after submitting. Defaults to"
                    " 'Response Recorded!'"
                ),
                default=form.confirmation,
                required=False,
                max_length=2000,
            ),
            ui.TextInput(
                label="Channel",
                placeholder="The id of a text channel where responses will be sent to.",
                default=str(form.channel) if form.channel is not None else None,
                required=False,
                max_length=18,
            ),
        ]
        for item in self.items:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query_exists = "SELECT TRUE FROM forms WHERE name = $1;"
        query_update = (
            "UPDATE forms SET name = $1, message = $2, confirmation = $3, channel = $4"
            " WHERE name = $5;"
        )

        if self.items[0].value != self.items[0].default and await self.pool.fetchval(
            query_exists, self.items[0].value
        ):
            await respond_error(
                interaction, f"A form with name `{self.items[0].value}` already exists."
            )
            return

        channel = None
        if self.items[3].value:
            try:
                channel = abs(int(self.items[3].value))
            except ValueError:
                await respond_error(interaction, "Not a valid channel id.")
                return

        await self.pool.execute(
            query_update,
            self.items[0].value,
            self.items[1].value or None,
            self.items[2].value or None,
            channel,
            self.items[0].default,
        )
        await respond_success(interaction, f"Form `{self.items[0].value}` updated.")


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
    @app_commands.describe(
        name="The name (title) of the form.",
        message="The initial message that is displayed to users filling out this form.",
        confirmation=(
            "The confirmation message users get after submitting. Defaults to 'Response"
            " Recorded!'"
        ),
        channel="The text channel where responses will be sent to.",
        ping="Whether @everyone should get pinged when the form response is sent.",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        name: app_commands.Range[str, 1, 45],
        message: str | None = None,
        confirmation: str | None = None,
        channel: discord.TextChannel | discord.Thread | None = None,
        ping: bool = False,
    ) -> None:
        """Create a new form."""
        query = (
            "INSERT INTO forms (name, message, confirmation, channel, ping)"
            " VALUES ($1, $2, $3, $4, $5)"
            " ON CONFLICT (name) DO NOTHING"
            " RETURNING name;"
        )

        result_name = await self.pool.fetchval(
            query,
            name,
            message,
            confirmation,
            None if channel is None else channel.id,
            ping,
        )
        if result_name is None:
            await respond_error(
                interaction, f"A form with name `{name}` already exists."
            )
        else:
            msg = f"Form `{name}` created."
            if (
                isinstance(interaction.command, app_commands.Command)
                and (parent := interaction.command.root_parent) is not None
            ):
                msg += (
                    f"\nUse `/{parent.qualified_name}` select to add modals"
                    f" (pop-up windows that contain the actual form questions)."
                )
            await respond_success(interaction, msg)

    @app_commands.command()
    @app_commands.describe(form="The name of the form you want to edit.")
    @app_commands.autocomplete(form=form_autocomplete)
    async def edit(
        self, interaction: discord.Interaction, form: app_commands.Range[str, 1, 45]
    ) -> None:
        """Edit a form."""
        query = "SELECT * FROM forms WHERE name = $1;"

        row = await self.pool.fetchrow(query, form)
        if row is None:
            await respond_error(interaction, f"Form `{form}` not found.")
        else:
            await interaction.response.send_modal(
                FormEditModal(self.pool, Form(**dict(row)))
            )

    @app_commands.command()
    @app_commands.describe(form="The name of the form you want to select.")
    @app_commands.autocomplete(form=form_autocomplete)
    async def select(
        self, interaction: discord.Interaction, form: app_commands.Range[str, 1, 45]
    ) -> None:
        """Select a form to manage its modals."""
        query = "SELECT id FROM forms WHERE name = $1;"

        form_id = await self.pool.fetchval(query, form)
        if form_id is None:
            await respond_error(interaction, f"Form `{form}` not found.")
        else:
            self.selected_forms[interaction.user.id] = form_id
            await respond_success(
                interaction,
                f"Form `{form}` selected.\nYou can now use modal commands to edit its"
                " modals (pop-up windows that contain the form questions).",
            )

    @app_commands.command()
    @app_commands.describe(form="The name of the form you want to remove.")
    @app_commands.autocomplete(form=form_autocomplete)
    async def remove(
        self, interaction: discord.Interaction, form: app_commands.Range[str, 1, 45]
    ) -> None:
        """Remove a form. WARNING: This action is permanent, deleting all responses."""
        query = "DELETE FROM forms WHERE name = $1 RETURNING id;"

        if await self.pool.fetchval(query, form) is None:
            await respond_error(interaction, f"Form `{form}` not found.")
        else:
            await respond_success(interaction, f"Form `{form}` removed.")

    @app_commands.command()
    @app_commands.describe(
        channel="The text channel this will get sent to.",
        content="The text above the form button(s).",
    )
    async def send(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | discord.Thread,
        content: str,
    ) -> None:
        """Send a message with buttons for one or multiple forms to a channel."""
        query = "SELECT * FROM forms;"

        embed = discord.Embed(
            title="New form message",
            description=f"Will be sent in {channel.mention}",
        )
        embed.add_field(
            name="Button 1/1", value="Current Label: [None]\nCurrent Emoji: [None]"
        )
        forms = [Form(**dict(r)) for r in await self.pool.fetch(query)]
        await interaction.response.send_message(
            embed=embed,
            view=SendView(self.pool, channel, content, embed, forms),
        )
