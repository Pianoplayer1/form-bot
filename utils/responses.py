import logging

import discord


async def respond(
    interaction: discord.Interaction,
    color: int,
    title: str,
    content: str,
    *,
    edit: bool = False,
) -> None:
    embed = discord.Embed(color=color, title=title, description=content)
    if edit:
        await interaction.response.edit_message(content=content, embed=embed, view=None)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)
    logging.getLogger("client.responses").debug("%d: %s", content, interaction.user.id)


async def respond_error(
    interaction: discord.Interaction, content: str, *, edit: bool = False
) -> None:
    await respond(interaction, 0xAA0000, "Error", content, edit=edit)


async def respond_success(
    interaction: discord.Interaction, content: str, *, edit: bool = False
) -> None:
    await respond(interaction, 0x00AA00, "Success", content, edit=edit)
