def table(columns: list[str], data: list[list[str]]) -> str:
    widths = []
    message = "│"

    for i, column in enumerate(columns):
        width = max(*(len(row[i]) for row in data), len(column)) + 2
        widths.append(width)
        message += f" {column.ljust(width - 1)}│"

    message += "\n├" + "┼".join("─" * width for width in widths) + "┤"

    for row in data:
        message += "\n│"
        for i in range(len(columns)):
            try:
                message += f" {str(row[i]).ljust(widths[i] - 1)}│"
            except IndexError:
                message += " " * (widths[i]) + "│"

    return message
