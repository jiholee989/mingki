"""모델 교체 지점. 그래프는 특정 LLM 공급자에 의존하지 않는다."""

from typing import Protocol
from pydantic import BaseModel
from app.schemas import ChangeSpec, Requirement, TestCase


class RequirementsOutput(BaseModel):
    items: list[Requirement]


class LocationsOutput(BaseModel):
    items: list[ChangeSpec]


class TestsOutput(BaseModel):
    items: list[TestCase]


class Draft(BaseModel):
    diff: str
    proposal: str


class Reasoner(Protocol):
    is_demo: bool

    def requirements(self, diff: dict) -> list[Requirement]: ...
    def locate(self, state: dict, tools) -> list[ChangeSpec]: ...
    def tests(self, state: dict, tools) -> list[TestCase]: ...
    def draft(self, context: dict) -> Draft: ...
