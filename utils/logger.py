import logging

import discord


class DiscordLogHandler(logging.Handler):
    def __init__(self, client: discord.Client, channel: discord.TextChannel):
        super().__init__()
        self.client = client
        self.channel = channel

    def emit(self, record: logging.LogRecord) -> None:
        log_entry = self.format(record)
        if log_entry.startswith("We are being rate limited"):
            return
        try:
            self.client.loop.create_task(self.channel.send(f"```{log_entry:.1994}```"))
        except discord.DiscordException:
            pass
