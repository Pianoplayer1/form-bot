from dataclasses import dataclass


@dataclass(slots=True)
class Form:
    id: int
    name: str
    message: str | None
    confirmation: str | None
    channel: int | None
    ping: bool


@dataclass(slots=True)
class Modal:
    id: int
    form_id: int
    label: str
    title: str | None


@dataclass(slots=True)
class Question:
    id: int
    modal_id: int
    label: str
    description: str | None
    placeholder: str | None
    paragraph: bool
    required: bool
    min_length: int | None
    max_length: int | None
    minecraft_username: bool
