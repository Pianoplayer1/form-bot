import logging

import asyncpg
import discord
from discord import ui

from database.models import Form
from utils.responses import respond_error, respond_success
from views.starter import StarterView

log = logging.getLogger(__name__)


class SendView(ui.View):
    def __init__(
        self,
        pool: asyncpg.Pool,
        channel: discord.TextChannel | discord.Thread,
        content: str,
        embed: discord.Embed,
        forms: list[Form],
    ) -> None:
        super().__init__(timeout=None)
        self.pool = pool
        self.channel = channel
        self.content = content
        self.embed = embed
        self.forms = forms
        self.buttons: list[
            tuple[str | None, str | None, int, int | None, ui.Select[SendView]]
        ] = []
        self.current_button = 0
        self.new_button()
        self.add_item(self.buttons[0][4])

    def new_button(self) -> None:
        select: ui.Select[SendView] = FormSelect(
            placeholder="Select a form for this button",
            options=[
                discord.SelectOption(label=form.name, value=str(form.id))
                for form in self.forms
            ],
            row=1,
        )
        self.buttons.append((None, None, 2, None, select))

    async def update(
        self,
        interaction: discord.Interaction,
        prev_select: ui.Select["SendView"] | None = None,
    ) -> None:
        self.embed.clear_fields()
        data = self.buttons[self.current_button]
        self.embed.add_field(
            name=f"Button {self.current_button + 1}/{len(self.buttons)}",
            value=(
                f"Current Label: {data[0] or '[None]'}\nCurrent Emoji:"
                f" {data[1] or '[None]'}"
            ),
        )
        self.style_button.style = discord.ButtonStyle(
            self.buttons[self.current_button][2]
        )
        if prev_select is not None:
            self.remove_item(prev_select)
            self.add_item(self.buttons[self.current_button][4])
        await interaction.response.edit_message(embed=self.embed, view=self)

    @ui.button(style=discord.ButtonStyle.primary, label="Edit Button", row=2)
    async def edit_button(
        self, interaction: discord.Interaction, _: ui.Button["SendView"]
    ) -> None:
        await interaction.response.send_modal(EditModal(self))

    @ui.button(label="Style (click to cycle)", row=2)
    async def style_button(
        self, interaction: discord.Interaction, button: ui.Button["SendView"]
    ) -> None:
        b = self.buttons[self.current_button]
        self.buttons[self.current_button] = (b[0], b[1], b[2] % 4 + 1, b[3], b[4])
        button.style = discord.ButtonStyle(self.buttons[self.current_button][2])
        await interaction.response.edit_message(view=self)

    @ui.button(label="Delete Button", style=discord.ButtonStyle.danger, row=2)
    async def delete_button(
        self, interaction: discord.Interaction, _: ui.Button["SendView"]
    ) -> None:
        prev_select = self.buttons[self.current_button][4]
        if len(self.buttons) > 0:
            del self.buttons[self.current_button]
            self.current_button = (self.current_button - 1) % len(self.buttons)
        await self.update(interaction, prev_select)

    @ui.button(style=discord.ButtonStyle.primary, emoji="⬅️", row=3)
    async def back_button(
        self, interaction: discord.Interaction, _: ui.Button["SendView"]
    ) -> None:
        prev_select = self.buttons[self.current_button][4]
        self.current_button = (self.current_button - 1) % len(self.buttons)
        await self.update(interaction, prev_select)

    @ui.button(label="Add Button", style=discord.ButtonStyle.primary, emoji="➕", row=3)
    async def add_button(
        self, interaction: discord.Interaction, _: ui.Button["SendView"]
    ) -> None:
        prev_select = self.buttons[self.current_button][4]
        self.current_button = len(self.buttons)
        self.new_button()
        await self.update(interaction, prev_select)

    @ui.button(style=discord.ButtonStyle.primary, emoji="➡️", row=3)
    async def next_button(
        self, interaction: discord.Interaction, _: ui.Button["SendView"]
    ) -> None:
        prev_select = self.buttons[self.current_button][4]
        self.current_button = (self.current_button + 1) % len(self.buttons)
        await self.update(interaction, prev_select)

    @ui.button(label="Send", style=discord.ButtonStyle.success, emoji="📨", row=3)
    async def send_button(
        self, interaction: discord.Interaction, _: ui.Button["SendView"]
    ) -> None:
        query = (
            "INSERT INTO form_views (message_id, label, emoji, style, form_id)"
            " VALUES ($1, $2, $3, $4, $5);"
        )

        if any(b[0] is None or b[3] is None for b in self.buttons):
            await respond_error(
                interaction, "You must set the label and form for each button."
            )
            return

        labels = [b[0] for b in self.buttons]
        if len(set(labels)) != len(labels):
            await respond_error(interaction, "Button labels must be unique.")
            return

        try:
            msg = await self.channel.send(self.content)
        except discord.Forbidden:
            log.warning("No permission to send to channel %d", self.channel.id)
            await respond_error(
                interaction,
                f"No access to <#{self.channel.id}>, message could not be sent.",
            )
            return

        setup_data = [
            (b[0] or "", b[1], discord.ButtonStyle(b[2]), b[3] or 0)
            for b in self.buttons
        ]
        await msg.edit(view=StarterView(self.pool, msg.id, setup_data))

        await self.pool.executemany(
            query, [(msg.id, b[0], b[1], b[2], b[3]) for b in self.buttons]
        )
        log.info(
            "%s sent form message to channel %d",
            interaction.user,
            self.channel.id,
        )
        await respond_success(
            interaction, f"Message sent to <#{self.channel.id}>.", edit=True
        )


class FormSelect(ui.Select[SendView]):
    async def callback(self, interaction: discord.Interaction) -> None:
        selected_option = None
        for option in self.options:
            option.default = False
            if option.value == self.values[0]:
                selected_option = option
        if selected_option is None:
            await respond_error(interaction, "Something went wrong.")
            return
        value = int(selected_option.value)
        if self.view is not None:
            buttons = self.view.buttons
            current_button = self.view.current_button
            v1, v2, v3, _, v4 = buttons[current_button]
            buttons[current_button] = (v1, v2, v3, value, v4)
        self.placeholder = selected_option.label
        selected_option.default = True
        await interaction.response.edit_message(view=self.view)


class EditModal(ui.Modal):
    def __init__(self, view: SendView) -> None:
        super().__init__(title=f"Editing Button {view.current_button + 1}")
        self.view = view
        self.label_input: ui.TextInput[SendView] = ui.TextInput(max_length=80)
        self.emoji_input: ui.TextInput[SendView] = ui.TextInput(
            required=False,
            max_length=32,
        )
        self.add_item(ui.Label(text="Label", component=self.label_input))
        self.add_item(
            ui.Label(
                text="Emoji",
                description="Must be an actual emoji icon, not just a name.",
                component=self.emoji_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        label = self.label_input.value
        emoji = self.emoji_input.value or None
        b = self.view.buttons[self.view.current_button]
        self.view.buttons[self.view.current_button] = (label, emoji, b[2], b[3], b[4])
        await self.view.update(interaction)
