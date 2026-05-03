import logging

import asyncpg
import discord
from discord import app_commands, ui

from database.models import Question
from utils.responses import respond_error, respond_success

log = logging.getLogger(__name__)


class QuestionEditModal(ui.Modal):
    def __init__(self, pool: asyncpg.Pool, question: Question) -> None:
        super().__init__(title=f"Editing {question.label:.37}")
        self.pool = pool
        self.page_id = question.page_id

        self.label_input: ui.TextInput[QuestionEditModal] = ui.TextInput(
            default=question.label,
            max_length=45,
        )
        self.description_input: ui.TextInput[QuestionEditModal] = ui.TextInput(
            default=question.description,
            required=False,
            max_length=100,
        )
        self.placeholder_input: ui.TextInput[QuestionEditModal] = ui.TextInput(
            default=question.placeholder,
            required=False,
            max_length=100,
        )
        self.checkboxes: ui.CheckboxGroup[QuestionEditModal] = ui.CheckboxGroup(
            options=[
                discord.CheckboxGroupOption(
                    label="Long answer field",
                    value="paragraph",
                    default=question.paragraph,
                ),
                discord.CheckboxGroupOption(
                    label="Required",
                    value="required",
                    default=question.required,
                ),
                discord.CheckboxGroupOption(
                    label="Minecraft username",
                    value="minecraft_username",
                    default=question.minecraft_username,
                ),
            ],
        )
        self.length_input: ui.TextInput[QuestionEditModal] = ui.TextInput(
            placeholder="e.g. 10-500",
            default=(
                f"{question.min_length or 0}-{question.max_length or 1024}"
                if question.min_length or question.max_length
                else None
            ),
            required=False,
            max_length=80,
        )

        self.add_item(ui.Label(text="Label", component=self.label_input))
        self.add_item(
            ui.Label(
                text="Description",
                description="Shown below the label in the form.",
                component=self.description_input,
            )
        )
        self.add_item(
            ui.Label(
                text="Placeholder",
                description="Grey hint text shown in the empty answer field.",
                component=self.placeholder_input,
            )
        )
        self.add_item(ui.Label(text="Options", component=self.checkboxes))
        self.add_item(
            ui.Label(
                text="Answer length",
                description="Formatted as min-max, up to 1024. Defaults to 1000.",
                component=self.length_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query_exists = "SELECT TRUE FROM questions WHERE page_id = $1 AND label = $2;"
        query_update = (
            "UPDATE questions"
            " SET label = $3, description = $4, placeholder = $5, paragraph = $6,"
            " required = $7, min_length = $8, max_length = $9, minecraft_username = $10"
            " WHERE page_id = $1 AND label = $2;"
        )

        label = self.label_input.value
        if label != self.label_input.default and await self.pool.fetchval(
            query_exists, self.page_id, label
        ):
            await respond_error(
                interaction,
                f"A question with label `{label}` already exists on this page.",
            )
            return

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
                    "Not a valid length: Has to be formatted as `<min>-<max>`"
                    " with 0 <= min <= max <= 1024.",
                )
                return

        await self.pool.execute(
            query_update,
            self.page_id,
            self.label_input.default,
            label,
            self.description_input.value or None,
            self.placeholder_input.value or None,
            "paragraph" in self.checkboxes.values,
            "required" in self.checkboxes.values,
            min_length,
            max_length,
            "minecraft_username" in self.checkboxes.values,
        )
        log.info("%s edited question %r", interaction.user, label)
        await respond_success(interaction, f"Question `{label}` updated.")


@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
class FormQuestionCommands(app_commands.Group):
    def __init__(self, pool: asyncpg.Pool, selected_forms: dict[int, int]) -> None:
        super().__init__(name="questions")
        self.pool = pool
        self.selected_forms = selected_forms

    async def _fetch_numbered_questions(self, form_id: int) -> list[tuple[str, str]]:
        """Return (display_name, question_id) pairs for all questions in a form."""
        query = (
            "SELECT q.label, m.id AS page_id"
            " FROM questions q JOIN pages m ON q.page_id = m.id"
            " WHERE m.form_id = $1"
            " ORDER BY m.id, q.id;"
        )
        rows = await self.pool.fetch(query, form_id)

        result: list[tuple[str, str]] = []
        page_num = 0
        current_page_id = None
        question_num = 0
        for row in rows:
            if row["page_id"] != current_page_id:
                current_page_id = row["page_id"]
                page_num += 1
                question_num = 0
            question_num += 1
            display = f"{page_num}.{question_num} {row['label']}"
            result.append((display, row["label"]))
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
            app_commands.Choice(name=display[:100], value=str(label))
            for display, label in entries
            if current_lower in display.lower()
        ][:25]

    async def page_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        query = "SELECT label FROM pages WHERE form_id = $1 AND label ILIKE $2;"

        form_id = self.selected_forms.get(interaction.user.id)
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
        query_page = "SELECT id FROM pages WHERE form_id = $1 AND label = $2;"
        query_free_page = (
            "SELECT m.id FROM pages m"
            " WHERE m.form_id = $1 AND (SELECT COUNT(*)"
            " FROM questions q WHERE q.page_id = m.id) < 5"
            " ORDER BY m.id LIMIT 1;"
        )
        query_count_pages = "SELECT COUNT(*) FROM pages WHERE form_id = $1;"
        query_insert_page = (
            "INSERT INTO pages (form_id, label) VALUES ($1, $2) RETURNING id;"
        )
        query_insert_question = (
            "INSERT INTO questions (page_id, label)"
            " SELECT $1, $2"
            " WHERE (SELECT COUNT(*) FROM questions"
            " WHERE page_id = $1) < 5"
            " ON CONFLICT (page_id, label) DO NOTHING"
            " RETURNING id;"
        )
        query_get = "SELECT * FROM questions WHERE id = $1;"

        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        if page is not None:
            page_id: int | None = await self.pool.fetchval(query_page, form_id, page)
            if page_id is None:
                await respond_error(
                    interaction, f"Page `{page}` not found in this form."
                )
                return
        else:
            page_id = await self.pool.fetchval(query_free_page, form_id)
            if page_id is None:
                count: int = await self.pool.fetchval(query_count_pages, form_id)
                page_id = await self.pool.fetchval(
                    query_insert_page, form_id, f"Page {count + 1}"
                )

        question_id = await self.pool.fetchval(query_insert_question, page_id, label)
        if question_id is None:
            await respond_error(
                interaction,
                f"A question with label `{label}` already exists on this page"
                " or the page is full.",
            )
            return

        if row := await self.pool.fetchrow(query_get, question_id):
            db_question = Question(**dict(row))
            log.info("%s added question %r", interaction.user, label)
            await interaction.response.send_modal(
                QuestionEditModal(self.pool, db_question)
            )
        else:
            await respond_error(interaction, "Failed to create question.")

    @app_commands.command()
    @app_commands.autocomplete(question=question_autocomplete)
    @app_commands.describe(question="The question to edit.")
    async def edit(self, interaction: discord.Interaction, question: str) -> None:
        """Edit a question of the selected form."""
        query = (
            "SELECT q.* FROM questions q JOIN pages m"
            " ON q.page_id = m.id"
            " WHERE m.form_id = $1 AND q.label = $2;"
        )

        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        if row := await self.pool.fetchrow(query, form_id, question):
            db_question = Question(**dict(row))
            await interaction.response.send_modal(
                QuestionEditModal(self.pool, db_question)
            )
        else:
            await respond_error(
                interaction, f"Question `{question}` not found in this form."
            )

    @app_commands.command()
    @app_commands.autocomplete(question=question_autocomplete)
    @app_commands.describe(question="The question to remove.")
    async def remove(self, interaction: discord.Interaction, question: str) -> None:
        """Remove a question from the selected form. This is permanent."""
        query = (
            "DELETE FROM questions"
            " WHERE label = $1 AND page_id IN"
            " (SELECT id FROM pages WHERE form_id = $2)"
            " RETURNING id;"
        )

        form_id = self.selected_forms.get(interaction.user.id)
        if form_id is None:
            await respond_error(interaction, "No form selected.")
            return

        if await self.pool.fetchval(query, question, form_id):
            log.info("%s removed question %r", interaction.user, question)
            await respond_success(interaction, f"Question `{question}` removed.")
        else:
            await respond_error(
                interaction, f"Question `{question}` not found in this form."
            )
