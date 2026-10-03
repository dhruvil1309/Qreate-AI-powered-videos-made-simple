"""Data contracts shared by every pipeline stage.

The ScenePlan is the heart of the system: the script agent must produce it,
the critic reviews it, and every media stage reads from it.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Language = Literal["english", "hinglish", "hindi"]


class JobRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=600, description="Topic, prompt, idea or trend")
    community: str = Field("General", max_length=80, description="Target Qoneqt community")
    language: Language = "english"
    tone: str = Field("energetic", max_length=60)
    target_seconds: int = Field(45, ge=20, le=90)
    visual_style: Literal["mix", "stock", "ai"] = "mix"


class BatchRequest(BaseModel):
    topics: list[str] = Field(min_length=1, max_length=50)
    community: str = "General"
    language: Language = "english"
    tone: str = "energetic"
    target_seconds: int = Field(45, ge=20, le=90)
    visual_style: Literal["mix", "stock", "ai"] = "mix"


class Visual(BaseModel):
    mode: Literal["stock", "ai_image"] = "stock"
    query: str = Field("", description="Short stock-footage search query in English")
    prompt: str = Field("", description="Detailed image-generation prompt in English")


class Scene(BaseModel):
    id: int
    voiceover: str = Field(description="Exactly what the narrator says in this scene")
    caption: str = Field("", description="Punchy on-screen headline, max ~6 words")
    visual: Visual = Field(default_factory=Visual)

    @field_validator("caption")
    @classmethod
    def _short_caption(cls, v: str) -> str:
        words = v.split()
        return " ".join(words[:7])


class ScenePlan(BaseModel):
    title: str
    hook: str
    hook_options: list[str] = Field(default_factory=list)
    scenes: list[Scene] = Field(min_length=2, max_length=12)
    cta: str = ""
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    generated_by: str = "offline"

    @field_validator("hashtags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        out = []
        for t in v:
            t = "#" + t.strip().lstrip("#").replace(" ", "")
            if len(t) > 1 and t.lower() not in {x.lower() for x in out}:
                out.append(t)
        return out[:8]


class Critique(BaseModel):
    scores: dict[str, float] = Field(default_factory=dict)
    overall: float = 0
    issues: list[str] = Field(default_factory=list)
    rounds: int = 0
    judged_by: str = "heuristic"


class SceneEdit(BaseModel):
    voiceover: Optional[str] = None
    caption: Optional[str] = None
    visual_query: Optional[str] = None
    visual_prompt: Optional[str] = None
    visual_mode: Optional[Literal["stock", "ai_image"]] = None


class PlanEdit(BaseModel):
    """Post copy that can be changed without re-rendering any video."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    cta: Optional[str] = Field(None, max_length=200)
    hashtags: Optional[list[str]] = Field(None, max_length=12)


class HookPick(BaseModel):
    """Swap the opening line for one of the script agent's alternative hooks."""

    index: Optional[int] = Field(None, ge=0, le=11, description="Index into plan.hook_options")
    text: Optional[str] = Field(None, min_length=3, max_length=400, description="Custom hook line")
