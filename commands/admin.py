import asyncio
import enum
import io
import logging
import subprocess
import textwrap
import traceback
from contextlib import redirect_stdout
from typing import Any

import asyncpg
import discord
from discord import app_commands

from utils.responses import respond_success, respond_error
from utils.tables import table


class LogLevel(enum.Enum):
    critical = logging.CRITICAL
    error = logging.ERROR
    warning = logging.WARNING
    info = logging.INFO
    debug = logging.DEBUG


async def run_command(interaction: discord.Interaction, command: str) -> None:
    process = await asyncio.create_subprocess_shell(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = (output.decode() for output in await process.communicate())
    if stderr:
        await respond_error(interaction, f"stdout:\n{stdout}\n\nstderr:\n{stderr}")
    else:
        await respond_success(interaction, stdout)


async def send_sql_results(
    interaction: discord.Interaction, records: list[Any]
) -> None:
    fmt = table(
        {c: len(c) + 2 for c in records[0].keys()}, [list(r.values()) for r in records]
    )
    fmt = f"```\n{fmt}\n```"
    if len(fmt) > 2000:
        fp = io.BytesIO(fmt.encode("utf-8"))
        await interaction.response.send_message(file=discord.File(fp, "results.txt"))
    else:
        await interaction.response.send_message(fmt)


class SQLCommands(app_commands.Group):
    def __init__(self, pool: asyncpg.Pool, **kwargs: Any):  # type: ignore
        super().__init__(**kwargs)
        self.name = "sql"
        self.pool = pool

    @app_commands.command()
    async def fetch(self, interaction: discord.Interaction, query: str) -> None:
        results = await self.pool.fetch(query)
        await send_sql_results(interaction, results)

    @app_commands.command()
    async def execute(self, interaction: discord.Interaction, query: str) -> None:
        result = await self.pool.execute(query)
        await respond_success(interaction, result)

    @app_commands.command()
    async def schema(self, interaction: discord.Interaction, table_name: str) -> None:
        query = (
            "SELECT column_name, data_type, column_default, is_nullable"
            " FROM INFORMATION_SCHEMA.COLUMNS WHERE table_name = $1;"
        )

        results = await self.pool.fetch(query, table_name)
        if len(results) == 0:
            return await respond_error(interaction, f"Table `{table_name}` not found.")
        await send_sql_results(interaction, results)

    @app_commands.command()
    async def tables(self, interaction: discord.Interaction) -> None:
        query = (
            "SELECT table_name FROM information_schema.tables WHERE"
            " table_schema='public' AND table_type='BASE TABLE'"
        )

        results = await self.pool.fetch(query)
        await send_sql_results(interaction, results)

    @app_commands.command()
    async def sizes(self, interaction: discord.Interaction) -> None:
        query = (
            "SELECT nspname || '.' || relname AS relation,"
            " pg_size_pretty(pg_relation_size(C.oid)) AS size"
            " FROM pg_class C LEFT JOIN pg_namespace N ON (N.oid = C.relnamespace)"
            " WHERE nspname NOT IN ('pg_catalog', 'information_schema')"
            " ORDER BY pg_relation_size(C.oid) DESC LIMIT 20;"
        )

        results = await self.pool.fetch(query)
        await send_sql_results(interaction, results)

    @app_commands.command()
    async def explain(self, interaction: discord.Interaction, query: str) -> None:
        query = f"EXPLAIN (ANALYZE, COSTS, VERBOSE, BUFFERS, FORMAT JSON)\n{query}"

        json = await self.pool.fetchrow(query)
        if json is None:
            return await respond_error(interaction, "DB error while analyzing query.")

        file = discord.File(
            io.BytesIO(json[0].encode("utf-8")), filename="explain.json"
        )
        await interaction.response.send_message(file=file)


@app_commands.default_permissions(administrator=True)
class AdminCommands(app_commands.Group):
    _last_result: Any | None

    def __init__(self, pool: asyncpg.Pool, **kwargs: Any):  # type: ignore
        super().__init__(**kwargs)
        self.add_command(SQLCommands(pool, **kwargs))
        self.pool = pool

    @app_commands.command()
    async def shell(self, interaction: discord.Interaction, command: str) -> None:
        await run_command(interaction, command)

    @app_commands.command()
    async def reboot(self, interaction: discord.Interaction) -> None:
        await run_command(interaction, "reboot")

    @app_commands.command()
    async def logging(
        self,
        interaction: discord.Interaction,
        level: LogLevel,
        logger: str | None = None,
    ) -> None:
        logging.getLogger(logger).setLevel(level.value)
        await respond_success(
            interaction, f"Set logging level of `{logger}` to `{level.name}`."
        )

    @app_commands.command()
    async def python(self, interaction: discord.Interaction, code: str) -> None:
        env = {"interaction": interaction, "_": self._last_result}
        try:
            exec(f"async def func():\n{textwrap.indent(code, '  ')}", env)
        except Exception as e:
            return await interaction.response.send_message(
                f"```py\n{e.__class__.__name__}: {e}\n```"
            )

        stdout = io.StringIO()
        try:
            with redirect_stdout(stdout):
                ret = await env["func"]()
        except Exception:
            value = stdout.getvalue()
            await interaction.response.send_message(
                f"```py\n{value}{traceback.format_exc()}\n```"
            )
        else:
            value = stdout.getvalue()
            if ret is None:
                self._last_result = ret
            await interaction.response.send_message(f"```py\n{value}{ret}\n```")
