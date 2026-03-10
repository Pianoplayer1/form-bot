from datetime import UTC, datetime

import aiohttp
import asyncpg
import discord
from discord import ui

from models import Form, Modal, Question
from utils.responses import respond_error, respond_success


class ApplicationView(ui.View):
    def __init__(
        self,
        pool: asyncpg.Pool,
        form: Form,
        data: list[tuple[Modal, list[Question]]],
    ) -> None:
        super().__init__(timeout=None)
        self.pool = pool
        self.form = form
        self.answers: list[list[str | None]] = []
        self.questions: list[list[Question]] = []
        self.buttons: list[FormButton] = []

        for i, (modal, questions) in enumerate(data):
            self.answers.append([None] * len(questions))
            self.questions.append(questions)
            button = FormButton(
                self,
                modal.title or form.name,
                modal.label,
                i,
            )
            self.add_item(button)
            self.buttons.append(button)
        self.send_button = SendButton(self)
        self.add_item(self.send_button)


class FormButton(ui.Button[ApplicationView]):
    def __init__(
        self, parent_view: ApplicationView, title: str, label: str, index: int
    ) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.parent_view = parent_view
        self.title = title
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            FormModal(self.parent_view, self.title, self.index)
        )


class SendButton(ui.Button[ApplicationView]):
    def __init__(self, parent_view: ApplicationView) -> None:
        super().__init__(label="Send", disabled=True, style=discord.ButtonStyle.success)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        query_response = (
            "INSERT INTO responses (username, timestamp, form_id) VALUES ($1, $2, $3)"
            " RETURNING id;"
        )
        query_answers = (
            "INSERT INTO answers (response_id, question_id, answer)"
            " VALUES ($1, $2, $3);"
        )

        self.parent_view.stop()
        form = self.parent_view.form

        timestamp = datetime.now(UTC)

        # Flatten questions and answers across all modals
        all_questions = [q for modal in self.parent_view.questions for q in modal]
        all_answers = [a for modal in self.parent_view.answers for a in modal]

        # Extract Minecraft username if it's the first question
        username = None
        start = 0
        if all_questions[0].label.lower() == "minecraft username":
            username = all_answers[0]
            start = 1

        # Build the response embed
        embed = discord.Embed(color=0x859900, title=form.name, timestamp=timestamp)
        if username is not None:
            embed.title = f"{form.name} - {username}"
            embed.add_field(name="Minecraft username:", value=username, inline=False)
            embed.add_field(name="Discord username:", value=interaction.user.name)
        else:
            embed.add_field(name="Username:", value=interaction.user.display_name)

        for question, answer in zip(
            all_questions[start:], all_answers[start:], strict=False
        ):
            embed.add_field(
                name=question.label + ("" if question.label.endswith("?") else ":"),
                value=answer or "---",
                inline=False,
            )

        # Insert response and answers in a single transaction
        async with self.parent_view.pool.acquire() as conn, conn.transaction():
            response_id: int = await conn.fetchval(
                query_response, interaction.user.name, timestamp, form.id
            )
            db_answers = [
                (response_id, q.id, a)
                for q, a in zip(
                    all_questions[start:], all_answers[start:], strict=False
                )
            ]
            await conn.executemany(query_answers, db_answers)

        if username is not None:
            await add_player_stats(embed, username)

        channel = (
            interaction.client.get_channel(form.channel)
            if form.channel is not None
            else None
        )
        try:
            if not isinstance(channel, discord.TextChannel | discord.Thread):
                raise ValueError
            await channel.send("@everyone" if form.ping else None, embed=embed)
            await respond_success(
                interaction, form.confirmation or "Response recorded!", edit=True
            )
        except (discord.Forbidden, ValueError):
            await respond_error(
                interaction,
                "An error occurred when processing your response.\nPlease contact"
                " Pianoplayer1 (<@667445845792391208>).",
                edit=True,
            )


class FormModal(ui.Modal):
    def __init__(self, view: ApplicationView, title: str, index: int) -> None:
        super().__init__(title=title)
        self.view = view
        self.index = index
        self.items: list[ui.TextInput[FormModal]] = [
            ui.TextInput(
                label=question.label,
                style=(
                    discord.TextStyle.long
                    if question.paragraph
                    else discord.TextStyle.short
                ),
                placeholder=question.placeholder,
                default=value,
                required=question.required,
                min_length=question.min_length,
                max_length=question.max_length or 1000,
            )
            for question, value in zip(
                view.questions[index], view.answers[index], strict=False
            )
        ]
        for item in self.items:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        for i, item in enumerate(self.items):
            self.view.answers[self.index][i] = item.value or None
        self.view.buttons[self.index].style = discord.ButtonStyle.secondary
        if all(
            all(a is not None or not q.required for a, q in zip(*x, strict=False))
            for x in zip(self.view.answers, self.view.questions, strict=False)
        ):
            self.view.send_button.disabled = False
        await interaction.response.edit_message(view=self.view)


async def add_player_stats(embed: discord.Embed, username: str) -> None:
    async with aiohttp.ClientSession() as session:
        player_url = f"https://api.wynncraft.com/v3/player/{username}"
        res = await session.get(player_url)
        if res.status != 200:
            return
        stats = await res.json()
        res = await session.get(player_url + "/characters")
        if res.status != 200:
            highest_class = None
        else:
            char_data: dict[str, dict[str, str]] = await res.json()
            try:
                highest_class = max(
                    char_data.values(), key=lambda x: (x["level"], x["xp"])
                )
            except (ValueError, KeyError):
                highest_class = None

    try:
        guild_text = (
            "None"
            if stats["guild"] is None
            else (
                f"{stats['guild']['name']} \u001b[0m[\u001b[1;32;48m"
                f"{stats['guild']['prefix']}\u001b[0m] -"
                f" \u001b[0;32;48m{stats['guild']['rank'].title()}"
            )
        )
        first = f"\u001b[1;34;48mPlayer Stats of \u001b[1;31;48m{stats['username']}"
        second = f"\u001b[0;34;48mCurrent Guild:  \u001b[0;32;48m{guild_text}"
        third = (
            "\u001b[0;34;48mHighest Class: "
            f" \u001b[0;32;48m{highest_class['type'].title()}"
            f" Lv. {highest_class['level']}"
            if highest_class is not None
            else ""
        )
        embed.add_field(
            name="", value=f"```ansi\n{first}\n{second}\n{third}\n```", inline=False
        )
        embed.add_field(
            name="Total Level",
            value=f"```hs\n{stats['globalData']['totalLevel']}\n```",
        )
        embed.add_field(
            name="Raids",
            value=f"```hs\n{stats['globalData']['raids']['total']}\n```",
        )
        embed.add_field(name="Wars", value=f"```hs\n{stats['globalData']['wars']}\n```")
        embed.add_field(
            name="Rank",
            value=(
                f"```hs\n{str(stats['supportRank']).title().replace('plus', '+')}\n```"
            ),
        )
        embed.add_field(
            name="First Join", value=f"```hs\n{stats['firstJoin'][:10]}\n```"
        )
        embed.add_field(
            name="Playtime", value=f"```hs\n{stats['playtime']:.0f} Hours\n```"
        )
    except (KeyError, TypeError):
        pass
