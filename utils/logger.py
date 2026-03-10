import contextlib
import logging

import discord


class DiscordLogHandler(logging.Handler):
    def __init__(self, client: discord.Client, channel: discord.TextChannel) -> None:
        super().__init__()
        self.client = client
        self.channel = channel

    def emit(self, record: logging.LogRecord) -> None:
        log_entry = self.format(record)
        if log_entry.startswith("We are being rate limited"):
            return
        with contextlib.suppress(discord.DiscordException):
            self.client.loop.create_task(self.channel.send(f"```{log_entry:.1994}```"))
