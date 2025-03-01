def table(columns: dict[str, int], data: list[list[str]]) -> str:
    message = "│"

    for column, width in columns.items():
        message += f" {column.ljust(width - 1)}│"

    message += "\n├" + "┼".join("─" * width for width in columns.values()) + "┤"

    for row in data:
        message += "\n│"
        for i in range(len(columns)):
            try:
                message += f" {str(row[i]).ljust(list(columns.values())[i] - 1)}│"
            except IndexError:
                message += " " * (list(columns.values())[i]) + "│"

    return message
