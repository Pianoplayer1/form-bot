import logging

import asyncpg
import discord
from discord import CheckboxGroupOption, app_commands, ui

from database.models import Question
from utils.responses import respond_error, respond_success

log = logging.getLogger(__name__)


class QuestionEditModal(ui.Modal):
    def __init__(self, pool: asyncpg.Pool, question: Question) -> None:
        super().__init__(title=f"Editing {question.label:.37}")
        self.pool = pool
        self.modal_id = question.modal_id

        self.label_input: ui.TextInput[QuestionEditModal] = ui.TextInput(
            label="Label",
            placeholder="The label (title) of the question.",
            default=question.label,
            max_length=45,
        )
        self.description_input: ui.TextInput[QuestionEditModal] = ui.TextInput(
            label="Description",
            placeholder="An optional description shown below the label.",
            default=question.description,
            required=False,
            max_length=100,
        )
        self.placeholder_input: ui.TextInput[QuestionEditModal] = ui.TextInput(
            label="Placeholder",
            placeholder="A placeholder text like this for this question.",
            default=question.placeholder,
            required=False,
            max_length=100,
        )
        self.checkboxes: ui.CheckboxGroup[QuestionEditModal] = ui.CheckboxGroup(
            options=[
                CheckboxGroupOption(
                    label="Long answer field",
                    value="paragraph",
                    default=question.paragraph,
                ),
                CheckboxGroupOption(
                    label="Required",
                    value="required",
                    default=question.required,
                ),
            ],
        )
        self.length_input: ui.TextInput[QuestionEditModal] = ui.TextInput(
            label="Answer length req., formatted as (min)-(max)",
            placeholder="The maximum length can be up to 1024, defaults to 1000.",
            default=(
                f"{question.min_length or ''}-{question.max_length or ''}"
                if question.min_length or question.max_length
                else None
            ),
            required=False,
            max_length=80,
        )

        self.add_item(self.label_input)
        self.add_item(self.description_input)
        self.add_item(self.placeholder_input)
        self.add_item(self.checkboxes)
        self.add_item(self.length_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query_exists = "SELECT TRUE FROM questions WHERE modal_id = $1 AND label = $2;"
        query_update = (
            "UPDATE questions"
            " SET label = $3, description = $4, placeholder = $5, paragraph = $6"
            " , required = $7, min_length = $8, max_length = $9"
            " WHERE modal_id = $1 AND label = $2;"
        )

        label = self.label_input.value
        if label != self.label_input.default and await self.pool.fetchval(
            query_exists, self.modal_id, label
        ):
            await respond_error(
                interaction,
                f"A question with label `{label}` already exists on this page.",
            )
            return

        selected = self.checkboxes.values
        long_answer = "paragraph" in selected
        required = "required" in selected
        min_length = max_length = None
        if self.length_input.value:
            try:
                parts = self.length_input.value.split("-")
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
            self.label_input.default,
            label,
            self.description_input.value or None,
            self.placeholder_input.value or None,
            long_answer,
            required,
            min_length,
            max_length,
        )
        log.info("%s edited question %r", interaction.user, label)
        await respond_success(interaction, f"Question `{label}` updated.")


