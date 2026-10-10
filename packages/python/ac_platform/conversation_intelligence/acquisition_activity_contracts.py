"""Executable wire contracts for completed analysis usage, not recorded-call totals."""

from datetime import date, timedelta
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NonnegativeInt = Annotated[int, Field(ge=0)]
WireDate = Annotated[
    str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", json_schema_extra={"format": "date"})
]
WireUUID = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        json_schema_extra={"format": "uuid"},
    ),
]


class _ReceiptContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CompletedReceiptDay(_ReceiptContract):
    date: WireDate
    analysed: NonnegativeInt
    analysed_seconds: NonnegativeInt

    @field_validator("date")
    @classmethod
    def valid_calendar_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class CompletedReceiptPerson(_ReceiptContract):
    person_id: WireUUID
    name: str
    analysed_last_30_days: NonnegativeInt
    analysed_seconds_last_30_days: NonnegativeInt
    analysed_previous_30_days: NonnegativeInt


class AccountAcquisitionActivity(_ReceiptContract):
    """Thirty consecutive IST dates; current count equals the sum of day counts."""

    timezone: Literal["Asia/Kolkata"]
    days: Annotated[list[CompletedReceiptDay], Field(min_length=30, max_length=30)]
    analysed_last_30_days: NonnegativeInt
    analysed_previous_30_days: NonnegativeInt

    @model_validator(mode="after")
    def consistent_days(self) -> Self:
        if any(
            date.fromisoformat(current.date) - date.fromisoformat(previous.date)
            != timedelta(days=1)
            for previous, current in zip(self.days, self.days[1:], strict=False)
        ):
            raise ValueError("days must be ordered consecutive calendar dates")
        if self.analysed_last_30_days != sum(entry.analysed for entry in self.days):
            raise ValueError("current count must equal the sum of day counts")
        return self


class OrganisationAcquisitionActivity(AccountAcquisitionActivity):
    """Unique people sorted by name/ID; people totals equal day and response totals."""

    people: list[CompletedReceiptPerson]

    @model_validator(mode="after")
    def consistent_people(self) -> Self:
        keys = [(person.name, person.person_id) for person in self.people]
        if keys != sorted(keys) or len({person.person_id for person in self.people}) != len(keys):
            raise ValueError("people must be unique and sorted by name and person_id")
        if self.analysed_last_30_days != sum(p.analysed_last_30_days for p in self.people):
            raise ValueError("current count must equal the sum of people counts")
        if self.analysed_previous_30_days != sum(p.analysed_previous_30_days for p in self.people):
            raise ValueError("previous count must equal the sum of people counts")
        if sum(day.analysed_seconds for day in self.days) != sum(
            person.analysed_seconds_last_30_days for person in self.people
        ):
            raise ValueError("current seconds must equal the sum of people seconds")
        return self
