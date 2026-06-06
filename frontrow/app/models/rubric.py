from pydantic import BaseModel, Field


class RubricDimension(BaseModel):
    dimension_id: str
    label: str
    weight: float = Field(ge=0.0, le=1.0)


class Rubric(BaseModel):
    dimensions: list[RubricDimension] = Field(
        default_factory=lambda: [
            RubricDimension(dimension_id="field_expertise", label="Field expertise", weight=0.4),
            RubricDimension(dimension_id="experience_depth", label="Experience depth", weight=0.25),
            RubricDimension(dimension_id="communication", label="Communication", weight=0.2),
            RubricDimension(
                dimension_id="behavioral_ownership",
                label="Behavioral and ownership",
                weight=0.15,
            ),
        ]
    )

    @classmethod
    def for_seniority(cls, seniority: str) -> "Rubric":
        """Create role-weighting that adapts without assuming a field.

        The same four top-level dimensions work across software, healthcare,
        trades, operations, sales, and other roles. What changes is emphasis:
        early-career roles usually need more communication/coachability signal,
        while senior roles need stronger depth and ownership signal.
        """
        seniority_key = seniority.lower()
        if seniority_key in {"fresher", "entry", "junior", "trainee", "apprentice"}:
            weights = {
                "field_expertise": 0.30,
                "experience_depth": 0.15,
                "communication": 0.30,
                "behavioral_ownership": 0.25,
            }
        elif seniority_key in {"senior", "lead", "principal", "staff", "manager"}:
            weights = {
                "field_expertise": 0.35,
                "experience_depth": 0.35,
                "communication": 0.15,
                "behavioral_ownership": 0.15,
            }
        else:
            weights = {
                "field_expertise": 0.40,
                "experience_depth": 0.25,
                "communication": 0.20,
                "behavioral_ownership": 0.15,
            }
        return cls(
            dimensions=[
                RubricDimension(
                    dimension_id="field_expertise",
                    label="Field expertise",
                    weight=weights["field_expertise"],
                ),
                RubricDimension(
                    dimension_id="experience_depth",
                    label="Experience depth",
                    weight=weights["experience_depth"],
                ),
                RubricDimension(
                    dimension_id="communication",
                    label="Communication",
                    weight=weights["communication"],
                ),
                RubricDimension(
                    dimension_id="behavioral_ownership",
                    label="Behavioral and ownership",
                    weight=weights["behavioral_ownership"],
                ),
            ]
        )
