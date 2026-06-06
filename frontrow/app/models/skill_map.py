from enum import StrEnum

from pydantic import BaseModel, Field


class SkillStatus(StrEnum):
    UNTOUCHED = "untouched"
    IN_PROGRESS = "in_progress"
    SUFFICIENT = "sufficient"
    NEEDS_VALIDATION = "needs_validation"
    LOW_CONFIDENCE = "low_confidence"


class SkillNode(BaseModel):
    skill_id: str
    label: str
    dimension: str = "field_expertise"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    target_depth: str = "medium"
    current_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    attempts: int = 0
    scaffold_attempts: int = 0
    status: SkillStatus = SkillStatus.UNTOUCHED
    evidence_ids: list[str] = Field(default_factory=list)
    related_resume_claims: list[str] = Field(default_factory=list)
    related_jd_requirements: list[str] = Field(default_factory=list)


class SkillMap(BaseModel):
    skills: dict[str, SkillNode] = Field(default_factory=dict)

    def highest_priority_uncovered(self, exclude_skill_ids: set[str] | None = None) -> SkillNode | None:
        excluded = exclude_skill_ids or set()
        candidates = [
            skill
            for skill in self.skills.values()
            if skill.skill_id not in excluded and skill.status != SkillStatus.SUFFICIENT
        ]
        return max(candidates, key=lambda skill: (skill.importance, -skill.attempts), default=None)

    def next_coverage_target(self, exclude_skill_ids: set[str] | None = None) -> SkillNode | None:
        """Prefer untouched skills before revisiting partially-tested high-priority skills."""
        excluded = exclude_skill_ids or set()
        candidates = [
            skill
            for skill in self.skills.values()
            if skill.skill_id not in excluded and skill.status != SkillStatus.SUFFICIENT
        ]
        return max(
            candidates,
            key=lambda skill: (
                skill.attempts == 0,
                -skill.attempts,
                skill.importance,
            ),
            default=None,
        )

    def get_or_create(self, skill_id: str, label: str | None = None) -> SkillNode:
        if skill_id not in self.skills:
            self.skills[skill_id] = SkillNode(skill_id=skill_id, label=label or skill_id.replace("_", " "))
        return self.skills[skill_id]

    @property
    def covered_skill_ids(self) -> set[str]:
        return {
            skill.skill_id
            for skill in self.skills.values()
            if skill.status == SkillStatus.SUFFICIENT or skill.attempts > 0
        }
