from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class Signup(Login):
    nickname: str = Field(min_length=1, max_length=50)


class Post(Input):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20000)


class PostEdit(Post):
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=1, max_length=128)


class Password(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(min_length=1, max_length=128)


class Comment(Input):
    content: str = Field(min_length=1, max_length=2000)


class Report(Input):
    target_type: Literal['POST', 'COMMENT']
    target_id: str
    reason: str = Field(min_length=1, max_length=1000)


class ReportEdit(Input):
    status: Literal['RECEIVED', 'IN_REVIEW', 'RESOLVED']
    admin_note: str = Field(default='', max_length=2000)


class Rule(Input):
    rule_type: Literal['KEYWORD', 'REGEX']
    pattern: str = Field(min_length=1, max_length=500)
    match_mode: Literal['PARTIAL', 'WORD', 'REGEX']
    case_sensitive: bool = False
    replacement: str = Field(default='***', min_length=1, max_length=20)
    priority: int = Field(default=0, ge=-1000, le=1000)
