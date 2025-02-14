from typing import Any

import asyncpg
import discord
from discord import app_commands, ui

from utils.responses import respond_error, respond_success


class QuestionEditModal(ui.Modal):
    def __init__(self, pool: asyncpg.Pool, record: asyncpg.Record):  # type: ignore
        super().__init__(title=f"Editing {record['label']:.37}")
        self.pool = pool
        self.modal_id = record["modal_id"]
        self.items: list[ui.TextInput[QuestionEditModal]] = [
            ui.TextInput(label="Label", default=record["label"], max_length=45),
            ui.TextInput(
                label="Placeholder",
                default=record["placeholder"],
                required=False,
                max_length=100,
            ),
            ui.TextInput(
                label="Long Answer Field?",
                default="Yes" if record["paragraph"] else "No",
                placeholder="Yes / No",
                max_length=5,
            ),
            ui.TextInput(
                label="Required?",
                default="Yes" if record["required"] else "No",
                placeholder="Yes / No",
                max_length=5,
            ),
            ui.TextInput(
                label="Length, formatted as (min)-(max)",
                default=(
                    f"{record['min_length'] or ''}-{record['max_length'] or ''}"
                    if record["min_length"] or record["max_length"]
                    else None
                ),
                placeholder="The maximum length can be up to 1024, defaults to 1000.",
                required=False,
                max_length=80,
            ),
        ]
        for item in self.items:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query_exists = "SELECT TRUE FROM questions WHERE modal_id = $1 AND label = $2;"
        query_update = (
            "UPDATE questions"
            " SET label = $3, placeholder = $4, paragraph = $5"
            " , required = $6, min_length = $7, max_length = $8"
            " WHERE modal_id = $1 AND label = $2;"
        )

        if self.items[0].value != self.items[0].default and await self.pool.fetchval(
            query_exists, self.modal_id, self.items[0].value
        ):
            await respond_error(
                interaction,
                f"A question with label `{self.items[0].value}` already exists in the"
                " currently selected modal.",
            )
            return

        long_answer = self.items[2].value.lower().startswith("y")
        required = self.items[3].value.lower().startswith("y")
        min_length = max_length = None
        if self.items[4].value:
            try:
                parts = self.items[4].value.split("-")
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise ValueError
                min_length = int(parts[0])
                if not 0 <= min_length <= 1024:
                    raise ValueError
                max_length = int(parts[1])
                if not max(1, min_length) <= max_length <= 1024:
                    raise ValueError
            except ValueError:
                await respond_error(
                    interaction,
                    "Not a valid length: Has to be between 0 and 1024, formatted as"
                    " `(min)-(max)`.",
                )
                return

        await self.pool.execute(
            query_update,
            self.modal_id,
            self.items[0].default,
            self.items[0].value,
            self.items[1].value or None,
            long_answer,
            required,
            min_length,
            max_length,
        )
        text = f"Question `{self.items[0].value}` updated."
        if self.items[2].value.lower() not in ("yes", "no"):
            text += (
                f"\n\nNote: You set the `Long Answer` field to `{self.items[2].value}`."
                " This is interpreted as a "
                + ("yes (long answer)." if long_answer else "no (short answer).")
            )
        if self.items[3].value.lower() not in ("yes", "no"):
            text += (
                f"\n\nNote: You set the `Required` field to `{self.items[3].value}`."
                " This is interpreted as a "
                + ("yes (required)." if required else "no (not required).")
            )
        await respond_success(interaction, text)


@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
class FormQuestionCommands(app_commands.Group):
    def __init__(self, pool: asyncpg.Pool, **kwargs: Any):  # type: ignore
        super().__init__(**kwargs)
        self.pool = pool

    async def question_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        query = (
            "SELECT * FROM questions"
            " JOIN selected_modals ON questions.modal_id = selected_modals.modal_id"
            " WHERE user_id = $1 AND label ILIKE $2;"
        )

        records = await self.pool.fetch(query, interaction.user.id, current + "%")
        return [
            app_commands.Choice(name=record["label"], value=record["label"])
            for record in records
        ]

    @app_commands.command()
    async def add(
        self,
        interaction: discord.Interaction,
        label: app_commands.Range[str, 1, 45],
        placeholder: app_commands.Range[str, 1, 100] | None = None,
        paragraph: bool = False,
        required: bool = True,
        min_length: app_commands.Range[int, 0, 4000] | None = None,
        max_length: app_commands.Range[int, 1, 4000] | None = None,
    ) -> None:
        query = (
            "INSERT INTO questions (modal_id, label, placeholder"
            " , paragraph, required, min_length, max_length)"
            " SELECT modal_id, $2, $3, $4, $5, $6, $7 FROM selected_modals"
            " WHERE user_id = $1 AND ("
            "  SELECT COUNT(*) FROM questions WHERE modal_id = selected_modals.modal_id"
            " ) < 5 ON CONFLICT (modal_id, label) DO NOTHING;"
        )

        result = await self.pool.execute(
            query,
            interaction.user.id,
            label,
            placeholder,
            paragraph,
            required,
            min_length,
            max_length,
        )
        if result.endswith("0"):
            await respond_error(
                interaction,
                "No modal with less than five questions selected or a question with"
                f" label `{label}` already exists in the currently selected modal.",
            )
        else:
            await respond_success(interaction, f"Question `{label}` added.")

    @app_commands.command()
    @app_commands.autocomplete(question=question_autocomplete)
    async def edit(
        self, interaction: discord.Interaction, question: app_commands.Range[str, 1, 45]
    ) -> None:
        query = (
            "SELECT questions.* FROM questions"
            " JOIN selected_modals ON questions.modal_id = selected_modals.modal_id"
            " WHERE user_id = $1 AND label = $2;"
        )

        record = await self.pool.fetchrow(query, interaction.user.id, question)
        if record is None:
            await respond_error(
                interaction,
                "No modal selected or a question with"
                f" label `{question}` already exists in the currently selected modal.",
            )
        else:
            await interaction.response.send_modal(QuestionEditModal(self.pool, record))

    @app_commands.command()
    @app_commands.autocomplete(question=question_autocomplete)
    async def remove(
        self, interaction: discord.Interaction, question: app_commands.Range[str, 1, 45]
    ) -> None:
        query = (
            "DELETE FROM questions"
            " WHERE modal_id = (SELECT modal_id FROM selected_modals WHERE user_id = $1"
            ") AND label = $2;"
        )

        record = await self.pool.fetchrow(query, interaction.user.id, question)
        if record is None:
            await respond_error(
                interaction,
                "No modal selected or a question with"
                f" label `{question}` already exists in the currently selected modal.",
            )
        else:
            await respond_success(interaction, f"Question `{question}` removed.`")