@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
class FormQuestionCommands(app_commands.Group):
    def __init__(
        self,
        pool: asyncpg.Pool,
        selected_forms: dict[int, int],
        name: str,
    ) -> None:
        super().__init__(name=name)
        self.pool = pool
        self.selected_forms = selected_forms

    async def _fetch_numbered_questions(self, form_id: int) -> list[tuple[str, int]]:
        """Return (display_name, question_id) pairs for all questions in a form."""
        query = (
            "SELECT q.id, q.label, m.id AS modal_id"
            " FROM questions q JOIN modals m ON q.modal_id = m.id"
            " WHERE m.form_id = $1"
            " ORDER BY m.id, q.id;"
        )
        rows = await self.pool.fetch(query, form_id)

        result: list[tuple[str, int]] = []
        page_num = 0
        current_modal_id = None
        question_num = 0
        for row in rows:
            if row["modal_id"] != current_modal_id:
                current_modal_id = row["modal_id"]
                page_num += 1
                question_num = 0
            question_num += 1
            display = f"{page_num}.{question_num} {row['label']}"
            result.append((display, row["id"]))
        return result

    async def question_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            return []

        entries = await self._fetch_numbered_questions(form_id)
        current_lower = current.lower()
        return [
            app_commands.Choice(name=display[:100], value=str(qid))
            for display, qid in entries
            if current_lower in display.lower()
        ][:25]

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
        label="The label (title) of the question.",
        page="The page to add to. Auto-assigned if not specified.",
    )
    @app_commands.autocomplete(page=page_autocomplete)
    async def add(
        self,
        interaction: discord.Interaction,
        label: app_commands.Range[str, 1, 45],
        page: app_commands.Range[str, 1, 80] | None = None,
    ) -> None:
        """Add a question to the selected form and open the editor."""
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        if page is not None:
            query_page = "SELECT id FROM modals WHERE form_id = $1 AND label = $2;"
            modal_id: int | None = await self.pool.fetchval(query_page, form_id, page)
            if modal_id is None:
                await respond_error(
                    interaction,
                    f"Page `{page}` not found in the selected form.",
                )
                return
        else:
            query_free = (
                "SELECT m.id FROM modals m"
                " WHERE m.form_id = $1 AND (SELECT COUNT(*)"
                " FROM questions q WHERE q.modal_id = m.id) < 5"
                " ORDER BY m.id LIMIT 1;"
            )
            modal_id = await self.pool.fetchval(query_free, form_id)
            if modal_id is None:
                query_count = "SELECT COUNT(*) FROM modals WHERE form_id = $1;"
                count: int = await self.pool.fetchval(query_count, form_id)
                query_create = (
                    "INSERT INTO modals (form_id, label) VALUES ($1, $2) RETURNING id;"
                )
                modal_id = await self.pool.fetchval(
                    query_create, form_id, f"Page {count + 1}"
                )

        query_insert = (
            "INSERT INTO questions (modal_id, label)"
            " SELECT $1, $2"
            " WHERE (SELECT COUNT(*) FROM questions"
            " WHERE modal_id = $1) < 5"
            " ON CONFLICT (modal_id, label) DO NOTHING"
            " RETURNING id;"
        )
        question_id = await self.pool.fetchval(query_insert, modal_id, label)
        if question_id is None:
            await respond_error(
                interaction,
                f"A question with label `{label}` already exists on"
                " this page or the page is full.",
            )
            return

        query_get = "SELECT * FROM questions WHERE id = $1;"
        row = await self.pool.fetchrow(query_get, question_id)
        if row is None:
            await respond_error(interaction, "Failed to create question.")
            return
        log.info("%s added question %r", interaction.user, label)
        await interaction.response.send_modal(
            QuestionEditModal(self.pool, Question(**dict(row)))
        )

    @app_commands.command()
    @app_commands.autocomplete(question=question_autocomplete)
    @app_commands.describe(question="The question to edit.")
    async def edit(self, interaction: discord.Interaction, question: str) -> None:
        """Edit a question of the selected form."""
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        query = (
            "SELECT q.* FROM questions q JOIN modals m"
            " ON q.modal_id = m.id"
            " WHERE m.form_id = $1 AND q.id = $2;"
        )
        try:
            row = await self.pool.fetchrow(query, form_id, int(question))
        except ValueError:
            row = None

        if row is None:
            await respond_error(interaction, "Question not found.")
        else:
            await interaction.response.send_modal(
                QuestionEditModal(self.pool, Question(**dict(row)))
            )

    @app_commands.command()
    @app_commands.autocomplete(question=question_autocomplete)
    @app_commands.describe(question="The question to remove.")
    async def remove(self, interaction: discord.Interaction, question: str) -> None:
        """Remove a question from the selected form. This is permanent."""
        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        query = (
            "DELETE FROM questions"
            " WHERE id = $1 AND modal_id IN"
            " (SELECT id FROM modals WHERE form_id = $2)"
            " RETURNING id;"
        )
        try:
            result = await self.pool.fetchval(query, int(question), form_id)
        except ValueError:
            result = None

        if result is None:
            await respond_error(interaction, "Question not found.")
        else:
            log.info("%s removed question %d", interaction.user, result)
            await respond_success(interaction, "Question removed.")
